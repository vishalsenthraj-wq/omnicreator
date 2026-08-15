"""ntfy.sh push notification dispatcher for VIP (BUSINESS_COLLABORATION) leads."""
import logging
import os

import requests

logger = logging.getLogger("omnicreator.notifier")

NTFY_BASE_URL = "https://ntfy.sh"
REQUEST_TIMEOUT = 10


def send_vip_notification(username: str, summary: str | None):
    topic = os.getenv("NTFY_TOPIC")
    if not topic:
        logger.info("NTFY_TOPIC not set — skipping push notification for @%s (log only)", username)
        return

    summary_text = summary or "New potential collaboration opportunity."
    message = f"@{username}: {summary_text}"
    title = "New Collab Lead Detected!"

    try:
        resp = requests.post(
            f"{NTFY_BASE_URL}/{topic}",
            data=message.encode("utf-8"),
            headers={
                "Title": title,
                "Priority": "high",
                "Tags": "rotating_light",
            },
            timeout=REQUEST_TIMEOUT,
        )
        if resp.ok:
            logger.info("ntfy notification sent for @%s", username)
        else:
            logger.warning("ntfy notification failed (status=%s): %s", resp.status_code, resp.text)
    except requests.RequestException as exc:
        logger.warning("ntfy notification request failed: %s", exc)
