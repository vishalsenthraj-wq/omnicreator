"""Instagram Graph API client: fetch media, fetch comments, post replies.

Uses the "API setup with Instagram login" flow, which talks to graph.instagram.com.
As a fallback (some setups/API versions route Instagram Business accounts through
the classic Facebook Graph API host instead), if a call to graph.instagram.com fails
with a permissions/not-found style error, we retry the same call against
graph.facebook.com with the same token. Whichever host actually works in practice
should be documented in the README.
"""
import logging
import os

import requests

logger = logging.getLogger("omnicreator.instagram")

API_VERSION = "v21.0"
PRIMARY_HOST = "https://graph.instagram.com"
FALLBACK_HOST = "https://graph.facebook.com"

REQUEST_TIMEOUT = 15


class InstagramConfigError(Exception):
    """Raised when required Instagram credentials are missing."""


class InstagramAPIError(Exception):
    """Raised when the Instagram Graph API returns an error we can't recover from."""


def _get_credentials():
    token = os.getenv("IG_ACCESS_TOKEN")
    account_id = os.getenv("IG_BUSINESS_ACCOUNT_ID")
    if not token or not account_id:
        raise InstagramConfigError(
            "Instagram not configured: set IG_ACCESS_TOKEN and IG_BUSINESS_ACCOUNT_ID in .env"
        )
    return token, account_id


def _is_retryable_error(resp: requests.Response) -> bool:
    """True if this looks like a host/permissions mismatch worth retrying on the fallback host."""
    if resp.status_code in (404, 400, 403):
        return True
    return False


def _request(method: str, path_template: str, token: str, params: dict | None = None,
             data: dict | None = None):
    """Issue a request against the primary host, retrying on the fallback host on failure."""
    params = dict(params or {})
    params["access_token"] = token

    last_error = None
    for host in (PRIMARY_HOST, FALLBACK_HOST):
        url = f"{host}/{API_VERSION}/{path_template}"
        try:
            resp = requests.request(method, url, params=params, data=data, timeout=REQUEST_TIMEOUT)
        except requests.RequestException as exc:
            logger.error("Instagram API request to %s failed: %s", host, exc)
            last_error = str(exc)
            continue

        if resp.ok:
            if host == FALLBACK_HOST:
                logger.info("Instagram API call succeeded via fallback host %s (path=%s)", host, path_template)
            return resp.json()

        try:
            err_body = resp.json()
            err_msg = err_body.get("error", {}).get("message", resp.text)
        except ValueError:
            err_msg = resp.text
        logger.warning("Instagram API error from %s (status=%s): %s", host, resp.status_code, err_msg)
        last_error = err_msg

        if host == PRIMARY_HOST and _is_retryable_error(resp):
            continue
        else:
            raise InstagramAPIError(f"Instagram API error ({resp.status_code}): {err_msg}")

    raise InstagramAPIError(f"Instagram API request failed on both hosts: {last_error}")


def fetch_recent_media(limit: int = 10) -> list[dict]:
    """Fetch recent media (posts) for the configured IG Business Account."""
    token, account_id = _get_credentials()
    result = _request(
        "GET",
        f"{account_id}/media",
        token,
        params={"fields": "id,caption,timestamp", "limit": limit},
    )
    return result.get("data", [])


def fetch_comments(media_id: str) -> list[dict]:
    """Fetch comments for a given media (post) ID."""
    token, _ = _get_credentials()
    result = _request(
        "GET",
        f"{media_id}/comments",
        token,
        params={"fields": "id,text,username,timestamp"},
    )
    return result.get("data", [])


def post_reply(comment_id: str, message: str) -> dict:
    """Post a reply to a specific comment. Raises InstagramAPIError on failure."""
    token, _ = _get_credentials()
    return _request(
        "POST",
        f"{comment_id}/replies",
        token,
        data={"message": message},
    )
