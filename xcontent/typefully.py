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


def _get_api_key() -> str:
    key = os.getenv("TYPEFULLY_API_KEY")
    if not key:
        raise RuntimeError(
            "TYPEFULLY_API_KEY not set. Add it to your .env file.\n"
            "Get one at https://typefully.com/settings/api"
        )
    return key


def _get_social_set_id() -> str:
    sid = os.getenv("TYPEFULLY_SOCIAL_SET_ID")
    if not sid:
        raise RuntimeError(
            "TYPEFULLY_SOCIAL_SET_ID not set. Add it to your .env file.\n"
            "Enable Development Mode in Typefully Settings > API to find it."
        )
    return sid


def create_draft(content: str) -> dict:
    """Create a new draft in Typefully via v2 API.

    Args:
        content: The post text.

    Returns:
        Dict with draft info from the API.
    """
    api_key = _get_api_key()
    social_set_id = _get_social_set_id()

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

    if resp.status_code in (401, 403):
        raise RuntimeError(
            f"Typefully API error {resp.status_code}: {resp.text}"
        )
    if resp.status_code == 429:
        raise RuntimeError("Typefully rate limit hit. Wait a moment and try again.")

    resp.raise_for_status()
    return resp.json()


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
