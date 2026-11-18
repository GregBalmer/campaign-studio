"""Sending a request to the people who can act on it.

Email works everywhere with no setup: the browser opens the user's own mail app
with the message written (see the UI). Slack is optional: if IT sets
STUDIO_SLACK_WEBHOOK to an incoming-webhook URL, requests post straight to that
channel. In production this is where a Jira or ServiceNow connector would go.
"""
from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request


class NotifyError(RuntimeError):
    pass


def slack_webhook() -> str | None:
    url = os.environ.get("STUDIO_SLACK_WEBHOOK", "").strip()
    return url or None


def post_to_slack(text: str) -> None:
    url = slack_webhook()
    if not url:
        raise NotifyError("Slack isn't connected. Ask IT to set it up, or use email.")
    req = urllib.request.Request(url, data=json.dumps({"text": text}).encode("utf-8"),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            if r.status >= 300:
                raise NotifyError(f"Slack didn't accept the message ({r.status}).")
    except urllib.error.HTTPError as e:
        raise NotifyError(f"Slack didn't accept the message ({e.code}). The channel link may have changed.") from None
    except (urllib.error.URLError, socket.timeout, TimeoutError):
        raise NotifyError("Couldn't reach Slack. Check the internet connection, or use email.") from None
