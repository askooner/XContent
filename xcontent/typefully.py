"""
Typefully Integration — Push generated posts directly as drafts.

Instead of saving to local files, send posts straight to your
Typefully drafts queue so they're ready to schedule and publish.
"""

from __future__ import annotations

import json
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


def create_draft(content: str, threadify: bool = False, share: bool = False) -> dict:
    """Create a new draft in Typefully.

    Args:
        content: The post text. For threads, separate tweets with \\n\\n\\n\\n (4 newlines).
        threadify: If True, Typefully auto-splits long content into a thread.
        share: If True, returns a share URL for the draft.

    Returns:
        Dict with draft info (id, share_url if requested).
    """
    api_key = _get_api_key()

    response = requests.post(
        "https://api.typefully.com/v1/drafts/",
        headers={
            "X-API-KEY": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        json={
            "content": content,
            "threadify": threadify,
            "share": share,
        },
    )

    if response.status_code == 401:
        raise RuntimeError(
            "Typefully API key is invalid. Check your TYPEFULLY_API_KEY in .env\n"
            "Get a new one at https://typefully.com/settings/api"
        )
    if response.status_code == 429:
        raise RuntimeError("Typefully rate limit hit. Wait a moment and try again.")

    response.raise_for_status()
    return response.json()


def push_drafts(posts: list[str], threadify: bool = False) -> list[dict]:
    """Push multiple posts as separate Typefully drafts.

    Args:
        posts: List of post texts.
        threadify: If True, auto-split long posts into threads.

    Returns:
        List of draft results from the API.
    """
    results = []
    for post in posts:
        result = create_draft(post, threadify=threadify)
        results.append(result)
    return results
