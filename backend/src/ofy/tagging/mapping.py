"""Picard-compatible tag mapping (pure).

``model_to_fields`` flattens a TagModel into Picard internal tag names → list of string values.
The per-format tables below map those names to ID3v2.4 frames, MP4 atoms and Vorbis comments,
following https://picard-docs.musicbrainz.org/en/appendices/tag_mapping.html and Picard's
source (picard/formats/id3.py, mp4.py, vorbis.py).
"""

from __future__ import annotations

from ofy.tagging.model import TagModel

# Internal name -> ID3 frame id, or "TXXX:<description>"
ID3_MAP: dict[str, str] = {
    "title": "TIT2",
    "artist": "TPE1",
    "artists": "TXXX:ARTISTS",
    "album": "TALB",
    "albumartist": "TPE2",
    "albumartists": "TXXX:ALBUMARTISTS",
    "artistsort": "TSOP",
    "albumartistsort": "TSO2",
    "date": "TDRC",
    "originaldate": "TDOR",
    "originalyear": "TXXX:originalyear",
    "genre": "TCON",
    "label": "TPUB",
    "catalognumber": "TXXX:CATALOGNUMBER",
    "barcode": "TXXX:BARCODE",
    "isrc": "TSRC",
    "media": "TMED",
    "releasetype": "TXXX:MusicBrainz Album Type",
    "releasestatus": "TXXX:MusicBrainz Album Status",
    "releasecountry": "TXXX:MusicBrainz Album Release Country",
    "compilation": "TCMP",
    "script": "TXXX:SCRIPT",
    "language": "TLAN",
    "length": "TLEN",
    "asin": "TXXX:ASIN",
    "discsubtitle": "TSST",
    "musicbrainz_trackid": "TXXX:MusicBrainz Release Track Id",
    "musicbrainz_albumid": "TXXX:MusicBrainz Album Id",
    "musicbrainz_releasegroupid": "TXXX:MusicBrainz Release Group Id",
    "musicbrainz_artistid": "TXXX:MusicBrainz Artist Id",
    "musicbrainz_albumartistid": "TXXX:MusicBrainz Album Artist Id",
    "youtube_video_id": "TXXX:YOUTUBE_VIDEO_ID",
    "haslyrics": "TXXX:HAS_LYRICS",
    "instrumental": "TXXX:INSTRUMENTAL",
    # special-cased in the writer:
    #   tracknumber/totaltracks -> TRCK "n/t", discnumber/totaldiscs -> TPOS "n/t"
    #   musicbrainz_recordingid -> UFID owner "http://musicbrainz.org"
    #   lyrics -> USLT, cover -> APIC (type 3, front cover)
}
UFID_OWNER = "http://musicbrainz.org"

FF = "----:com.apple.iTunes:"
MP4_MAP: dict[str, str] = {
    "title": "\xa9nam",
    "artist": "\xa9ART",
    "artists": FF + "ARTISTS",
    "album": "\xa9alb",
    "albumartist": "aART",
    "albumartists": FF + "ALBUMARTISTS",
    "artistsort": "soar",
    "albumartistsort": "soaa",
    "date": "\xa9day",
    "originaldate": FF + "originaldate",
    "originalyear": FF + "originalyear",
    "genre": "\xa9gen",
    "label": FF + "LABEL",
    "catalognumber": FF + "CATALOGNUMBER",
    "barcode": FF + "BARCODE",
    "isrc": FF + "ISRC",
    "media": FF + "MEDIA",
    "releasetype": FF + "MusicBrainz Album Type",
    "releasestatus": FF + "MusicBrainz Album Status",
    "releasecountry": FF + "MusicBrainz Album Release Country",
    "script": FF + "SCRIPT",
    "language": FF + "LANGUAGE",
    "length": FF + "LENGTH",
    "asin": FF + "ASIN",
    "discsubtitle": FF + "DISCSUBTITLE",
    "musicbrainz_recordingid": FF + "MusicBrainz Track Id",
    "musicbrainz_trackid": FF + "MusicBrainz Release Track Id",
    "musicbrainz_albumid": FF + "MusicBrainz Album Id",
    "musicbrainz_releasegroupid": FF + "MusicBrainz Release Group Id",
    "musicbrainz_artistid": FF + "MusicBrainz Artist Id",
    "musicbrainz_albumartistid": FF + "MusicBrainz Album Artist Id",
    "youtube_video_id": FF + "YOUTUBE_VIDEO_ID",
    "haslyrics": FF + "HAS_LYRICS",
    "instrumental": FF + "INSTRUMENTAL",
    "lyrics": "\xa9lyr",
    # special-cased: tracknumber/totaltracks -> trkn, discnumber/totaldiscs -> disk,
    #   compilation -> cpil (bool), cover -> covr
}

VORBIS_MAP: dict[str, str] = {
    "title": "TITLE",
    "artist": "ARTIST",
    "artists": "ARTISTS",
    "album": "ALBUM",
    "albumartist": "ALBUMARTIST",
    "albumartists": "ALBUMARTISTS",
    "artistsort": "ARTISTSORT",
    "albumartistsort": "ALBUMARTISTSORT",
    "tracknumber": "TRACKNUMBER",
    "totaltracks": "TRACKTOTAL",
    "discnumber": "DISCNUMBER",
    "totaldiscs": "DISCTOTAL",
    "date": "DATE",
    "originaldate": "ORIGINALDATE",
    "originalyear": "ORIGINALYEAR",
    "genre": "GENRE",
    "label": "LABEL",
    "catalognumber": "CATALOGNUMBER",
    "barcode": "BARCODE",
    "isrc": "ISRC",
    "media": "MEDIA",
    "releasetype": "RELEASETYPE",
    "releasestatus": "RELEASESTATUS",
    "releasecountry": "RELEASECOUNTRY",
    "compilation": "COMPILATION",
    "script": "SCRIPT",
    "language": "LANGUAGE",
    "length": "LENGTH",
    "asin": "ASIN",
    "discsubtitle": "DISCSUBTITLE",
    # Picard's Vorbis naming: MUSICBRAINZ_TRACKID is the *recording* id
    "musicbrainz_recordingid": "MUSICBRAINZ_TRACKID",
    "musicbrainz_trackid": "MUSICBRAINZ_RELEASETRACKID",
    "musicbrainz_albumid": "MUSICBRAINZ_ALBUMID",
    "musicbrainz_releasegroupid": "MUSICBRAINZ_RELEASEGROUPID",
    "musicbrainz_artistid": "MUSICBRAINZ_ARTISTID",
    "musicbrainz_albumartistid": "MUSICBRAINZ_ALBUMARTISTID",
    "youtube_video_id": "YOUTUBE_VIDEO_ID",
    "haslyrics": "HAS_LYRICS",
    "instrumental": "INSTRUMENTAL",
    "lyrics": "LYRICS",
    # cover -> METADATA_BLOCK_PICTURE (base64 FLAC picture block, type 3)
}


def _s(v) -> list[str]:
    if v is None or v == "" or v == []:
        return []
    if isinstance(v, list):
        return [str(x) for x in v if x not in (None, "")]
    return [str(v)]


def model_to_fields(m: TagModel) -> dict[str, list[str]]:
    """Flatten the model to Picard internal names. Empty values are omitted."""
    fields: dict[str, list[str]] = {
        "title": _s(m.title),
        "artist": _s(m.artist),
        "artists": _s(m.artists),
        "album": _s(m.album),
        "albumartist": _s(m.albumartist),
        "albumartists": _s(m.albumartists),
        "artistsort": _s(m.artistsort),
        "albumartistsort": _s(m.albumartistsort),
        "tracknumber": _s(m.tracknumber),
        "totaltracks": _s(m.totaltracks),
        "discnumber": _s(m.discnumber),
        "totaldiscs": _s(m.totaldiscs),
        "date": _s(m.date),
        "originaldate": _s(m.originaldate),
        "originalyear": _s(m.originalyear),
        "genre": _s(m.genres),
        "label": _s(m.labels),
        "catalognumber": _s(m.catalognumbers),
        "barcode": _s(m.barcode),
        "isrc": _s(m.isrcs[:1]),
        "media": _s(m.media),
        "releasetype": _s(m.releasetype),
        "releasestatus": _s(m.releasestatus),
        "releasecountry": _s(m.releasecountry),
        "compilation": ["1"] if m.compilation else [],
        "script": _s(m.script),
        "language": _s(m.language),
        "length": _s(m.length_ms),
        "asin": _s(m.asin),
        "discsubtitle": _s(m.discsubtitle),
        "musicbrainz_recordingid": _s(m.musicbrainz_recordingid),
        "musicbrainz_trackid": _s(m.musicbrainz_trackid),
        "musicbrainz_albumid": _s(m.musicbrainz_albumid),
        "musicbrainz_releasegroupid": _s(m.musicbrainz_releasegroupid),
        "musicbrainz_artistid": _s(m.musicbrainz_artistids),
        "musicbrainz_albumartistid": _s(m.musicbrainz_albumartistids),
        "youtube_video_id": _s(m.youtube_video_id),
        "lyrics": _s(m.lyrics),
        **lyrics_missing_fields(m.lyrics_missing),
    }
    return {k: v for k, v in fields.items() if v}


# A lyrics lookup that found none, noted in the tags: HAS_LYRICS = 0, and INSTRUMENTAL = 1 when it's
# an instrumental. Found lyrics remove both.
LYRICS_MISSING_NAMES = ("haslyrics", "instrumental")


def lyrics_missing_fields(status: str | None) -> dict[str, list[str]]:
    """The tags noting ``status`` (not_found | instrumental | None); an empty list removes a tag."""
    return {"haslyrics": ["0"] if status else [], "instrumental": ["1"] if status == "instrumental" else []}


def lyrics_missing_from(fields: dict[str, list[str]]) -> str | None:
    """not_found | instrumental as noted in the tags, else None."""
    if (fields.get("instrumental") or [""])[0] == "1":
        return "instrumental"
    if (fields.get("haslyrics") or [""])[0] == "0":
        return "not_found"
    return None
