"""Video publishing tools — upload, update metadata, thumbnails, delete."""

import os

from googleapiclient.http import MediaFileUpload

from youtube_mcp.server import auth, mcp, quota

# Schreibbare Felder des status-Parts. videos.update ersetzt den KOMPLETTEN
# status-Block: was hier nicht mitgeschickt wird, setzt YouTube auf den Default
# zurueck. Vorher gingen dabei embeddable und ein geplanter publishAt verloren,
# sobald nur privacy_status geaendert wurde.
WRITABLE_STATUS_FIELDS = (
    "privacyStatus",
    "publishAt",
    "embeddable",
    "license",
    "publicStatsViewable",
    "selfDeclaredMadeForKids",
    "containsSyntheticMedia",
)


def _merge_status(current: dict, overrides: dict) -> dict | str:
    """Aktuellen status-Block uebernehmen und nur die uebergebenen Felder aendern.

    Gibt einen Fehlertext zurueck, wenn die Kombination ungueltig ist.
    """
    merged = {k: current[k] for k in WRITABLE_STATUS_FIELDS if k in current}
    merged.update({k: v for k, v in overrides.items() if v is not None})
    merged.setdefault("privacyStatus", "private")
    if merged["privacyStatus"] != "private":
        if overrides.get("publishAt"):
            return "publish_at requires privacy_status='private'"
        # Ein Termin gilt nur fuer private Videos; beim Veroeffentlichen faellt er weg.
        merged.pop("publishAt", None)
    return merged


@mcp.tool()
def youtube_upload_video(
    file_path: str,
    title: str,
    description: str = "",
    tags: list[str] | None = None,
    category_id: str = "22",
    privacy_status: str = "private",
    publish_at: str | None = None,
    contains_synthetic_media: bool | None = None,
) -> dict:
    """Upload a video to YouTube.

    Costs 1,600 quota units. Video is uploaded as private by default.

    Args:
        file_path: Absolute path to the video file
        title: Video title (max 100 characters)
        description: Video description (max 5,000 characters)
        tags: List of tags
        category_id: YouTube category ID (default "22" = People & Blogs)
        privacy_status: "private", "public", or "unlisted"
        publish_at: ISO 8601 datetime to schedule publishing (requires privacy_status="private")
        contains_synthetic_media: YouTube's "altered or synthetic content" disclosure
            (AI label, status.containsSyntheticMedia). True for AI music, AI avatars, etc.
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    quota.consume("video_insert")
    youtube = auth.build_youtube_service()

    body = {
        "snippet": {
            "title": title[:100],
            "description": description[:5000],
            "tags": tags or [],
            "categoryId": category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        },
    }

    if publish_at and privacy_status == "private":
        body["status"]["publishAt"] = publish_at
    if contains_synthetic_media is not None:
        body["status"]["containsSyntheticMedia"] = contains_synthetic_media

    media = MediaFileUpload(file_path, resumable=True)

    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = request.execute()

    return {
        "id": response["id"],
        "title": response["snippet"]["title"],
        "privacy": response["status"]["privacyStatus"],
        "publish_at": response["status"].get("publishAt"),
        "contains_synthetic_media": response["status"].get("containsSyntheticMedia"),
        "url": f"https://www.youtube.com/watch?v={response['id']}",
        "quota_cost": 1600,
    }


@mcp.tool()
def youtube_update_video(
    video_id: str,
    title: str | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    category_id: str | None = None,
    privacy_status: str | None = None,
    publish_at: str | None = None,
    made_for_kids: bool | None = None,
    contains_synthetic_media: bool | None = None,
    embeddable: bool | None = None,
) -> dict:
    """Update metadata for an existing video.

    Only provided fields are updated; others remain unchanged.

    Args:
        video_id: YouTube video ID
        title: New title (max 100 characters)
        description: New description (max 5,000 characters)
        tags: New tags (replaces existing tags)
        category_id: New category ID
        privacy_status: "private", "public", or "unlisted"
        publish_at: ISO 8601 datetime to schedule publishing (requires privacy_status="private" — either passed explicitly here or already set on the video).
        made_for_kids: COPPA self-declaration. Pass True/False to set selfDeclaredMadeForKids. Videos that were uploaded without this declaration cannot be published until it is set.
        contains_synthetic_media: AI label (status.containsSyntheticMedia), True/False.
        embeddable: Allow embedding on other sites.

    Status fields that are not passed keep their current value (embeddable,
    publishAt, license, ...). Changing privacy away from "private" drops publishAt.
    """
    quota.consume("list")
    youtube = auth.build_youtube_service()

    # Fetch current video data first
    current = youtube.videos().list(part="snippet,status", id=video_id).execute()
    items = current.get("items", [])
    if not items:
        return {"error": f"Video not found: {video_id}"}

    video = items[0]
    snippet = video["snippet"]
    status = video["status"]

    # Update only provided fields
    if title is not None:
        snippet["title"] = title[:100]
    if description is not None:
        snippet["description"] = description[:5000]
    if tags is not None:
        snippet["tags"] = tags
    if category_id is not None:
        snippet["categoryId"] = category_id

    body = {"id": video_id, "snippet": snippet}

    status_overrides = {
        "privacyStatus": privacy_status,
        "publishAt": publish_at,
        "selfDeclaredMadeForKids": made_for_kids,
        "containsSyntheticMedia": contains_synthetic_media,
        "embeddable": embeddable,
    }
    if any(v is not None for v in status_overrides.values()):
        new_status = _merge_status(status, status_overrides)
        if isinstance(new_status, str):
            return {"error": new_status}
        body["status"] = new_status
        parts = "snippet,status"
    else:
        parts = "snippet"

    quota.consume("update")
    response = youtube.videos().update(part=parts, body=body).execute()

    # part='snippet' responses omit the 'status' block entirely, so access it
    # defensively. Only surface these fields when the server actually
    # returned them.
    response_status = response.get("status") or {}
    return {
        "id": response["id"],
        "title": response["snippet"]["title"],
        "privacy": response_status.get("privacyStatus"),
        "publish_at": response_status.get("publishAt"),
        "embeddable": response_status.get("embeddable"),
        "contains_synthetic_media": response_status.get("containsSyntheticMedia"),
        "updated": True,
    }


@mcp.tool()
def youtube_set_thumbnail(video_id: str, file_path: str) -> dict:
    """Upload a custom thumbnail for a video.

    Args:
        video_id: YouTube video ID
        file_path: Absolute path to the thumbnail image (JPEG, PNG, GIF, BMP; max 2MB)
    """
    if not os.path.exists(file_path):
        return {"error": f"File not found: {file_path}"}

    quota.consume("thumbnail_set")
    youtube = auth.build_youtube_service()

    media = MediaFileUpload(file_path)
    response = youtube.thumbnails().set(videoId=video_id, media_body=media).execute()

    items = response.get("items", [])
    if items:
        return {
            "video_id": video_id,
            "thumbnail_url": items[0].get("default", {}).get("url"),
            "updated": True,
        }

    return {"video_id": video_id, "updated": True}


@mcp.tool()
def youtube_delete_video(video_id: str) -> dict:
    """Delete a video. This action is irreversible.

    Args:
        video_id: YouTube video ID to delete
    """
    quota.consume("delete")
    youtube = auth.build_youtube_service()

    youtube.videos().delete(id=video_id).execute()

    return {"video_id": video_id, "deleted": True}
