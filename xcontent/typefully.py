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


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {_get_api_key()}",
        "Content-Type": "application/json",
    }


def _get_social_set_id() -> str:
    """Fetch the first social set ID from the account."""
    global _social_set_id_cache
    if _social_set_id_cache:
        return _social_set_id_cache

    response = requests.get(
        "https://api.typefully.com/v2/social-sets",
        headers=_headers(),
    )
    response.raise_for_status()
    data = response.json()

    # Response could be a list or have a 'data' key
    sets = data if isinstance(data, list) else data.get("data", data.get("social_sets", []))
    if not sets:
        raise RuntimeError("No social sets found in your Typefully account.")

    _social_set_id_cache = sets[0]["id"]
    return _social_set_id_cache


def create_draft(content: str) -> dict:
    """Create a new draft in Typefully via v2 API.

    Args:
        content: The post text.

    Returns:
        Dict with draft info from the API.
    """
    social_set_id = _get_social_set_id()

    response = requests.post(
        f"https://api.typefully.com/v2/social-sets/{social_set_id}/drafts",
        headers=_headers(),
        json={
            "platforms": {
                "x": {
                    "enabled": True,
                    "posts": [{"text": content}],
                }
            }
        },
    )

    if response.status_code == 401:
        raise RuntimeError(
            "Typefully API key is invalid. Check your TYPEFULLY_API_KEY in .env\n"
            "Get a new one at https://typefully.com/settings/api"
        )
    if response.status_code == 403:
        raise RuntimeError(
            f"Typefully API returned 403. Response: {response.text}"
        )
    if response.status_code == 429:
        raise RuntimeError("Typefully rate limit hit. Wait a moment and try again.")

    response.raise_for_status()
    return response.json()


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
