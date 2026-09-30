"""Tests: KI-Label, Status-Update ohne Nebenwirkung, Untertitel-Upload, Kanal-Branding.

Die Negativkontrollen sind der Kern: vorher hat ein Status-Update embeddable und
einen geplanten publishAt still verworfen, und channels.update ersetzt den
kompletten brandingSettings-Block.
"""

from unittest.mock import MagicMock, patch

SCHEDULED = {
    "privacyStatus": "private",
    "publishAt": "2026-10-04T17:30:00Z",
    "embeddable": True,
    "license": "youtube",
    "publicStatsViewable": True,
    "selfDeclaredMadeForKids": False,
    # read-only Felder, die YouTube mitliefert und die NICHT zurueckgeschickt werden duerfen
    "uploadStatus": "processed",
    "madeForKids": False,
}


class TestMergeStatus:
    def test_only_ai_label_keeps_schedule_and_embeddable(self):
        from youtube_mcp.tools.publishing import _merge_status

        m = _merge_status(SCHEDULED, {"containsSyntheticMedia": True})
        assert m["containsSyntheticMedia"] is True
        assert m["publishAt"] == "2026-10-04T17:30:00Z"
        assert m["embeddable"] is True
        assert "uploadStatus" not in m and "madeForKids" not in m

    def test_privacy_private_again_keeps_embeddable(self):
        """Falle 2 aus der Memory: privacy_status='private' hat embeddable geloescht."""
        from youtube_mcp.tools.publishing import _merge_status

        m = _merge_status(SCHEDULED, {"privacyStatus": "private"})
        assert m["embeddable"] is True
        assert m["publishAt"] == "2026-10-04T17:30:00Z"

    def test_going_public_drops_schedule(self):
        from youtube_mcp.tools.publishing import _merge_status

        m = _merge_status(SCHEDULED, {"privacyStatus": "public"})
        assert m["privacyStatus"] == "public"
        assert "publishAt" not in m
        assert m["embeddable"] is True

    def test_publish_at_with_public_is_error(self):
        from youtube_mcp.tools.publishing import _merge_status

        assert isinstance(_merge_status({}, {"privacyStatus": "public", "publishAt": "2026-10-04T17:30:00Z"}), str)

    def test_none_overrides_change_nothing(self):
        from youtube_mcp.tools.publishing import _merge_status

        m = _merge_status(SCHEDULED, {"embeddable": None, "containsSyntheticMedia": None})
        assert m["embeddable"] is True


class TestUpdateVideoStatus:
    def _setup(self, mock_auth, status):
        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().list().execute.return_value = {
            "items": [{"id": "v1", "snippet": {"title": "T", "categoryId": "22"}, "status": dict(status)}]
        }
        mock_yt.videos().update().execute.return_value = {
            "id": "v1", "snippet": {"title": "T"},
            "status": {**status, "containsSyntheticMedia": True},
        }
        return mock_yt

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_ai_label_update_sends_full_status(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = self._setup(mock_auth, SCHEDULED)
        result = youtube_update_video(video_id="v1", contains_synthetic_media=True)
        sent = mock_yt.videos().update.call_args.kwargs["body"]["status"]
        assert sent["containsSyntheticMedia"] is True
        assert sent["embeddable"] is True
        assert sent["publishAt"] == "2026-10-04T17:30:00Z"
        assert result["contains_synthetic_media"] is True

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_privacy_update_keeps_embeddable(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = self._setup(mock_auth, SCHEDULED)
        youtube_update_video(video_id="v1", privacy_status="private")
        sent = mock_yt.videos().update.call_args.kwargs["body"]["status"]
        assert sent["embeddable"] is True
        assert sent["publishAt"] == "2026-10-04T17:30:00Z"

    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    def test_snippet_only_update_sends_no_status(self, mock_quota, mock_auth):
        from youtube_mcp.tools.publishing import youtube_update_video

        mock_yt = self._setup(mock_auth, SCHEDULED)
        youtube_update_video(video_id="v1", title="Neu")
        assert mock_yt.videos().update.call_args.kwargs["part"] == "snippet"


class TestUploadAiLabel:
    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_sets_label(self, _e, mock_quota, mock_auth, _m):
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().insert().execute.return_value = {
            "id": "n", "snippet": {"title": "X"},
            "status": {"privacyStatus": "private", "containsSyntheticMedia": True},
        }
        r = youtube_upload_video(file_path="/tmp/v.mp4", title="X", contains_synthetic_media=True)
        body = mock_yt.videos().insert.call_args.kwargs["body"]
        assert body["status"]["containsSyntheticMedia"] is True
        assert r["contains_synthetic_media"] is True

    @patch("youtube_mcp.tools.publishing.MediaFileUpload")
    @patch("youtube_mcp.tools.publishing.auth")
    @patch("youtube_mcp.tools.publishing.quota")
    @patch("os.path.exists", return_value=True)
    def test_upload_without_label_sends_no_field(self, _e, mock_quota, mock_auth, _m):
        from youtube_mcp.tools.publishing import youtube_upload_video

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.videos().insert().execute.return_value = {"id": "n", "snippet": {"title": "X"}, "status": {"privacyStatus": "private"}}
        youtube_upload_video(file_path="/tmp/v.mp4", title="X")
        assert "containsSyntheticMedia" not in mock_yt.videos().insert.call_args.kwargs["body"]["status"]


class TestUploadCaption:
    @patch("youtube_mcp.tools.transcripts.quota")
    def test_missing_file(self, mock_quota):
        from youtube_mcp.tools.transcripts import youtube_upload_caption

        assert "error" in youtube_upload_caption("v", "/nope/x.srt")
        mock_quota.consume.assert_not_called()

    @patch("os.path.exists", return_value=True)
    @patch("youtube_mcp.tools.transcripts.quota")
    def test_wrong_format(self, mock_quota, _e):
        from youtube_mcp.tools.transcripts import youtube_upload_caption

        assert "error" in youtube_upload_caption("v", "/tmp/x.txt")
        mock_quota.consume.assert_not_called()

    @patch("youtube_mcp.tools.transcripts.MediaFileUpload")
    @patch("os.path.exists", return_value=True)
    @patch("youtube_mcp.tools.transcripts.auth")
    @patch("youtube_mcp.tools.transcripts.quota")
    def test_insert(self, mock_quota, mock_auth, _e, _m):
        from youtube_mcp.tools.transcripts import youtube_upload_caption

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.captions().insert().execute.return_value = {"id": "cap1", "snippet": {"language": "de", "name": "", "isDraft": False}}
        r = youtube_upload_caption("v", "/tmp/x.srt", language="de")
        body = mock_yt.captions().insert.call_args.kwargs["body"]
        assert body["snippet"]["videoId"] == "v" and body["snippet"]["language"] == "de"
        assert r["action"] == "inserted" and r["caption_id"] == "cap1"
        mock_quota.consume.assert_called_with("caption_insert")

    @patch("youtube_mcp.tools.transcripts.MediaFileUpload")
    @patch("os.path.exists", return_value=True)
    @patch("youtube_mcp.tools.transcripts.auth")
    @patch("youtube_mcp.tools.transcripts.quota")
    def test_replace_existing_updates_matching_track_only(self, mock_quota, mock_auth, _e, _m):
        from youtube_mcp.tools.transcripts import youtube_upload_caption

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.captions().list().execute.return_value = {"items": [
            {"id": "auto", "snippet": {"language": "de", "name": "", "trackKind": "asr"}},  # Auto-Untertitel: nie ersetzen
            {"id": "en1", "snippet": {"language": "en", "name": "", "trackKind": "standard"}},
            {"id": "de1", "snippet": {"language": "de", "name": "", "trackKind": "standard"}},
        ]}
        mock_yt.captions().update().execute.return_value = {"id": "de1", "snippet": {"language": "de"}}
        r = youtube_upload_caption("v", "/tmp/x.srt", language="de", replace_existing=True)
        assert r["action"] == "replaced" and r["caption_id"] == "de1"
        assert mock_yt.captions().update.call_args.kwargs["body"]["id"] == "de1"

    @patch("youtube_mcp.tools.transcripts.MediaFileUpload")
    @patch("os.path.exists", return_value=True)
    @patch("youtube_mcp.tools.transcripts.auth")
    @patch("youtube_mcp.tools.transcripts.quota")
    def test_replace_without_match_inserts(self, mock_quota, mock_auth, _e, _m):
        from youtube_mcp.tools.transcripts import youtube_upload_caption

        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.captions().list().execute.return_value = {"items": [
            {"id": "auto", "snippet": {"language": "de", "name": "", "trackKind": "asr"}},
        ]}
        mock_yt.captions().insert().execute.return_value = {"id": "neu", "snippet": {}}
        r = youtube_upload_caption("v", "/tmp/x.srt", language="de", replace_existing=True)
        assert r["action"] == "inserted"


BRANDING = {
    "channel": {"title": "Kanal", "description": "alt", "keywords": "a b", "country": "DE", "unsubscribedTrailer": "tr1"},
    "image": {"bannerExternalUrl": "https://alt/banner"},
}


class TestChannelBranding:
    def _setup(self, mock_auth):
        mock_yt = MagicMock()
        mock_auth.build_youtube_service.return_value = mock_yt
        mock_yt.channels().list().execute.return_value = {"items": [{"id": "UC1", "brandingSettings": BRANDING}]}
        mock_yt.channels().update().execute.return_value = {"brandingSettings": BRANDING}
        return mock_yt

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_description_only_keeps_everything_else(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_update_channel

        mock_yt = self._setup(mock_auth)
        youtube_update_channel(description="neu")
        sent = mock_yt.channels().update.call_args.kwargs["body"]["brandingSettings"]
        assert sent["channel"]["description"] == "neu"
        assert sent["channel"]["keywords"] == "a b"
        assert sent["channel"]["unsubscribedTrailer"] == "tr1"
        assert sent["image"]["bannerExternalUrl"] == "https://alt/banner"

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_keywords_quoted(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_update_channel

        mock_yt = self._setup(mock_auth)
        youtube_update_channel(keywords=["Arcanara", "Wissen entfalten"])
        assert mock_yt.channels().update.call_args.kwargs["body"]["brandingSettings"]["channel"]["keywords"] == 'Arcanara "Wissen entfalten"'

    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_description_too_long(self, mock_quota, mock_auth):
        from youtube_mcp.tools.channel import youtube_update_channel

        mock_yt = self._setup(mock_auth)
        assert "error" in youtube_update_channel(description="x" * 1001)
        # _setup ruft update() ohne Argumente auf, um den Rueckgabewert zu setzen;
        # gezaehlt wird nur ein echter Aufruf mit body.
        assert not any(c.kwargs for c in mock_yt.channels().update.call_args_list)

    @patch("youtube_mcp.tools.channel.MediaFileUpload")
    @patch("os.path.exists", return_value=True)
    @patch("youtube_mcp.tools.channel.auth")
    @patch("youtube_mcp.tools.channel.quota")
    def test_banner_two_steps_keeps_channel_settings(self, mock_quota, mock_auth, _e, _m):
        from youtube_mcp.tools.channel import youtube_set_channel_banner

        mock_yt = self._setup(mock_auth)
        mock_yt.channelBanners().insert().execute.return_value = {"url": "https://neu/banner"}
        r = youtube_set_channel_banner("/tmp/b.png")
        sent = mock_yt.channels().update.call_args.kwargs["body"]["brandingSettings"]
        assert sent["image"]["bannerExternalUrl"] == "https://neu/banner"
        assert sent["channel"]["description"] == "alt"
        assert r["banner_url"] == "https://neu/banner"
