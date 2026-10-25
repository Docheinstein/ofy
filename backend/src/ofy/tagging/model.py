"""Format-agnostic tag model built from MusicBrainz release JSON (pure, no I/O).

Field semantics follow MusicBrainz Picard's internal tag names
(https://picard-docs.musicbrainz.org/en/appendices/tag_mapping.html).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal

from ofy.mb import logic

VARIOUS_ARTISTS_ID = "89ad4ac3-39f7-470e-963a-56509c546377"
MAX_GENRES = 5
# How several genres are written: as separate values (the ID3v2.4/MP4/Vorbis standard), as one value
# joined with a separator (for players that don't read multi-value tags), or only the top one.
GenreMode = Literal["multi", "joined", "first"]


@dataclass
class TagModel:
    title: str
    artist: str  # full artist credit string, e.g. "Daft Punk feat. Romanthony"
    artists: list[str]
    artistsort: str
    album: str
    albumartist: str
    albumartists: list[str]
    albumartistsort: str
    tracknumber: int
    totaltracks: int
    discnumber: int
    totaldiscs: int
    date: str | None = None  # release date
    originaldate: str | None = None  # release-group first release date
    originalyear: str | None = None
    genres: list[str] = field(default_factory=list)
    labels: list[str] = field(default_factory=list)
    catalognumbers: list[str] = field(default_factory=list)
    barcode: str | None = None
    isrcs: list[str] = field(default_factory=list)
    media: str | None = None
    releasetype: list[str] = field(default_factory=list)  # e.g. ["album", "live"]
    releasestatus: str | None = None  # e.g. "official"
    releasecountry: str | None = None
    compilation: bool = False
    script: str | None = None
    language: str | None = None
    length_ms: int | None = None
    asin: str | None = None
    discsubtitle: str | None = None
    # MusicBrainz identifiers
    musicbrainz_recordingid: str = ""
    musicbrainz_trackid: str = ""  # release track id
    musicbrainz_albumid: str = ""
    musicbrainz_releasegroupid: str = ""
    musicbrainz_artistids: list[str] = field(default_factory=list)
    musicbrainz_albumartistids: list[str] = field(default_factory=list)
    musicbrainz_labelids: list[str] = field(default_factory=list)
    # Provenance / extras
    youtube_video_id: str | None = None
    lyrics: str | None = None
    lyrics_missing: str | None = None  # a lookup found none: not_found | instrumental (kept so it isn't redone)

    @property
    def isrc(self) -> str | None:
        return self.isrcs[0] if self.isrcs else None

    @property
    def year(self) -> str | None:
        return logic.year_of(self.date)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def path_values(self, ext: str) -> dict[str, Any]:
        """Values for the library path template."""
        return {
            "albumartist": self.albumartist,
            "artist": self.artist,
            "album": self.album,
            "title": self.title,
            # Folder year: original release year (stable across reissues), falling back to release year
            "year": self.originalyear or self.year or "0000",
            "date": self.date or "",
            "originalyear": self.originalyear or "",
            "disc": self.discnumber,
            "disctotal": self.totaldiscs,
            "track": self.tracknumber,
            "tracktotal": self.totaltracks,
            "ext": ext,
            "media": self.media or "",
            "releasetype": (self.releasetype or [""])[0],
            "catalognumber": (self.catalognumbers or [""])[0],
            "label": (self.labels or [""])[0],
            "albumartistsort": self.albumartistsort,
            "artistsort": self.artistsort,
        }


def top_genres(*genre_lists: list[dict[str, Any]] | None, limit: int = MAX_GENRES) -> list[str]:
    """Merge MB genre lists (recording, release, release-group, ...) weighting by vote count."""
    counts: dict[str, int] = {}
    for gl in genre_lists:
        for g in gl or []:
            name = g.get("name")
            if name:
                counts[name] = counts.get(name, 0) + int(g.get("count") or 1)
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))
    if not ranked:
        return []
    top = ranked[0][1]
    # Drop noise: genres with very few votes relative to the top one.
    return [name for name, c in ranked if c * 10 >= top][:limit]


def _find_track(release: dict[str, Any], track_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
    for medium in release.get("media") or []:
        for t in medium.get("tracks") or []:
            if t.get("id") == track_id:
                return medium, t
    raise KeyError(f"track {track_id} not on release {release.get('id')}")


def format_genres(genres: list[str], mode: GenreMode = "multi", separator: str = "; ") -> list[str]:
    if not genres or mode == "multi":
        return genres
    if mode == "first":
        return genres[:1]
    return [separator.join(genres)]


def build_tag_model(
    release: dict[str, Any],
    track_id: str,
    *,
    youtube_video_id: str | None = None,
    genre_mode: GenreMode = "multi",
    genre_separator: str = "; ",
) -> TagModel:
    medium, track = _find_track(release, track_id)
    rec = track.get("recording") or {}
    rg = release.get("release-group") or {}
    track_credit = track.get("artist-credit") or rec.get("artist-credit") or []
    album_credit = release.get("artist-credit") or []
    media = release.get("media") or []
    labels = release.get("label-info") or []
    text = release.get("text-representation") or {}
    album_artist_ids = logic.artist_credit_ids(album_credit)
    types = [rg.get("primary-type")] + list(rg.get("secondary-types") or [])
    return TagModel(
        title=track.get("title") or rec.get("title", ""),
        artist=logic.artist_credit_string(track_credit),
        artists=logic.artist_credit_names(track_credit),
        artistsort=logic.artist_credit_sort(track_credit),
        album=release.get("title", ""),
        albumartist=logic.artist_credit_string(album_credit),
        albumartists=logic.artist_credit_names(album_credit),
        albumartistsort=logic.artist_credit_sort(album_credit),
        tracknumber=int(track.get("position") or 0),
        totaltracks=int(medium.get("track-count") or len(medium.get("tracks") or [])),
        discnumber=int(medium.get("position") or 1),
        totaldiscs=len(media) or 1,
        date=release.get("date") or None,
        originaldate=rg.get("first-release-date") or None,
        originalyear=logic.year_of(rg.get("first-release-date")),
        genres=format_genres(top_genres(rec.get("genres"), release.get("genres"), rg.get("genres")),
                             genre_mode, genre_separator),
        labels=list(dict.fromkeys(li["label"]["name"] for li in labels if li.get("label"))),
        catalognumbers=list(dict.fromkeys(li["catalog-number"] for li in labels if li.get("catalog-number"))),
        barcode=release.get("barcode") or None,
        isrcs=list(rec.get("isrcs") or []),
        media=medium.get("format") or None,
        releasetype=[t.lower() for t in types if t],
        releasestatus=(release.get("status") or "").lower() or None,
        releasecountry=release.get("country") or None,
        # Picard: compilation=1 when the album artist is "Various Artists"
        compilation=VARIOUS_ARTISTS_ID in album_artist_ids,
        script=text.get("script") or None,
        language=text.get("language") or None,
        length_ms=track.get("length") or rec.get("length"),
        asin=release.get("asin") or None,
        discsubtitle=medium.get("title") or None,
        musicbrainz_recordingid=rec.get("id", ""),
        musicbrainz_trackid=track["id"],
        musicbrainz_albumid=release["id"],
        musicbrainz_releasegroupid=rg.get("id", ""),
        musicbrainz_artistids=logic.artist_credit_ids(track_credit),
        musicbrainz_albumartistids=album_artist_ids,
        musicbrainz_labelids=list(dict.fromkeys(li["label"]["id"] for li in labels if (li.get("label") or {}).get("id"))),
        youtube_video_id=youtube_video_id,
    )
