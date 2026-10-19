"""Tests for publishing tools with mocked YouTube API."""

from unittest.mock import MagicMock, patch

import pytest


class TestUploadVideo:
    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_success(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().insert().execute.return_value = {
            "id": "new123",
            "snippet": {"title": "My Video"},
            "status": {"privacyStatus": "private"},
        }

        result = youtube_upload_video(
            file_path="/tmp/video.mp4",
            title="My Video",
            description="A test",
        )
        assert result["id"] == "new123"
        assert result["url"] == "https://www.youtube.com/watch?v=new123"
        assert result["quota_cost"] == 1600
        mock_quota.consume.assert_called_once_with("video_insert")

    @patch("youtube_mcp.tools.publishing.quota")
    def test_upload_file_not_found(self, mock_quota):
        from youtube_mcp.tools.publishing import youtube_upload_video

        result = youtube_upload_video(
            file_path="/nonexistent/video.mp4",
            title="Test",
        )
        assert "error" in result
        mock_quota.consume.assert_not_called()


class TestUpdateVideo:
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_title(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt

        # Mock the initial fetch
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {
                    "title": "Old Title",
                    "description": "Desc",
                    "tags": ["tag1"],
                    "categoryId": "22",
                },
                "status": {"privacyStatus": "public"},
            }]
        }

        # Mock the update
        mock_yt.videos().update().execute.return_value = {
            "id": "vid1",
            "snippet": {"title": "New Title"},
            "status": {"privacyStatus": "public"},
        }

        result = youtube_update_video(video_id="vid1", title="New Title")
        assert result["title"] == "New Title"
        assert result["updated"] is True

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_not_found(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {"items": []}

        result = youtube_update_video(video_id="nope", title="X")
        assert "error" in result

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")

    def test_update_schedule_on_private_video(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {"title": "T", "description": "D", "tags": [], "categoryId": "22"},
                "status": {"privacyStatus": "private"},
            }]
        }
        mock_yt.videos().update().execute.return_value = {
            "id": "vid1",
            "snippet": {"title": "T"},
            "status": {"privacyStatus": "private", "publishAt": "2026-05-01T16:00:00Z"},
        }

        result = youtube_update_video(video_id="vid1", publish_at="2026-05-01T16:00:00Z")
        assert result["publish_at"] == "2026-05-01T16:00:00Z"
        assert result["privacy"] == "private"

        # Verify the body sent to update() included status.publishAt
        call_kwargs = mock_yt.videos().update.call_args.kwargs
        assert call_kwargs["part"] == "snippet,status"
        assert call_kwargs["body"]["status"]["publishAt"] == "2026-05-01T16:00:00Z"
        assert call_kwargs["body"]["status"]["privacyStatus"] == "private"

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_made_for_kids(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {"title": "T", "description": "D", "tags": [], "categoryId": "22"},
                "status": {"privacyStatus": "private"},
            }]
        }
        mock_yt.videos().update().execute.return_value = {
            "id": "vid1",
            "snippet": {"title": "T"},
            "status": {"privacyStatus": "private"},
        }

        result = youtube_update_video(video_id="vid1", made_for_kids=False)
        assert result["updated"] is True

        call_kwargs = mock_yt.videos().update.call_args.kwargs
        assert call_kwargs["part"] == "snippet,status"
        assert call_kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False
        assert call_kwargs["body"]["status"]["privacyStatus"] == "private"

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_schedule_rejects_public(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {"title": "T", "description": "D", "tags": [], "categoryId": "22"},
                "status": {"privacyStatus": "public"},
            }]
        }

        result = youtube_update_video(video_id="vid1", publish_at="2026-05-01T16:00:00Z")
        assert "error" in result
        mock_yt.videos().update.assert_not_called()

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_without_privacy_status_does_not_raise_keyerror(
        self, mock_quota, mock_auth
    ):
        """Regression: when privacy_status/publish_at/made_for_kids are all
        omitted, only part='snippet' is sent and the YouTube API response
        omits the 'status' field. The function must not raise KeyError.
        """
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt

        mock_yt.videos().list().execute.return_value = {
            "items": [{
                "id": "vid1",
                "snippet": {
                    "title": "Old Title",
                    "description": "Desc",
                    "tags": ["tag1"],
                    "categoryId": "22",
                },
                "status": {"privacyStatus": "public"},
            }]
        }

        mock_yt.videos().update().execute.return_value = {
            "kind": "youtube#video",
            "etag": "abc",
            "id": "vid1",
            "snippet": {"title": "New Title"},
        }

        result = youtube_update_video(video_id="vid1", title="New Title")
        assert result["id"] == "vid1"
        assert result["title"] == "New Title"
        assert result["updated"] is True
        assert result.get("privacy") is None
        assert result.get("publish_at") is None


class TestSetThumbnail:
    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_set_thumbnail(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_set_thumbnail

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.thumbnails().set().execute.return_value = {
            "items": [{"default": {"url": "https://i.ytimg.com/thumb.jpg"}}]
        }

        result = youtube_set_thumbnail("vid1", "/tmp/thumb.jpg")
        assert result["updated"] is True
        mock_quota.consume.assert_called_once_with("thumbnail_set")


class TestDeleteVideo:
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_delete(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_delete_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt

        result = youtube_delete_video("vid1")
        assert result["deleted"] is True
        mock_quota.consume.assert_called_once_with("delete")


class TestVideoLanguage:
    """Sprache (18.10.2026): API-Uploads ohne defaultAudioLanguage landen als „Englisch (USA)"."""

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_sets_german_by_default(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().insert().execute.return_value = {
            "id": "v", "snippet": {"title": "t", "defaultLanguage": "de", "defaultAudioLanguage": "de"},
            "status": {"privacyStatus": "private"},
        }
        mock_yt.videos().insert.reset_mock()
        result = youtube_upload_video(file_path="/tmp/v.mp4", title="t")
        body = mock_yt.videos().insert.call_args.kwargs["body"]
        assert body["snippet"]["defaultLanguage"] == "de"
        assert body["snippet"]["defaultAudioLanguage"] == "de"
        assert result["default_audio_language"] == "de"

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_language_overridable(self, mock_exists, mock_quota, mock_auth, mock_media):
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().insert().execute.return_value = {
            "id": "v", "snippet": {"title": "t"}, "status": {"privacyStatus": "private"}}
        mock_yt.videos().insert.reset_mock()
        youtube_upload_video(file_path="/tmp/v.mp4", title="t", default_audio_language="en")
        assert mock_yt.videos().insert.call_args.kwargs["body"]["snippet"]["defaultAudioLanguage"] == "en"

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_made_for_kids(self, mock_exists, mock_quota, mock_auth, mock_media):
        # 19.10.2026: Der Wert war hart auf False — auf Arcanara Kinder waere jedes Video
        # als "nicht fuer Kinder" deklariert worden. Default bleibt False (Muss-gruen),
        # True muss im Body ankommen (Muss-rot fuer den alten Code).
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().insert().execute.return_value = {
            "id": "v", "snippet": {"title": "t"},
            "status": {"privacyStatus": "private", "selfDeclaredMadeForKids": True}}
        mock_yt.videos().insert.reset_mock()
        youtube_upload_video(file_path="/tmp/v.mp4", title="t")
        assert mock_yt.videos().insert.call_args.kwargs["body"]["status"]["selfDeclaredMadeForKids"] is False
        mock_yt.videos().insert.reset_mock()
        result = youtube_upload_video(file_path="/tmp/v.mp4", title="t", made_for_kids=True)
        assert mock_yt.videos().insert.call_args.kwargs["body"]["status"]["selfDeclaredMadeForKids"] is True
        assert result["made_for_kids"] is True

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_language_without_touching_status(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {"items": [{
            "id": "v", "snippet": {"title": "t", "categoryId": "22", "defaultAudioLanguage": "en-US"},
            "status": {"privacyStatus": "private", "publishAt": "2026-10-20T17:30:00Z"}}]}
        mock_yt.videos().update().execute.return_value = {
            "id": "v", "snippet": {"title": "t", "defaultLanguage": "de", "defaultAudioLanguage": "de"}}
        mock_yt.videos().update.reset_mock()
        result = youtube_update_video(video_id="v", default_language="de", default_audio_language="de")
        kw = mock_yt.videos().update.call_args.kwargs
        assert kw["part"] == "snippet"            # Status bleibt unberührt -> publishAt kann nicht verloren gehen
        assert "status" not in kw["body"]
        assert kw["body"]["snippet"]["defaultAudioLanguage"] == "de"
        assert result["default_language"] == "de"

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_update_without_language_keeps_existing(self, mock_quota, mock_auth):
        """Muss-rot-Gegenprobe: ohne Parameter darf die Sprache nicht still auf de kippen."""
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {"items": [{
            "id": "v", "snippet": {"title": "t", "categoryId": "22", "defaultAudioLanguage": "en"},
            "status": {"privacyStatus": "public"}}]}
        mock_yt.videos().update().execute.return_value = {"id": "v", "snippet": {"title": "t2"}}
        mock_yt.videos().update.reset_mock()
        youtube_update_video(video_id="v", title="t2")
        assert mock_yt.videos().update.call_args.kwargs["body"]["snippet"]["defaultAudioLanguage"] == "en"
