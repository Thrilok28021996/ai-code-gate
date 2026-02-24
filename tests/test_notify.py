"""
Tests for scripts/notify.py

Covers:
- build_slack_payload(): structure, colour, pass/fail messaging
- build_generic_payload(): fields and passed flag
- send_webhook(): success and failure cases (mocked)
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from notify import build_generic_payload, build_slack_payload, send_webhook  # noqa: E402


class TestBuildSlackPayload:
    def test_passed_uses_green_color(self):
        payload = build_slack_payload(80.0, 70.0, "org/repo", pr=1, pr_url="https://example.com")
        assert payload["attachments"][0]["color"] == "#2eb886"

    def test_failed_uses_red_color(self):
        payload = build_slack_payload(60.0, 70.0, "org/repo", pr=1, pr_url="https://example.com")
        assert payload["attachments"][0]["color"] == "#e01e5a"

    def test_passed_status_in_text(self):
        payload = build_slack_payload(80.0, 70.0, "org/repo", pr=1, pr_url="")
        text = payload["attachments"][0]["blocks"][0]["text"]["text"]
        assert "PASSED" in text

    def test_blocked_status_in_text(self):
        payload = build_slack_payload(50.0, 70.0, "org/repo", pr=1, pr_url="")
        text = payload["attachments"][0]["blocks"][0]["text"]["text"]
        assert "BLOCKED" in text

    def test_score_in_text(self):
        payload = build_slack_payload(82.5, 70.0, "org/repo", pr=None, pr_url="")
        text = payload["attachments"][0]["blocks"][0]["text"]["text"]
        assert "82.5" in text

    def test_repo_in_text(self):
        payload = build_slack_payload(75.0, 70.0, "myorg/myrepo", pr=None, pr_url="")
        text = payload["attachments"][0]["blocks"][0]["text"]["text"]
        assert "myorg/myrepo" in text

    def test_pr_link_present_when_url_given(self):
        payload = build_slack_payload(
            75.0, 70.0, "org/repo", pr=42, pr_url="https://github.com/org/repo/pull/42"
        )
        text = payload["attachments"][0]["blocks"][0]["text"]["text"]
        assert "42" in text
        assert "https://github.com/org/repo/pull/42" in text

    def test_no_pr_shows_push(self):
        payload = build_slack_payload(75.0, 70.0, "org/repo", pr=None, pr_url="")
        text = payload["attachments"][0]["blocks"][0]["text"]["text"]
        assert "push" in text

    def test_payload_has_attachments_key(self):
        payload = build_slack_payload(75.0, 70.0, "org/repo", pr=None, pr_url="")
        assert "attachments" in payload
        assert isinstance(payload["attachments"], list)


class TestBuildGenericPayload:
    def test_passed_flag_true_when_above_threshold(self):
        payload = build_generic_payload(80.0, 70.0, "org/repo", pr=1, pr_url="")
        assert payload["passed"] is True

    def test_passed_flag_false_when_below_threshold(self):
        payload = build_generic_payload(60.0, 70.0, "org/repo", pr=1, pr_url="")
        assert payload["passed"] is False

    def test_event_field(self):
        payload = build_generic_payload(75.0, 70.0, "org/repo", pr=None, pr_url="")
        assert payload["event"] == "ai_gate_result"

    def test_score_field(self):
        payload = build_generic_payload(77.5, 70.0, "org/repo", pr=None, pr_url="")
        assert payload["score"] == 77.5

    def test_repo_field(self):
        payload = build_generic_payload(77.5, 70.0, "myorg/myrepo", pr=None, pr_url="")
        assert payload["repo"] == "myorg/myrepo"

    def test_pr_field(self):
        payload = build_generic_payload(77.5, 70.0, "org/repo", pr=99, pr_url="https://example.com")
        assert payload["pr"] == 99
        assert payload["pr_url"] == "https://example.com"


class TestSendWebhook:
    def test_returns_true_on_200(self):
        mock_resp = MagicMock()
        mock_resp.status = 200
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("notify.urllib.request.urlopen", return_value=mock_resp):
            result = send_webhook("https://example.com/hook", {"key": "value"})
        assert result is True

    def test_returns_false_on_url_error(self):
        import urllib.error

        with patch(
            "notify.urllib.request.urlopen",
            side_effect=urllib.error.URLError("connection refused"),
        ):
            result = send_webhook("https://example.com/hook", {"key": "value"})
        assert result is False

    def test_returns_false_on_500(self):
        mock_resp = MagicMock()
        mock_resp.status = 500
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)

        with patch("notify.urllib.request.urlopen", return_value=mock_resp):
            result = send_webhook("https://example.com/hook", {})
        assert result is False

    def test_returns_false_on_unexpected_exception(self):
        with patch("notify.urllib.request.urlopen", side_effect=RuntimeError("boom")):
            result = send_webhook("https://example.com/hook", {})
        assert result is False
