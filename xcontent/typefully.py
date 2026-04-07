"""
Typefully Integration — Push generated posts directly as drafts.

Instead of saving to local files, send posts straight to your
Typefully drafts queue so they're ready to schedule and publish.
"""

from __future__ import annotations

import os

import requests
from dotenv import load_dotenv

load_dotenv()

_social_set_id_cache = None


def _get_api_key() -> str:
    key = os.getenv("TYPEFULLY_API_KEY")
    if not key:
        raise RuntimeError(
            "TYPEFULLY_API_KEY not set. Add it to your .env file.\n"
            "Get one at https://typefully.com/settings/api"
        )
    return key


def _try_v1(content: str) -> dict | None:
    """Try creating a draft via v1 API. Returns result or None if it fails."""
    api_key = _get_api_key()

    # Try both header formats for v1
    for headers in [
        {"X-API-KEY": f"Bearer {api_key}", "Content-Type": "application/json"},
        {"X-API-KEY": api_key, "Content-Type": "application/json"},
    ]:
        resp = requests.post(
            "https://api.typefully.com/v1/drafts/",
            headers=headers,
            json={"content": content, "threadify": False},
        )
        if resp.status_code == 200:
            return resp.json()

    return None


def _get_social_set_id() -> str:
    """Fetch the social set ID from the account (v2)."""
    global _social_set_id_cache
    if _social_set_id_cache:
        return _social_set_id_cache

    api_key = _get_api_key()

    # Try both auth header formats
    for headers in [
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        {"X-API-KEY": f"Bearer {api_key}", "Content-Type": "application/json"},
        {"X-API-KEY": api_key, "Content-Type": "application/json"},
    ]:
        resp = requests.get("https://api.typefully.com/v2/social-sets", headers=headers)
        if resp.status_code == 200:
            data = resp.json()
            sets = data if isinstance(data, list) else data.get("data", data.get("social_sets", []))
            if sets:
                _social_set_id_cache = sets[0]["id"]
                return _social_set_id_cache

    raise RuntimeError(
        "Could not fetch social sets from Typefully.\n"
        "Your API key may be an MCP-only key.\n"
        "Go to https://typefully.com/settings/api and generate a REST API key."
    )


def _try_v2(content: str) -> dict:
    """Create draft via v2 API."""
    social_set_id = _get_social_set_id()
    api_key = _get_api_key()

    resp = requests.post(
        f"https://api.typefully.com/v2/social-sets/{social_set_id}/drafts",
        headers={
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "platforms": {
                "x": {
                    "enabled": True,
                    "posts": [{"text": content}],
                }
            }
        },
    )
    resp.raise_for_status()
    return resp.json()


def create_draft(content: str) -> dict:
    """Create a new draft in Typefully. Tries v1 first, falls back to v2.

    Args:
        content: The post text.

    Returns:
        Dict with draft info from the API.
    """
    # Try v1 first (simpler, no social set needed)
    result = _try_v1(content)
    if result is not None:
        return result

    # Fall back to v2
    return _try_v2(content)


def push_drafts(posts: list[str]) -> list[dict]:
    """Push multiple posts as separate Typefully drafts.

    Args:
        posts: List of post texts.

    Returns:
        List of draft results from the API.
    """
    results = []
    for post in posts:
        result = create_draft(post)
        results.append(result)
    return results
