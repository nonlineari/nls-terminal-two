"""Apple Music chart snapshot features. One storefront payload in, scalars out."""

from __future__ import annotations

from datetime import date, datetime
from email.utils import parsedate_to_datetime

GENERIC_GENRES = {
    "music",
    "音楽",
    "음악",
    "音乐",
    "音樂",
    "เพลง",
    "âm nhạc",
    "nhạc",
    "musik",
}


def _parse_date(value: object) -> date | None:
    """Accept a YYYY-MM-DD prefix or an RFC 2822 feed timestamp.

    Apple's `updated` field looks like 'Thu, 22 Oct 2026 05:46:59 +0000'.
    Track release dates are calendar dates.
    """
    if not isinstance(value, str):
        return None
    text = value.strip()
    if len(text) >= 10:
        try:
            return datetime.strptime(text[:10], "%Y-%m-%d").date()
        except ValueError:
            pass
    try:
        return parsedate_to_datetime(text).date()
    except (TypeError, ValueError, IndexError, OverflowError):
        return None


def _is_generic(name: str) -> bool:
    return name.strip().casefold() in {genre.casefold() for genre in GENERIC_GENRES}


def apple_chart_features(body: dict | None) -> dict[str, float | str | None]:
    """Derive comparable chart stats from an Apple Marketing Tools feed.

    Track count is not used as a model feature: the pipeline asks every
    storefront for the same chart length, so the count mostly echoes the request.
    """
    empty: dict[str, float | str | None] = {
        "apple_chart_tracks": None,
        "apple_unique_artists": None,
        "apple_artist_diversity": None,
        "apple_genre_hhi": None,
        "apple_share_new_90d": None,
        "apple_chart_as_of": None,
    }
    if not body:
        return empty
    feed = body.get("feed") or {}
    results = feed.get("results") or []
    if not isinstance(results, list):
        return empty

    artists: list[str] = []
    genres: list[str] = []
    as_of = _parse_date(feed.get("updated"))
    dated = 0
    fresh = 0
    for track in results:
        if not isinstance(track, dict):
            continue
        artist = track.get("artistName")
        if isinstance(artist, str) and artist.strip():
            artists.append(artist.strip())
        primary = None
        for genre in track.get("genres") or []:
            if not isinstance(genre, dict):
                continue
            name = genre.get("name")
            if isinstance(name, str) and name.strip() and not _is_generic(name):
                primary = name.strip()
                break
        if primary is None:
            for genre in track.get("genres") or []:
                if isinstance(genre, dict) and isinstance(genre.get("name"), str):
                    primary = genre["name"].strip()
                    break
        if primary:
            genres.append(primary)
        released = _parse_date(track.get("releaseDate"))
        if as_of is not None and released is not None:
            dated += 1
            if (as_of - released).days <= 90:
                fresh += 1

    tracks = len([track for track in results if isinstance(track, dict)])
    unique_artists = len(set(artists))
    diversity = (unique_artists / tracks) if tracks else None
    hhi = None
    if genres:
        counts: dict[str, int] = {}
        for name in genres:
            counts[name] = counts.get(name, 0) + 1
        total = sum(counts.values())
        hhi = sum((count / total) ** 2 for count in counts.values())
    return {
        "apple_chart_tracks": tracks,
        "apple_unique_artists": unique_artists,
        "apple_artist_diversity": diversity,
        "apple_genre_hhi": hhi,
        "apple_share_new_90d": (fresh / dated) if dated else None,
        "apple_chart_as_of": as_of.isoformat() if as_of else None,
    }
