#!/usr/bin/env python3
"""
Notification dispatcher for AI Code Gate.

Currently supports:
  - Slack (via incoming webhook)
  - Generic webhook (JSON POST)

Designed to be called from CI after score.py completes. Failures are
non-fatal — a broken notification must never block a merge decision.

Usage:
  python scripts/notify.py \
    --webhook "https://hooks.slack.com/services/..." \
    --score 72.5 \
    --threshold 70 \
    --repo "org/repo" \
    --pr 42 \
    --pr-url "https://github.com/org/repo/pull/42"

  python scripts/notify.py \
    --webhook "https://your-server.com/hook" \
    --type generic \
    --score 55.0 \
    --threshold 70 \
    --repo "org/repo"
"""

import argparse
import json
import sys
import urllib.request
from urllib.error import URLError


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------
def build_slack_payload(
    score: float,
    threshold: float,
    repo: str,
    pr: int | None,
    pr_url: str,
) -> dict:
    passed = score >= threshold
    emoji = ":white_check_mark:" if passed else ":x:"
    status = "PASSED" if passed else "BLOCKED"
    color = "#2eb886" if passed else "#e01e5a"

    pr_text = f"<{pr_url}|PR #{pr}>" if pr and pr_url else (f"PR #{pr}" if pr else "push")

    return {
        "attachments": [
            {
                "color": color,
                "blocks": [
                    {
                        "type": "section",
                        "text": {
                            "type": "mrkdwn",
                            "text": (
                                f"{emoji} *AI Code Gate — {status}*\n"
                                f"*Repo:* `{repo}` | *Run:* {pr_text}\n"
                                f"*Score:* `{score:.1f} / 100` (threshold: {threshold:.0f})"
                            ),
                        },
                    }
                ],
            }
        ]
    }


def build_generic_payload(
    score: float,
    threshold: float,
    repo: str,
    pr: int | None,
    pr_url: str,
) -> dict:
    return {
        "event": "ai_gate_result",
        "repo": repo,
        "pr": pr,
        "pr_url": pr_url,
        "score": score,
        "threshold": threshold,
        "passed": score >= threshold,
    }


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------
def send_webhook(url: str, payload: dict, timeout: int = 10) -> bool:
    """
    POST JSON payload to a webhook URL. Returns True on success.
    """
    body = json.dumps(payload).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json", "User-Agent": "ai-code-gate/1.0"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status < 400
    except URLError as e:
        print(f"[notify] Webhook delivery failed: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"[notify] Unexpected error sending webhook: {e}", file=sys.stderr)
        return False


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main() -> None:
    parser = argparse.ArgumentParser(description="Send AI gate score notifications")
    parser.add_argument("--webhook", required=True, help="Webhook URL (Slack or generic)")
    parser.add_argument(
        "--type",
        choices=["slack", "generic"],
        default="slack",
        help="Webhook type (default: slack)",
    )
    parser.add_argument("--score", type=float, required=True)
    parser.add_argument("--threshold", type=float, default=70.0)
    parser.add_argument("--repo", default="unknown/repo")
    parser.add_argument("--pr", type=int, default=None)
    parser.add_argument("--pr-url", default="")
    parser.add_argument(
        "--only-on-failure",
        action="store_true",
        help="Only send notification when score is below threshold",
    )
    args = parser.parse_args()

    passed = args.score >= args.threshold
    if args.only_on_failure and passed:
        print("[notify] Score passed threshold — skipping notification (--only-on-failure set)")
        return

    if args.type == "slack":
        payload = build_slack_payload(args.score, args.threshold, args.repo, args.pr, args.pr_url)
    else:
        payload = build_generic_payload(args.score, args.threshold, args.repo, args.pr, args.pr_url)

    ok = send_webhook(args.webhook, payload)
    if ok:
        print(f"[notify] Notification delivered to {args.type} webhook")
    else:
        print("[notify] Notification failed — continuing (non-fatal)", file=sys.stderr)
        # Notifications must never block CI — exit 0 always
        sys.exit(0)


if __name__ == "__main__":
    main()
