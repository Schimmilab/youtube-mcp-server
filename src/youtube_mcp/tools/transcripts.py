"""Transcript and caption tools.

Uses two strategies:
- Official YouTube Data API captions endpoint for own videos (requires OAuth)
- youtube-transcript-api library for public/competitor videos (scraping, no auth needed)
"""

import os

from googleapiclient.http import MediaFileUpload

from youtube_mcp.server import auth, mcp, quota


@mcp.tool()
def youtube_list_captions(video_id: str) -> dict:
    """List available caption tracks for a video you own.

    Requires OAuth. Only works for videos on the authenticated user's channel.

    Args:
        video_id: YouTube video ID
    """
    quota.consume("list")
    youtube = auth.build_youtube_service()

    response = youtube.captions().list(part="snippet", videoId=video_id).execute()

    tracks = []
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        tracks.append({
            "id": item["id"],
            "language": snippet.get("language"),
            "name": snippet.get("name"),
            "track_kind": snippet.get("trackKind"),
            "is_auto_synced": snippet.get("isAutoSynced"),
            "is_draft": snippet.get("isDraft"),
            "last_updated": snippet.get("lastUpdated"),
        })

    return {"video_id": video_id, "tracks": tracks}


CAPTION_EXTENSIONS = {".srt", ".vtt", ".sbv", ".scc", ".ttml"}


@mcp.tool()
def youtube_upload_caption(
    video_id: str,
    file_path: str,
    language: str = "de",
    name: str = "",
    is_draft: bool = False,
    replace_existing: bool = False,
) -> dict:
    """Upload a caption/subtitle file (SRT, VTT, ...) to a video you own.

    Costs 400 quota units (insert) or 450 (update when replacing).

    Args:
        video_id: YouTube video ID
        file_path: Absolute path to the caption file (.srt, .vtt, .sbv, .scc, .ttml)
        language: BCP-47 language code of the track, e.g. "de", "en"
        name: Track name shown to viewers (empty = default track for the language)
        is_draft: If True the track is uploaded but not shown to viewers
        replace_existing: If a track with the same language AND name exists, replace
            its content instead of adding a second track
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}
    ext = os.path.splitext(file_path)[1].lower()
    if ext not in CAPTION_EXTENSIONS:
        return {"error": f"Unsupported caption format {ext!r}, expected one of {sorted(CAPTION_EXTENSIONS)}"}

    youtube = auth.build_youtube_service()
    media = MediaFileUpload(file_path, mimetype="application/octet-stream", resumable=False)

    existing_id = None
    if replace_existing:
        quota.consume("list")
        listing = youtube.captions().list(part="snippet", videoId=video_id).execute()
        for item in listing.get("items", []):
            sn = item.get("snippet", {})
            if sn.get("language") == language and (sn.get("name") or "") == name and sn.get("trackKind") != "asr":
                existing_id = item["id"]
                break

    if existing_id:
        quota.consume("caption_update")
        response = youtube.captions().update(
            part="snippet",
            body={"id": existing_id, "snippet": {"isDraft": is_draft}},
            media_body=media,
        ).execute()
        action = "replaced"
    else:
        quota.consume("caption_insert")
        response = youtube.captions().insert(
            part="snippet",
            body={"snippet": {"videoId": video_id, "language": language, "name": name, "isDraft": is_draft}},
            media_body=media,
        ).execute()
        action = "inserted"

    sn = response.get("snippet", {})
    return {
        "caption_id": response.get("id"),
        "video_id": video_id,
        "language": sn.get("language", language),
        "name": sn.get("name", name),
        "is_draft": sn.get("isDraft", is_draft),
        "action": action,
    }


@mcp.tool()
def youtube_get_transcript(
    video_id: str,
    language: str = "en",
    use_official_api: bool = False,
) -> dict:
    """Get the transcript/captions for a video.

    By default uses youtube-transcript-api (works for any public video, no quota cost).
    Set use_official_api=True to use the official Data API (only for your own videos,
    costs quota units).

    Args:
        video_id: YouTube video ID
        language: Preferred language code (e.g., "en", "es", "ja")
        use_official_api: If True, use official API (own videos only)
    """
    if use_official_api:
        return _get_transcript_official(video_id, language)
    return _get_transcript_scraping(video_id, language)


def _get_transcript_scraping(video_id: str, language: str) -> dict:
    """Get transcript using youtube-transcript-api (public videos)."""
    try:
        from youtube_transcript_api import YouTubeTranscriptApi

        try:
            transcript_list = YouTubeTranscriptApi().list(video_id)

            # Try to find the requested language, fall back to auto-generated
            try:
                transcript = transcript_list.find_transcript([language])
            except Exception:
                # Fall back to any available transcript
                transcript = next(iter(transcript_list))
                if transcript.language_code != language:
                    try:
                        transcript = transcript.translate(language)
                    except Exception:
                        pass  # Use whatever we have

            fetched = transcript.fetch()
            segments = [
                {"text": s.text, "start": s.start, "duration": s.duration}
                for s in fetched
            ]
            full_text_parts = [s.text for s in fetched]

            return {
                "video_id": video_id,
                "language": transcript.language_code,
                "is_generated": transcript.is_generated,
                "source": "youtube-transcript-api",
                "full_text": " ".join(full_text_parts),
                "segments": segments,
            }
        except Exception as e:
            return {
                "video_id": video_id,
                "error": f"Could not fetch transcript: {e}",
                "source": "youtube-transcript-api",
            }
    except ImportError:
        return {
            "error": "youtube-transcript-api is not installed. "
            "Install it with: pip install youtube-transcript-api",
        }


def _get_transcript_official(video_id: str, language: str) -> dict:
    """Get transcript using official YouTube Data API (own videos only)."""
    quota.consume("list")
    youtube = auth.build_youtube_service()

    # First, list captions to find the right track
    response = youtube.captions().list(part="snippet", videoId=video_id).execute()

    target_caption = None
    for item in response.get("items", []):
        snippet = item.get("snippet", {})
        if snippet.get("language") == language:
            target_caption = item
            break

    if not target_caption:
        items = response.get("items", [])
        if items:
            target_caption = items[0]
        else:
            return {"video_id": video_id, "error": "No captions found"}

    # Download the caption track
    quota.consume("list")  # caption download costs vary
    caption_text = (
        youtube.captions().download(id=target_caption["id"], tfmt="srt").execute()
    )

    text = caption_text.decode("utf-8") if isinstance(caption_text, bytes) else caption_text

    return {
        "video_id": video_id,
        "language": target_caption["snippet"].get("language"),
        "track_kind": target_caption["snippet"].get("trackKind"),
        "source": "official_api",
        "full_text": text,
    }
