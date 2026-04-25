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


def _parse_duration(iso_duration: str) -> int:
    """Parse ISO 8601 duration (PT1H2M3S) to total seconds."""
    import re
    m = re.match(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?", iso_duration)
    if not m:
        return 0
    hours = int(m.group(1) or 0)
    minutes = int(m.group(2) or 0)
    seconds = int(m.group(3) or 0)
    return hours * 3600 + minutes * 60 + seconds


def list_channel_videos(channel_input: str, max_results: int = 200,
                        min_duration: int = 600) -> list[dict]:
    """List long-form videos from a YouTube channel (filters out Shorts/clips).

    Args:
        channel_input: Channel URL, @handle, channel ID, or saved channel name.
        max_results: Max videos to return.
        min_duration: Minimum video duration in seconds (default 600 = 10 min).

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

    # Keep paginating through uploads until we find enough long-form videos.
    # Channels that post lots of Shorts may need deep scanning.
    videos = []
    page_token = None
    max_pages = 20  # safety limit: 20 pages x 50 = 1000 uploads scanned max

    for _ in range(max_pages):
        if len(videos) >= max_results:
            break

        params = {
            "part": "snippet",
            "playlistId": uploads_playlist,
            "maxResults": 50,
        }
        if page_token:
            params["pageToken"] = page_token

        resp = youtube.playlistItems().list(**params).execute()

        page_videos = []
        for item in resp.get("items", []):
            snippet = item["snippet"]
            vid = snippet.get("resourceId", {}).get("videoId", "")
            if vid:
                page_videos.append({
                    "video_id": vid,
                    "title": snippet.get("title", ""),
                    "channel": channel_name,
                    "published": snippet.get("publishedAt", "")[:10],
                })

        if not page_videos:
            break

        # Check durations for this page and keep only long-form
        ids = ",".join(v["video_id"] for v in page_videos)
        details = youtube.videos().list(part="contentDetails", id=ids).execute()

        duration_map = {}
        for item in details.get("items", []):
            duration_map[item["id"]] = _parse_duration(
                item["contentDetails"].get("duration", "PT0S")
            )

        for v in page_videos:
            if duration_map.get(v["video_id"], 0) >= min_duration:
                videos.append(v)
                if len(videos) >= max_results:
                    break

        page_token = resp.get("nextPageToken")
        if not page_token:
            break

    return videos


def _get_ytt_api():
    """Get a YouTubeTranscriptApi with browser-like session to avoid blocks."""
    import requests as _req
    from youtube_transcript_api import YouTubeTranscriptApi

    session = _req.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    session.cookies.set("CONSENT", "YES+cb", domain=".youtube.com")

    cookie_path = Path(__file__).resolve().parent.parent / "cookies.txt"
    if cookie_path.exists():
        try:
            from http.cookiejar import MozillaCookieJar
            jar = MozillaCookieJar(str(cookie_path))
            jar.load(ignore_discard=True, ignore_expires=True)
            session.cookies.update(jar)
        except Exception:
            pass

    return YouTubeTranscriptApi(http_client=session)


def _fetch_transcript_ytdlp(video_id: str, debug: bool = False) -> str | None:
    """Fallback: fetch transcript using yt-dlp CLI (bypasses YouTube blocks).

    Uses yt-dlp as a subprocess so it works with Homebrew installs that
    bundle their own Python, avoiding Python 3.9 compatibility issues.
    """
    import re
    import shutil
    import subprocess
    import tempfile

    # Prefer venv yt-dlp (shares Python env with curl_cffi for impersonation)
    import sys
    venv_ytdlp = os.path.join(os.path.dirname(sys.executable), "yt-dlp")
    if os.path.isfile(venv_ytdlp):
        ytdlp = venv_ytdlp
    else:
        ytdlp = shutil.which("yt-dlp") or shutil.which("yt-dlp", path="/opt/homebrew/bin:/usr/local/bin")
    if not ytdlp:
        if debug:
            print("[yt-dlp] not found in PATH, venv, or /opt/homebrew/bin")
        return None
    if debug:
        print(f"[yt-dlp] using: {ytdlp}")

    cookie_path = Path(__file__).resolve().parent.parent / "cookies.txt"

    # Build list of auth strategies to try in order.
    # Chrome cookies got furthest in testing (bypasses 429).
    # web_creator player client avoids YouTube's JS challenge.
    cookie_strategies = [
        ["--cookies-from-browser", "chrome"],
    ]
    if cookie_path.exists():
        cookie_strategies.append(["--cookies", str(cookie_path)])
    cookie_strategies.append([])  # no cookies, impersonation only

    for strategy in cookie_strategies:
      with tempfile.TemporaryDirectory() as tmpdir:
        cmd = [
            ytdlp,
            "--skip-download",
            "--write-sub",
            "--write-auto-sub",
            "--sub-lang", "en",
            "--sub-format", "vtt/srt/best",
            "--ignore-errors",
            "--extractor-args", "youtube:player_client=web_creator",
            "-o", f"{tmpdir}/sub",
            f"https://www.youtube.com/watch?v={video_id}",
        ] + strategy

        strategy_name = strategy[1] if strategy else "impersonation only"
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=120
            )
            if debug:
                print(f"[yt-dlp] strategy: {strategy_name} → exit {result.returncode}")
                if result.stderr:
                    for line in result.stderr.strip().split("\n")[-3:]:
                        print(f"[yt-dlp]   {line}")
        except Exception as e:
            if debug:
                print(f"[yt-dlp] strategy: {strategy_name} → error: {e}")
            continue

        # Find the subtitle file
        sub_files = [f for f in os.listdir(tmpdir) if f.endswith((".vtt", ".srt", ".srv1"))]
        if debug:
            print(f"[yt-dlp] files in tmpdir: {os.listdir(tmpdir)}")

        if not sub_files:
            continue

        with open(os.path.join(tmpdir, sub_files[0])) as f:
            raw = f.read()

        # Strip VTT/SRT formatting to plain text
        lines = []
        seen = set()
        for line in raw.split("\n"):
            line = line.strip()
            if not line:
                continue
            if re.match(r"^\d+$", line):
                continue
            if "-->" in line:
                continue
            if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
                continue
            line = re.sub(r"<[^>]+>", "", line)
            if line and line not in seen:
                seen.add(line)
                lines.append(line)

        text = " ".join(lines)
        if len(text) > 100:
            return text

    return None


def _fetch_transcript_direct(video_id: str, debug: bool = False) -> str | None:
    """Fetch transcript via YouTube's innertube API.

    Extracts the transcript engagement panel params from the video page,
    then calls get_transcript with those exact params. This avoids
    guessing protobuf formats and bypasses caption URL rate limiting.
    """
    import html as html_mod
    import re

    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) "
                      "Chrome/125.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
    })
    session.cookies.set("CONSENT", "YES+cb", domain=".youtube.com")

    # Fetch the video page
    try:
        page = session.get(
            f"https://www.youtube.com/watch?v={video_id}", timeout=30
        )
        if debug:
            print(f"[innertube] page: {page.status_code}")
    except Exception as e:
        if debug:
            print(f"[innertube] page failed: {e}")
        return None

    if page.status_code != 200:
        return None

    # Extract innertube API key
    key_match = re.search(r'"INNERTUBE_API_KEY":"([^"]+)"', page.text)
    api_key = key_match.group(1) if key_match else "AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8"

    ver_match = re.search(r'"INNERTUBE_CLIENT_VERSION":"([^"]+)"', page.text)
    client_version = ver_match.group(1) if ver_match else "2.20250420.01.00"

    # Extract transcript params from the engagement panel in ytInitialData
    # YouTube embeds the exact params we need in the page's initial data
    params = None

    # Method 1: Look for transcript engagement panel params
    params_match = re.search(
        r'"engagement-panel-searchable-transcript".*?"serializedShareEntity":"([^"]+)"',
        page.text
    )
    if params_match:
        params = params_match.group(1)
        if debug:
            print(f"[innertube] found panel params")

    # Method 2: Look for showEngagementPanelEndpoint with transcript params
    if not params:
        params_match = re.search(
            r'"showTranscriptEndpoint"\s*:\s*\{[^}]*"params"\s*:\s*"([^"]+)"',
            page.text
        )
        if params_match:
            params = params_match.group(1)
            if debug:
                print(f"[innertube] found transcript endpoint params")

    # Method 3: Look for any get_transcript params in the page
    if not params:
        params_match = re.search(
            r'get_transcript[^}]*"params"\s*:\s*"([^"]+)"',
            page.text
        )
        if params_match:
            params = params_match.group(1)
            if debug:
                print(f"[innertube] found get_transcript params")

    # Method 4: Build params from video ID (flat protobuf, not nested)
    if not params:
        import base64
        vid_bytes = video_id.encode("utf-8")
        proto = b"\x0a" + bytes([len(vid_bytes)]) + vid_bytes + b"\x12\x00\x1a\x00"
        params = base64.b64encode(proto).decode("utf-8")
        if debug:
            print(f"[innertube] using constructed params: {params}")

    if debug:
        print(f"[innertube] key={api_key[:20]}... version={client_version}")

    # Call the innertube get_transcript endpoint
    payload = {
        "context": {
            "client": {
                "hl": "en",
                "gl": "US",
                "clientName": "WEB",
                "clientVersion": client_version,
            }
        },
        "params": params,
    }

    try:
        resp = session.post(
            f"https://www.youtube.com/youtubei/v1/get_transcript?key={api_key}",
            json=payload,
            timeout=30,
        )
        if debug:
            print(f"[innertube] transcript API: {resp.status_code}")
    except Exception as e:
        if debug:
            print(f"[innertube] API call failed: {e}")
        return None

    if resp.status_code != 200:
        if debug:
            print(f"[innertube] error: {resp.text[:200]}")
        return None

    # Parse the transcript from the innertube response
    data = resp.json()
    try:
        body = (
            data["actions"][0]["updateEngagementPanelAction"]
            ["content"]["transcriptRenderer"]["body"]
            ["transcriptBodyRenderer"]["cueGroups"]
        )
    except (KeyError, IndexError):
        if debug:
            print(f"[innertube] unexpected response structure: {json.dumps(data, indent=2)[:500]}")
        return None

    segments = []
    for group in body:
        try:
            cue = group["transcriptCueGroupRenderer"]["cues"][0]["transcriptCueRenderer"]
            text = cue["cue"]["simpleText"]
            segments.append(html_mod.unescape(text))
        except (KeyError, IndexError):
            continue

    text = " ".join(segments)
    if debug:
        print(f"[innertube] got {len(segments)} segments, {len(text)} chars")

    return text if len(text) > 100 else None


def get_transcript(video_id: str, languages: list[str] | None = None,
                   video_title: str = "", channel: str = "") -> str:
    """Fetch the transcript for a YouTube video.

    Tries youtube-transcript-api first, falls back to yt-dlp.
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

    text = _fetch_transcript_direct(video_id)

    if not text:
        try:
            ytt_api = _get_ytt_api()
            transcript = ytt_api.fetch(video_id, languages=languages)
            text = " ".join(entry.text for entry in transcript.snippets)
        except Exception:
            pass

    if not text:
        text = _fetch_transcript_ytdlp(video_id)

    if not text:
        raise RuntimeError(f"Could not fetch transcript for {video_id}")

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
