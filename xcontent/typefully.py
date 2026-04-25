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


def get_published_drafts(limit: int = 50) -> list[dict]:
    """Fetch recently published drafts from Typefully.

    Returns list of dicts with at least {id, text, published_at}.
    """
    api_key = _get_api_key()
    social_set_id = _get_social_set_id()

    resp = requests.get(
        f"https://api.typefully.com/v2/social-sets/{social_set_id}/drafts",
        headers={"Authorization": f"Bearer {api_key}"},
        params={"status": "published"},
    )

    if resp.status_code in (401, 403):
        raise RuntimeError(f"Typefully API error {resp.status_code}: {resp.text}")
    resp.raise_for_status()

    body = resp.json()

    # Debug: show raw response structure
    if os.getenv("XCONTENT_DEBUG"):
        import json as _j
        print(f"[typefully] status={resp.status_code}")
        print(f"[typefully] body type={type(body).__name__}")
        if isinstance(body, dict):
            print(f"[typefully] keys={list(body.keys())}")
            for k, v in body.items():
                if isinstance(v, list):
                    print(f"[typefully] {k}: {len(v)} items")
                    if v:
                        print(f"[typefully] first item keys: {list(v[0].keys()) if isinstance(v[0], dict) else type(v[0])}")
        elif isinstance(body, list):
            print(f"[typefully] list of {len(body)} items")
            if body:
                print(f"[typefully] first item keys: {list(body[0].keys()) if isinstance(body[0], dict) else type(body[0])}")

    # Handle both list and paginated response formats
    items = body if isinstance(body, list) else body.get("data", body.get("drafts", []))
    if not isinstance(items, list):
        items = []

    results = []
    for item in items[:limit]:
        draft_id = item.get("id", "")
        published_at = item.get("published_at", item.get("updated_at", ""))

        # Extract the post text — try nested platforms.x.posts first, then fallback
        text = ""
        platforms = item.get("platforms", {})
        x_data = platforms.get("x", {})
        posts = x_data.get("posts", [])
        if posts:
            text = posts[0].get("text", "")

        if not text:
            text = item.get("preview", item.get("text", item.get("draft_title", "")))

        if text:
            results.append({
                "id": str(draft_id),
                "text": text,
                "published_at": published_at,
            })

    return results
