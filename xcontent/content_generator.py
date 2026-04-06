"""
Content Generator — Combine your style + source material to produce posts.

This is the assembly line: your style is the template, YouTube transcripts
are the raw material, and Claude does the assembly.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


def _ensure_content_dir():
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)


def _get_anthropic_client():
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to your .env file.\n"
            "Get one at https://console.anthropic.com/settings/keys"
        )
    return anthropic.Anthropic(api_key=api_key)


def generate(
    style_name: str,
    transcript: str,
    topic: str = "",
    focus: str = "",
    content_type: str = "linkedin",
    additional_instructions: str = "",
    model: str | None = None,
    video_title: str = "",
) -> str:
    """Generate content in your style from a transcript.

    Args:
        style_name: Name of the saved style profile to use.
        transcript: The source transcript text.
        topic: What the post should be about (e.g. "Bezos on customer obsession").
        focus: Specific angle or moment to focus on. Leave empty for best-of extraction.
        content_type: Type of content — "linkedin", "twitter", "thread", "newsletter".
        additional_instructions: Any extra direction for this specific post.
        model: Claude model to use. Defaults to CLAUDE_MODEL env var.
        video_title: Title of the source video (for context).

    Returns:
        The generated content as a string.
    """
    from .style_manager import build_style_prompt

    client = _get_anthropic_client()
    model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514")

    style_prompt = build_style_prompt(style_name)

    system_prompt = _build_system_prompt(style_prompt, content_type)
    user_prompt = _build_user_prompt(transcript, topic, focus, additional_instructions, video_title)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    content = response.content[0].text
    return content


def generate_and_save(
    style_name: str,
    transcript: str,
    topic: str = "",
    focus: str = "",
    content_type: str = "linkedin",
    additional_instructions: str = "",
    model: str | None = None,
    video_title: str = "",
    video_id: str = "",
) -> tuple[str, Path]:
    """Generate content and save it to the content directory.

    Returns:
        Tuple of (generated_content, file_path).
    """
    _ensure_content_dir()

    content = generate(
        style_name=style_name,
        transcript=transcript,
        topic=topic,
        focus=focus,
        content_type=content_type,
        additional_instructions=additional_instructions,
        model=model,
        video_title=video_title,
    )

    # Save with metadata
    slug = _slugify(topic or video_title or "untitled")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"{timestamp}_{slug}.json"

    output = {
        "content": content,
        "metadata": {
            "style": style_name,
            "content_type": content_type,
            "topic": topic,
            "focus": focus,
            "video_title": video_title,
            "video_id": video_id,
            "generated_at": datetime.now().isoformat(),
        },
    }

    path = CONTENT_DIR / filename
    path.write_text(json.dumps(output, indent=2))
    return content, path


def _build_system_prompt(style_prompt: str, content_type: str) -> str:
    """Build the full system prompt combining style + content type instructions."""
    content_type_instructions = {
        "linkedin": (
            "You are writing a LinkedIn post. It should be a single post (not a thread). "
            "LinkedIn posts perform best when they have a strong hook in the first 1-2 lines "
            "(the part visible before 'see more'), use line breaks for readability, and end "
            "with a thought-provoking question or strong closing statement. Keep it under 3000 characters."
        ),
        "twitter": (
            "You are writing a single tweet. Max 280 characters. Make it punchy and standalone. "
            "It should be a complete thought that works on its own."
        ),
        "thread": (
            "You are writing a Twitter/X thread. Start with a hook tweet that makes people "
            "want to read the rest. Number each tweet (1/, 2/, etc.). Each tweet should be "
            "under 280 characters. End with a summary or call-to-action tweet. Aim for 5-12 tweets."
        ),
        "newsletter": (
            "You are writing a newsletter section or short essay. It should be 500-1500 words, "
            "well-structured with clear sections, and feel like a thoughtful piece of writing — "
            "not a summary. Open with a hook, develop the ideas, and close with a takeaway."
        ),
    }

    instructions = content_type_instructions.get(content_type, content_type_instructions["linkedin"])

    return f"""{style_prompt}

# CONTENT TYPE
{instructions}

# YOUR ROLE
You are a ghostwriter. Your job is to take source material (a transcript) and
turn it into original content that matches the writing style above. You are NOT
summarizing — you are extracting insights, stories, and ideas, then rewriting
them in the author's voice. The output should feel like the author watched/listened
to the source and wrote their own take on it.

Rules:
- NEVER mention "this podcast" or "this video" or "according to" — write as if
  these are YOUR insights that you happen to know
- NEVER use generic motivational language or cliché phrases
- NEVER start with "I just listened to..." or "In a recent episode..."
- Extract specific stories, numbers, quotes, and details — specificity is what
  makes content interesting
- If a focus area is provided, go deep on that. If not, pull the most compelling
  2-3 insights from the material
- The content should be ORIGINAL writing inspired by the source, not a reworded summary
"""


def _build_user_prompt(
    transcript: str,
    topic: str,
    focus: str,
    additional_instructions: str,
    video_title: str,
) -> str:
    """Build the user message with the transcript and directions."""
    parts = []

    if video_title:
        parts.append(f"Source: {video_title}")

    if topic:
        parts.append(f"Topic: {topic}")

    if focus:
        parts.append(f"Focus: {focus}")
    else:
        parts.append("Focus: Extract the most compelling insights, stories, or lessons from this material.")

    if additional_instructions:
        parts.append(f"Additional instructions: {additional_instructions}")

    # Truncate very long transcripts to avoid token limits
    max_transcript_chars = 100_000
    if len(transcript) > max_transcript_chars:
        transcript = transcript[:max_transcript_chars] + "\n\n[Transcript truncated for length]"

    parts.append(f"\n--- TRANSCRIPT ---\n{transcript}\n--- END TRANSCRIPT ---")
    parts.append("\nNow write the content. Output ONLY the finished post, nothing else.")

    return "\n\n".join(parts)


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    import re

    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:60].strip("-")
