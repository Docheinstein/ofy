"""Tag writers/readers for ID3v2.4 (mp3), MP4 atoms (m4a) and Vorbis comments (opus) via mutagen."""

from __future__ import annotations

import base64
import struct
from pathlib import Path

from mutagen import id3
from mutagen.flac import Picture
from mutagen.mp3 import MP3
from mutagen.mp4 import MP4, MP4Cover, MP4FreeForm
from mutagen.oggopus import OggOpus

from ofy.tagging.mapping import FF, ID3_MAP, MP4_MAP, UFID_OWNER, VORBIS_MAP, model_to_fields
from ofy.tagging.model import TagModel

UTF8 = id3.Encoding.UTF8


class UnsupportedFormat(ValueError):
    pass


def kind_of(path: Path) -> str:
    ext = path.suffix.lower()
    if ext == ".mp3":
        return "mp3"
    if ext in (".m4a", ".mp4", ".aac"):
        return "m4a"
    if ext in (".opus", ".ogg"):
        return "opus"
    raise UnsupportedFormat(ext)


def image_mime(data: bytes) -> str:
    return "image/png" if data[:8] == b"\x89PNG\r\n\x1a\n" else "image/jpeg"


def jpeg_size(data: bytes) -> tuple[int, int]:
    """(width, height) of a JPEG/PNG, (0, 0) if unknown."""
    if data[:8] == b"\x89PNG\r\n\x1a\n" and len(data) >= 24:
        w, h = struct.unpack(">II", data[16:24])
        return w, h
    i = 2
    while i + 9 < len(data):
        if data[i] != 0xFF:
            i += 1
            continue
        marker = data[i + 1]
        if marker in (0xC0, 0xC1, 0xC2):
            h, w = struct.unpack(">HH", data[i + 5:i + 9])
            return w, h
        seg_len = struct.unpack(">H", data[i + 2:i + 4])[0]
        i += 2 + seg_len
    return 0, 0


# --- write ------------------------------------------------------------------------------------

def write_tags(path: Path, model: TagModel, cover: bytes | None = None) -> None:
    """Replace all tags of ``path`` with the model's (cover embedded if given)."""
    fields = model_to_fields(model)
    k = kind_of(path)
    if k == "mp3":
        _write_id3(path, fields, cover)
    elif k == "m4a":
        _write_mp4(path, fields, cover)
    else:
        _write_vorbis(path, fields, cover)


def _write_id3(path: Path, fields: dict[str, list[str]], cover: bytes | None) -> None:
    try:
        tags = id3.ID3(path)
    except id3.ID3NoHeaderError:
        tags = id3.ID3()
    tags.clear()
    for name, values in fields.items():
        if name in ("tracknumber", "totaltracks", "discnumber", "totaldiscs", "musicbrainz_recordingid", "lyrics"):
            continue
        key = ID3_MAP.get(name)
        if not key:
            continue
        tags.add(_id3_frame(key, values))
    if "tracknumber" in fields:
        tags.add(id3.TRCK(encoding=UTF8, text=_num_total(fields, "tracknumber", "totaltracks")))
    if "discnumber" in fields:
        tags.add(id3.TPOS(encoding=UTF8, text=_num_total(fields, "discnumber", "totaldiscs")))
    if "musicbrainz_recordingid" in fields:
        tags.add(id3.UFID(owner=UFID_OWNER, data=fields["musicbrainz_recordingid"][0].encode("ascii")))
    if "lyrics" in fields:
        tags.add(id3.USLT(encoding=UTF8, lang=_id3_lang(fields), desc="", text=fields["lyrics"][0]))
    if cover:
        tags.add(id3.APIC(encoding=UTF8, mime=image_mime(cover), type=id3.PictureType.COVER_FRONT,
                          desc="Cover", data=cover))
    tags.save(path, v2_version=4, v1=0)


def _id3_frame(key: str, values: list[str]) -> id3.Frame:
    if key.startswith("TXXX:"):
        return id3.TXXX(encoding=UTF8, desc=key[5:], text=values)
    return getattr(id3, key)(encoding=UTF8, text=values)


def _id3_lang(fields: dict[str, list[str]]) -> str:
    lang = (fields.get("language") or ["XXX"])[0]
    return lang if len(lang) == 3 else "XXX"


def _num_total(fields: dict[str, list[str]], n: str, t: str) -> str:
    return f"{fields[n][0]}/{fields[t][0]}" if t in fields else fields[n][0]


def _write_mp4(path: Path, fields: dict[str, list[str]], cover: bytes | None) -> None:
    f = MP4(path)
    if f.tags is None:
        f.add_tags()
    f.tags.clear()
    for name, values in fields.items():
        key = MP4_MAP.get(name)
        if not key:
            continue
        if key.startswith(FF):
            f.tags[key] = [MP4FreeForm(v.encode("utf-8")) for v in values]
        else:
            f.tags[key] = values
    if "tracknumber" in fields:
        f.tags["trkn"] = [(int(fields["tracknumber"][0]), int((fields.get("totaltracks") or [0])[0]))]
    if "discnumber" in fields:
        f.tags["disk"] = [(int(fields["discnumber"][0]), int((fields.get("totaldiscs") or [0])[0]))]
    if fields.get("compilation") == ["1"]:
        f.tags["cpil"] = True
    if cover:
        fmt = MP4Cover.FORMAT_PNG if image_mime(cover) == "image/png" else MP4Cover.FORMAT_JPEG
        f.tags["covr"] = [MP4Cover(cover, imageformat=fmt)]
    f.save()


def _picture_block(cover: bytes) -> str:
    pic = Picture()
    pic.type = 3  # front cover
    pic.mime = image_mime(cover)
    pic.desc = "Cover"
    pic.width, pic.height = jpeg_size(cover)
    pic.depth = 24
    pic.data = cover
    return base64.b64encode(pic.write()).decode("ascii")


def _write_vorbis(path: Path, fields: dict[str, list[str]], cover: bytes | None) -> None:
    f = OggOpus(path)
    f.tags.clear()
    for name, values in fields.items():
        key = VORBIS_MAP.get(name)
        if key:
            f.tags[key] = values
    if cover:
        f.tags["METADATA_BLOCK_PICTURE"] = [_picture_block(cover)]
    f.save()


# --- edit -------------------------------------------------------------------------------------

# Every internal name the editor may set or remove; lyrics have their own flow (sidecar files + set_lyrics).
EDITABLE: list[str] = [name for name in VORBIS_MAP if name != "lyrics"]
NUMERIC = ("tracknumber", "totaltracks", "discnumber", "totaldiscs")


def edit_fields(path: Path, changes: dict[str, list[str]]) -> None:
    """Set the given tags (internal names; an empty list removes the tag), leaving every other tag and the cover alone."""
    unknown = sorted(set(changes) - set(EDITABLE))
    if unknown:
        raise ValueError(f"Not an editable tag: {', '.join(unknown)}")
    changes = {name: [v.strip() for v in values if v.strip()] for name, values in changes.items()}
    for name in NUMERIC:
        values = changes.get(name, [])
        if len(values) > 1 or any(not v.isdigit() for v in values):
            raise ValueError(f"{name} must be a single whole number")
    if changes.get("compilation", []) not in ([], ["0"], ["1"]):
        raise ValueError("compilation must be 1 or 0")
    merged = {**read_fields(path), **changes}
    for n, t in (("tracknumber", "totaltracks"), ("discnumber", "totaldiscs")):
        if merged.get(t) and not merged.get(n):
            raise ValueError(f"{t} needs {n}")
    k = kind_of(path)
    if k == "mp3":
        _edit_id3(path, changes, merged)
    elif k == "m4a":
        _edit_mp4(path, changes, merged)
    else:
        _edit_vorbis(path, changes)


def _first(fields: dict[str, list[str]], name: str) -> str | None:
    values = fields.get(name)
    return values[0] if values else None


def _edit_id3(path: Path, changes: dict[str, list[str]], merged: dict[str, list[str]]) -> None:
    try:
        tags = id3.ID3(path)
    except id3.ID3NoHeaderError:
        tags = id3.ID3()
    for name, values in changes.items():
        if name in ("tracknumber", "totaltracks", "discnumber", "totaldiscs"):
            frame, n, t = ("TRCK", "tracknumber", "totaltracks") if "track" in name else ("TPOS", "discnumber", "totaldiscs")
            tags.delall(frame)
            if num := _first(merged, n):
                total = _first(merged, t)
                tags.add(getattr(id3, frame)(encoding=UTF8, text=f"{num}/{total}" if total else num))
        elif name == "musicbrainz_recordingid":
            tags.delall(f"UFID:{UFID_OWNER}")
            if values:
                tags.add(id3.UFID(owner=UFID_OWNER, data=values[0].encode("ascii", "replace")))
        else:
            key = ID3_MAP[name]
            tags.delall(key)
            if values:
                tags.add(_id3_frame(key, values))
    tags.save(path, v2_version=4, v1=0)


def _edit_mp4(path: Path, changes: dict[str, list[str]], merged: dict[str, list[str]]) -> None:
    f = MP4(path)
    if f.tags is None:
        f.add_tags()
    for name, values in changes.items():
        if name in ("tracknumber", "totaltracks", "discnumber", "totaldiscs"):
            atom, n, t = ("trkn", "tracknumber", "totaltracks") if "track" in name else ("disk", "discnumber", "totaldiscs")
            f.tags.pop(atom, None)
            if num := _first(merged, n):
                f.tags[atom] = [(int(num), int(_first(merged, t) or 0))]
        elif name == "compilation":
            f.tags.pop("cpil", None)
            if values == ["1"]:
                f.tags["cpil"] = True
        else:
            key = MP4_MAP[name]
            f.tags.pop(key, None)
            if values:
                f.tags[key] = [MP4FreeForm(v.encode("utf-8")) for v in values] if key.startswith(FF) else values
    f.save()


def _edit_vorbis(path: Path, changes: dict[str, list[str]]) -> None:
    f = OggOpus(path)
    for name, values in changes.items():
        key = VORBIS_MAP[name]
        if key in f.tags:
            del f.tags[key]
        if values:
            f.tags[key] = values
    f.save()


# --- lyrics -------------------------------------------------------------------------------------

def set_lyrics(path: Path, text: str | None) -> None:
    """Set (or with None remove) embedded unsynchronized lyrics without touching other tags."""
    k = kind_of(path)
    if k == "mp3":
        tags = id3.ID3(path)
        lang = "XXX"
        tlan = tags.get("TLAN")
        if tlan and len(str(tlan.text[0])) == 3:
            lang = str(tlan.text[0])
        tags.delall("USLT")
        if text:
            tags.add(id3.USLT(encoding=UTF8, lang=lang, desc="", text=text))
        tags.save(path, v2_version=4, v1=0)
    elif k == "m4a":
        f = MP4(path)
        if text:
            f.tags["\xa9lyr"] = [text]
        else:
            f.tags.pop("\xa9lyr", None)
        f.save()
    else:
        f = OggOpus(path)
        if text:
            f.tags["LYRICS"] = [text]
        elif "LYRICS" in f.tags:
            del f.tags["LYRICS"]
        f.save()


def get_lyrics(path: Path) -> str | None:
    vals = read_fields(path).get("lyrics")
    return vals[0] if vals else None


# --- read ---------------------------------------------------------------------------------------

def read_fields(path: Path) -> dict[str, list[str]]:
    """Read tags back into Picard internal names (inverse of the write mapping).

    Adds the pseudo-fields ``~cover`` (["front"] when a front cover is embedded) and ``~id3version``.
    """
    k = kind_of(path)
    out: dict[str, list[str]] = {}
    if k == "mp3":
        try:
            tags = id3.ID3(path)
        except id3.ID3NoHeaderError:
            return {}
        out["~id3version"] = [".".join(str(x) for x in tags.version)]
        rev = {v: k for k, v in ID3_MAP.items()}
        for frame in tags.values():
            if isinstance(frame, id3.TXXX):
                name = rev.get(f"TXXX:{frame.desc}")
                if name:
                    out[name] = [str(t) for t in frame.text]
            elif isinstance(frame, id3.UFID):
                if frame.owner == UFID_OWNER:
                    out["musicbrainz_recordingid"] = [frame.data.decode("ascii", "replace")]
            elif isinstance(frame, id3.USLT):
                out["lyrics"] = [frame.text]
            elif isinstance(frame, id3.APIC):
                if frame.type == id3.PictureType.COVER_FRONT:
                    out["~cover"] = ["front"]
            elif frame.FrameID == "TRCK":
                n, _, t = str(frame.text[0]).partition("/")
                out["tracknumber"] = [n]
                if t:
                    out["totaltracks"] = [t]
            elif frame.FrameID == "TPOS":
                n, _, t = str(frame.text[0]).partition("/")
                out["discnumber"] = [n]
                if t:
                    out["totaldiscs"] = [t]
            elif frame.FrameID in rev and hasattr(frame, "text"):
                out[rev[frame.FrameID]] = [str(t) for t in frame.text]
    elif k == "m4a":
        f = MP4(path)
        tags = f.tags or {}
        rev = {v: k for k, v in MP4_MAP.items()}
        for key, values in tags.items():
            if key == "trkn" and values:
                n, t = values[0]
                out["tracknumber"] = [str(n)]
                if t:
                    out["totaltracks"] = [str(t)]
            elif key == "disk" and values:
                n, t = values[0]
                out["discnumber"] = [str(n)]
                if t:
                    out["totaldiscs"] = [str(t)]
            elif key == "cpil":
                if values:
                    out["compilation"] = ["1"]
            elif key == "covr":
                if values:
                    out["~cover"] = ["front"]
            elif key in rev:
                out[rev[key]] = [v.decode("utf-8") if isinstance(v, bytes) else str(v) for v in values]
    else:
        f = OggOpus(path)
        rev = {v: k for k, v in VORBIS_MAP.items()}
        for key, values in (f.tags or {}).items():
            ku = key.upper()
            if ku == "METADATA_BLOCK_PICTURE":
                for v in values:
                    try:
                        if Picture(base64.b64decode(v)).type == 3:
                            out["~cover"] = ["front"]
                    except Exception:
                        pass
            elif ku in rev:
                out.setdefault(rev[ku], []).extend(values)
    return out


def read_cover(path: Path) -> bytes | None:
    """The embedded front cover (or else the first embedded picture), None without one."""
    k = kind_of(path)
    pictures: list[tuple[bool, bytes]] = []  # (is front cover, data)
    if k == "mp3":
        try:
            tags = id3.ID3(path)
        except id3.ID3NoHeaderError:
            return None
        pictures = [(f.type == id3.PictureType.COVER_FRONT, f.data) for f in tags.getall("APIC")]
    elif k == "m4a":
        pictures = [(True, bytes(v)) for v in (MP4(path).tags or {}).get("covr", [])]
    else:
        for v in (OggOpus(path).tags or {}).get("METADATA_BLOCK_PICTURE", []):
            try:
                pic = Picture(base64.b64decode(v))
            except Exception:
                continue
            pictures.append((pic.type == 3, pic.data))
    pictures.sort(key=lambda p: not p[0])
    return pictures[0][1] if pictures else None


def read_mbids(path: Path) -> dict[str, str | None]:
    fields = read_fields(path)

    def first(n: str) -> str | None:
        v = fields.get(n)
        return v[0] if v else None

    return {
        "recording_id": first("musicbrainz_recordingid"),
        "track_id": first("musicbrainz_trackid"),
        "release_id": first("musicbrainz_albumid"),
        "release_group_id": first("musicbrainz_releasegroupid"),
        "youtube_video_id": first("youtube_video_id"),
    }


def read_display(path: Path) -> dict[str, list[str]]:
    """Raw on-disk tag keys and values (for the UI's track drawer)."""
    k = kind_of(path)
    out: dict[str, list[str]] = {}
    if k == "mp3":
        try:
            tags = id3.ID3(path)
        except id3.ID3NoHeaderError:
            return {}
        out["(ID3 version)"] = [".".join(str(x) for x in tags.version)]
        for key, frame in sorted(tags.items()):
            if isinstance(frame, id3.APIC):
                out[key] = [f"{frame.mime}, type {int(frame.type)}, {len(frame.data)} bytes"]
            elif isinstance(frame, id3.UFID):
                out[key] = [frame.data.decode("ascii", "replace")]
            elif isinstance(frame, id3.USLT):
                out[key] = [_trim(frame.text)]
            elif hasattr(frame, "text"):
                out[key] = [str(t) for t in frame.text]
    elif k == "m4a":
        f = MP4(path)
        for key, values in sorted((f.tags or {}).items()):
            if key == "covr":
                out[key] = [f"{len(v)} bytes" for v in values]
            elif key in ("trkn", "disk"):
                out[key] = [f"{a}/{b}" for a, b in values]
            elif isinstance(values, list):
                out[key] = [_trim(v.decode("utf-8") if isinstance(v, bytes) else str(v)) for v in values]
            else:
                out[key] = [str(values)]
    else:
        f = OggOpus(path)
        for key, values in sorted((f.tags or {}).items()):
            if key.upper() == "METADATA_BLOCK_PICTURE":
                out[key] = [f"picture block, {len(v) * 3 // 4} bytes" for v in values]
            else:
                out[key] = [_trim(v) for v in values]
    return out


def _trim(s: str, n: int = 300) -> str:
    return s if len(s) <= n else s[:n] + "…"


def audio_length(path: Path) -> float | None:
    k = kind_of(path)
    try:
        f = MP3(path) if k == "mp3" else MP4(path) if k == "m4a" else OggOpus(path)
        return float(f.info.length)
    except Exception:
        return None
