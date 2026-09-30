"""Response formatting utilities for LLM consumption."""

from datetime import timedelta


def format_duration(iso_duration: str) -> str:
    """Convert ISO 8601 duration (PT1H2M3S) to human-readable format."""
    if not iso_duration:
        return "unknown"
    s = iso_duration.replace("PT", "")
    hours = minutes = seconds = 0
    if "H" in s:
        hours, s = s.split("H")
        hours = int(hours)
    if "M" in s:
        minutes, s = s.split("M")
        minutes = int(minutes)
    if "S" in s:
        seconds = int(s.replace("S", ""))
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds or not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def format_count(n: int | str) -> str:
    """Format large numbers with K/M/B suffixes."""
    n = int(n)
    if n >= 1_000_000_000:
        return f"{n / 1_000_000_000:.1f}B"
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}M"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return str(n)


LIST_DESCRIPTION_LIMIT = 500


def format_video_summary(video: dict, max_description: int | None = LIST_DESCRIPTION_LIMIT) -> dict:
    """Extract and format key fields from a YouTube Data API video resource.

    ``max_description`` kuerzt die Beschreibung fuer Listen/Suchen (Kontext sparen).
    ``None`` liefert sie vollstaendig — so ruft ``youtube_get_video`` auf.
    Wird gekuerzt, steht das in ``description_truncated`` und ``description_length``:
    Die Kuerzung war vorher stumm, und ein Link am Ende der Beschreibung sah aus,
    als fehle er (Arcanara F13, 30.09.2026).
    """
    snippet = video.get("snippet", {})
    stats = video.get("statistics", {})
    content = video.get("contentDetails", {})

    return {
        "id": video.get("id"),
        "title": snippet.get("title"),
        "channel": snippet.get("channelTitle"),
        "published_at": snippet.get("publishedAt"),
        "duration": format_duration(content.get("duration", "")),
        "views": int(stats.get("viewCount", 0)),
        "likes": int(stats.get("likeCount", 0)),
        "comments": int(stats.get("commentCount", 0)),
        **_description_fields(snippet.get("description", ""), max_description),
        "tags": snippet.get("tags", []),
        "thumbnail": snippet.get("thumbnails", {}).get("high", {}).get("url"),
        "is_short": _is_likely_short(content.get("duration", "")),
    }


def _description_fields(description: str, limit: int | None) -> dict:
    """Beschreibung plus ehrliche Angabe, ob gekuerzt wurde."""
    if limit is None or len(description) <= limit:
        return {"description": description, "description_truncated": False,
                "description_length": len(description)}
    return {"description": description[:limit], "description_truncated": True,
            "description_length": len(description)}


def _is_likely_short(iso_duration: str) -> bool:
    """Heuristic: videos <= 60 seconds are likely Shorts."""
    if not iso_duration:
        return False
    s = iso_duration.replace("PT", "")
    total_seconds = 0
    if "H" in s:
        return False
    if "M" in s:
        minutes, s = s.split("M")
        total_seconds += int(minutes) * 60
    if "S" in s:
        total_seconds += int(s.replace("S", ""))
    return total_seconds <= 60
