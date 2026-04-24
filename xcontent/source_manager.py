"""
Source Manager — YouTube channel management, video search, and transcript fetching.

You add YouTube channels (Founders Podcast, etc.) once. Then you can search
across all of them, browse episodes, and pull transcripts — all from one place.
"""

from __future__ import annotations

import json
import os
import ssl
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SOURCES_DIR = Path(__file__).resolve().parent.parent / "sources"


def _ensure_sources_dir():
    SOURCES_DIR.mkdir(parents=True, exist_ok=True)


def _get_youtube_client():
    """Build an authenticated YouTube Data API client."""
    import httplib2
    from googleapiclient.discovery import build

    api_key = os.getenv("YOUTUBE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "YOUTUBE_API_KEY not set. Add it to your .env file.\n"
            "Get one at https://console.cloud.google.com/apis/credentials"
        )

    # Handle environments with custom/self-signed SSL certificates
    http = httplib2.Http(disable_ssl_certificate_validation=True)
    return build("youtube", "v3", developerKey=api_key, http=http)


# ── Channel Management ──────────────────────────────────────────────


def add_channel(channel_input: str) -> dict:
    """Add a YouTube channel to your sources.

    Args:
        channel_input: Channel URL, handle (@name), or channel ID.

    Returns:
        Channel info dict that was saved.
    """
    _ensure_sources_dir()
    youtube = _get_youtube_client()

    channel_id = _resolve_channel_id(youtube, channel_input)
    info = _fetch_channel_info(youtube, channel_id)

    # Save channel config
    path = SOURCES_DIR / f"{info['id']}.json"
    info["added_at"] = datetime.now().isoformat()
    path.write_text(json.dumps(info, indent=2))
    return info


def _resolve_channel_id(youtube, channel_input: str) -> str:
    """Resolve various channel input formats to a channel ID."""
    channel_input = channel_input.strip()

    # Already a channel ID
    if channel_input.startswith("UC") and len(channel_input) == 24:
        return channel_input

    # Handle @username
    if channel_input.startswith("@"):
        resp = youtube.channels().list(part="id", forHandle=channel_input).execute()
        items = resp.get("items", [])
        if not items:
            raise ValueError(f"No channel found for handle '{channel_input}'")
        return items[0]["id"]

    # Handle full URL
    if "youtube.com" in channel_input:
        import re

        # /channel/UCxxxxxx
        m = re.search(r"/channel/(UC[\w-]+)", channel_input)
        if m:
            return m.group(1)

        # /@handle
        m = re.search(r"/@([\w.-]+)", channel_input)
        if m:
            return _resolve_channel_id(youtube, f"@{m.group(1)}")

        # /c/CustomName or /user/Username
        m = re.search(r"/(c|user)/([\w.-]+)", channel_input)
        if m:
            resp = youtube.search().list(
                part="snippet", q=m.group(2), type="channel", maxResults=1
            ).execute()
            items = resp.get("items", [])
            if items:
                return items[0]["snippet"]["channelId"]

    # Fallback: treat as search query
    resp = youtube.search().list(
        part="snippet", q=channel_input, type="channel", maxResults=1
    ).execute()
    items = resp.get("items", [])
    if items:
        return items[0]["snippet"]["channelId"]

    raise ValueError(f"Could not resolve channel: '{channel_input}'")


def _fetch_channel_info(youtube, channel_id: str) -> dict:
    """Fetch channel metadata."""
    resp = youtube.channels().list(
        part="snippet,statistics,contentDetails", id=channel_id
    ).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Channel not found: {channel_id}")

    ch = items[0]
    return {
        "id": ch["id"],
        "title": ch["snippet"]["title"],
        "description": ch["snippet"].get("description", "")[:300],
        "subscriber_count": ch["statistics"].get("subscriberCount", "N/A"),
        "video_count": ch["statistics"].get("videoCount", "N/A"),
        "uploads_playlist": ch["contentDetails"]["relatedPlaylists"]["uploads"],
    }


def list_channels() -> list[dict]:
    """List all saved YouTube channels."""
    _ensure_sources_dir()
    channels = []
    for path in sorted(SOURCES_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        channels.append({
            "id": data["id"],
            "title": data["title"],
            "video_count": data.get("video_count", "?"),
            "added_at": data.get("added_at", ""),
        })
    return channels


def remove_channel(channel_id: str) -> bool:
    """Remove a channel from your sources."""
    path = SOURCES_DIR / f"{channel_id}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ── Video Search ─────────────────────────────────────────────────────


def search_videos(query: str, channel_ids: list[str] | None = None, max_results: int = 10) -> list[dict]:
    """Search for videos across your saved channels (or specific ones).

    Args:
        query: Search terms (e.g. "Bezos customer obsession")
        channel_ids: Optional list of channel IDs to restrict search.
                     If None, searches all saved channels.
        max_results: Max videos to return per channel.

    Returns:
        List of video info dicts sorted by relevance.
    """
    youtube = _get_youtube_client()

    if channel_ids is None:
        channel_ids = [ch["id"] for ch in list_channels()]

    if not channel_ids:
        raise RuntimeError("No channels added yet. Run 'xcontent source add' first.")

    all_results = []
    for cid in channel_ids:
        resp = youtube.search().list(
            part="snippet",
            q=query,
            channelId=cid,
            type="video",
            maxResults=max_results,
            order="relevance",
        ).execute()

        for item in resp.get("items", []):
            all_results.append({
                "video_id": item["id"]["videoId"],
                "title": item["snippet"]["title"],
                "channel": item["snippet"]["channelTitle"],
                "published": item["snippet"]["publishedAt"][:10],
                "description": item["snippet"]["description"][:200],
            })

    return all_results


def get_video_details(video_id: str) -> dict:
    """Get detailed info about a specific video."""
    youtube = _get_youtube_client()
    resp = youtube.videos().list(
        part="snippet,contentDetails,statistics", id=video_id
    ).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Video not found: {video_id}")

    v = items[0]
    return {
        "video_id": v["id"],
        "title": v["snippet"]["title"],
        "channel": v["snippet"]["channelTitle"],
        "published": v["snippet"]["publishedAt"][:10],
        "description": v["snippet"]["description"],
        "duration": v["contentDetails"]["duration"],
        "view_count": v["statistics"].get("viewCount", "N/A"),
    }


# ── Transcript Fetching ─────────────────────────────────────────────


def list_channel_videos(channel_input: str, max_results: int = 200) -> list[dict]:
    """List all videos from a YouTube channel.

    Uses the channel's uploads playlist to enumerate videos efficiently.
    Costs ~1 API unit per 50 videos listed.

    Args:
        channel_input: Channel URL, @handle, channel ID, or saved channel name.
        max_results: Max videos to return.

    Returns:
        List of {video_id, title, channel, published} dicts.
    """
    youtube = _get_youtube_client()
    channel_id = _resolve_channel_id(youtube, channel_input)

    resp = youtube.channels().list(part="contentDetails,snippet", id=channel_id).execute()
    items = resp.get("items", [])
    if not items:
        raise ValueError(f"Channel not found: {channel_id}")

    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    channel_name = items[0]["snippet"]["title"]

    videos = []
    page_token = None

    while len(videos) < max_results:
        params = {
            "part": "snippet",
            "playlistId": uploads_playlist,
            "maxResults": min(50, max_results - len(videos)),
        }
        if page_token:
            params["pageToken"] = page_token

        resp = youtube.playlistItems().list(**params).execute()

        for item in resp.get("items", []):
            snippet = item["snippet"]
            vid = snippet.get("resourceId", {}).get("videoId", "")
            if vid:
                videos.append({
                    "video_id": vid,
                    "title": snippet.get("title", ""),
                    "channel": channel_name,
                    "published": snippet.get("publishedAt", "")[:10],
                })

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return videos


def _get_ytt_api():
    """Get a YouTubeTranscriptApi instance, with cookies if available."""
    from youtube_transcript_api import YouTubeTranscriptApi

    cookie_path = Path(__file__).resolve().parent.parent / "cookies.txt"
    if cookie_path.exists():
        try:
            from http.cookiejar import MozillaCookieJar

            import requests as _req

            jar = MozillaCookieJar(str(cookie_path))
            jar.load(ignore_discard=True, ignore_expires=True)
            session = _req.Session()
            session.cookies = jar
            return YouTubeTranscriptApi(http_client=session)
        except Exception:
            pass
    return YouTubeTranscriptApi()


def get_transcript(video_id: str, languages: list[str] | None = None,
                   video_title: str = "", channel: str = "") -> str:
    """Fetch the transcript for a YouTube video.

    Auto-saves to the knowledge base so you never need to fetch it again.

    Args:
        video_id: YouTube video ID
        languages: Preferred languages (default: ["en"])
        video_title: Video title (for knowledge base storage)
        channel: Channel name (for knowledge base storage)

    Returns:
        Full transcript as a single string.
    """
    # Check knowledge base first — free, no API call
    from .knowledge_base import get_transcript_text, save_transcript

    cached = get_transcript_text(video_id)
    if cached:
        return cached

    if languages is None:
        languages = ["en"]

    ytt_api = _get_ytt_api()
    transcript = ytt_api.fetch(video_id, languages=languages)

    # Join all segments into a readable string
    lines = []
    for entry in transcript.snippets:
        lines.append(entry.text)

    text = " ".join(lines)

    # Auto-save to knowledge base
    save_transcript(video_id, video_title or video_id, text, channel)

    return text


def get_transcript_with_timestamps(video_id: str, languages: list[str] | None = None) -> list[dict]:
    """Fetch transcript with timestamps for each segment."""
    if languages is None:
        languages = ["en"]

    ytt_api = _get_ytt_api()
    transcript = ytt_api.fetch(video_id, languages=languages)

    return [
        {
            "text": entry.text,
            "start": entry.start,
            "duration": entry.duration,
        }
        for entry in transcript.snippets
    ]
