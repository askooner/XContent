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


def _extract_key_material(client, transcript: str, topic: str, focus: str, video_title: str) -> str:
    """Step 1: Use Haiku to cheaply extract only the relevant parts of a long transcript."""
    extract_prompt = "Extract the most important quotes, stories, numbers, and insights"
    if topic:
        extract_prompt += f" related to: {topic}"
    if focus:
        extract_prompt += f" (focus on: {focus})"

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=2000,
        system=(
            "You are a research assistant. Your job is to extract the best raw material "
            "from a transcript for a content writer. Pull out:\n"
            "- The most powerful direct quotes (keep them exact)\n"
            "- Specific stories, anecdotes, and examples\n"
            "- Interesting numbers, facts, and data points\n"
            "- Key insights and frameworks\n\n"
            "Output ONLY the extracted material. No commentary. No summaries. "
            "Just the raw gold — quotes and facts, organized by theme."
        ),
        messages=[{"role": "user", "content": (
            f"Source: {video_title}\n\n{extract_prompt}\n\n"
            f"--- TRANSCRIPT ---\n{transcript}\n--- END TRANSCRIPT ---"
        )}],
    )
    return response.content[0].text


def extract_ideas(transcript: str, video_title: str = "", num_ideas: int = 5) -> list[dict]:
    """Extract multiple distinct post ideas from a single transcript.

    Returns a list of dicts with 'title', 'angle', and 'key_quotes' for each idea.
    This is the first step of batch mode — one cheap Haiku call to mine the whole video.
    """
    client = _get_anthropic_client()

    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=3000,
        system=(
            "You are a content strategist. Your job is to extract MULTIPLE distinct, "
            "standalone post ideas from a single transcript. Each idea should be a "
            "different topic, story, or insight — not variations of the same thing.\n\n"
            "For each idea, provide:\n"
            "1. A short title (what the post would be about)\n"
            "2. The angle/hook (why this is interesting)\n"
            "3. The key quotes and facts from the transcript that support this post\n\n"
            "Output as JSON array. Example:\n"
            "[\n"
            '  {"title": "Bezos on why he reads customer complaint emails", '
            '"angle": "The CEO of a trillion-dollar company still reads raw customer emails — here\'s why", '
            '"key_material": "Direct quotes and specific facts from the transcript..."},\n'
            "  ...\n"
            "]\n\n"
            "Rules:\n"
            "- Each idea must be DIFFERENT enough to be its own standalone post\n"
            "- Include the actual quotes and specifics, not just summaries\n"
            "- Focus on stories, contrarian takes, surprising facts, and frameworks\n"
            "- Skip generic/obvious insights — only the stuff that would stop someone scrolling"
        ),
        messages=[{"role": "user", "content": (
            f"Source: {video_title}\n\n"
            f"Extract {num_ideas} distinct post ideas from this transcript.\n\n"
            f"--- TRANSCRIPT ---\n{transcript}\n--- END TRANSCRIPT ---"
        )}],
    )

    # Parse the JSON response
    text = response.content[0].text
    # Handle cases where the model wraps in ```json
    if "```json" in text:
        text = text.split("```json")[1].split("```")[0]
    elif "```" in text:
        text = text.split("```")[1].split("```")[0]

    try:
        ideas = json.loads(text)
    except json.JSONDecodeError:
        # If JSON parsing fails, try to salvage
        import re
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if match:
            ideas = json.loads(match.group())
        else:
            raise ValueError("Could not parse ideas from the transcript. Try again.")

    return ideas


def generate_batch(
    style_name: str,
    transcript: str,
    content_type: str = "insights",
    model: str | None = None,
    video_title: str = "",
    video_id: str = "",
    num_posts: int = 5,
    additional_instructions: str = "",
) -> list[tuple[str, Path]]:
    """Generate multiple posts from a single transcript.

    Step 1: Extract N distinct ideas (one cheap Haiku call)
    Step 2: Generate a post for each idea (N cheap Haiku calls)

    Returns list of (content, file_path) tuples.
    """
    from .style_manager import build_style_prompt

    _ensure_content_dir()
    client = _get_anthropic_client()
    model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # Step 1: Extract ideas
    ideas = extract_ideas(transcript, video_title, num_ideas=num_posts)

    # Step 2: Generate a post for each idea
    style_prompt = build_style_prompt(style_name)
    system_prompt = _build_system_prompt(style_prompt, content_type)
    results = []

    for i, idea in enumerate(ideas):
        title = idea.get("title", f"idea-{i+1}")
        key_material = idea.get("key_material", idea.get("key_quotes", ""))
        angle = idea.get("angle", "")

        user_prompt = _build_user_prompt(
            transcript=key_material,
            topic=title,
            focus=angle,
            additional_instructions=additional_instructions,
            video_title=video_title,
        )

        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )

        content = response.content[0].text

        # Save each post
        slug = _slugify(title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{timestamp}_{slug}"

        txt_path = CONTENT_DIR / f"{base}.txt"
        txt_path.write_text(content)

        meta = {
            "style": style_name,
            "content_type": content_type,
            "topic": title,
            "focus": angle,
            "video_title": video_title,
            "video_id": video_id,
            "batch_index": i + 1,
            "batch_total": len(ideas),
            "generated_at": datetime.now().isoformat(),
        }
        meta_path = CONTENT_DIR / f"{base}.meta.json"
        meta_path.write_text(json.dumps(meta, indent=2))

        results.append((content, txt_path))

    return results


def generate(
    style_name: str,
    transcript: str,
    topic: str = "",
    focus: str = "",
    content_type: str = "insights",
    additional_instructions: str = "",
    model: str | None = None,
    video_title: str = "",
) -> str:
    """Generate content in your style from a transcript.

    For long transcripts (>15K chars), uses a two-step process:
    1. Haiku cheaply extracts the relevant quotes/stories/facts
    2. The writing model generates the post from the compressed material

    This cuts costs by ~80% on long transcripts.
    """
    from .style_manager import build_style_prompt

    client = _get_anthropic_client()
    model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

    # For long transcripts, extract key material first (cheap step)
    if len(transcript) > 15_000:
        transcript = _extract_key_material(client, transcript, topic, focus, video_title)

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

    # Save as plain text (easy to copy/share) + metadata sidecar
    slug = _slugify(topic or video_title or "untitled")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{timestamp}_{slug}"

    # Plain text file — just the post, nothing else
    txt_path = CONTENT_DIR / f"{base}.txt"
    txt_path.write_text(content)

    # Metadata sidecar
    meta = {
        "style": style_name,
        "content_type": content_type,
        "topic": topic,
        "focus": focus,
        "video_title": video_title,
        "video_id": video_id,
        "generated_at": datetime.now().isoformat(),
    }
    meta_path = CONTENT_DIR / f"{base}.meta.json"
    meta_path.write_text(json.dumps(meta, indent=2))

    return content, txt_path


def _build_system_prompt(style_prompt: str, content_type: str) -> str:
    """Build the full system prompt combining style + content type instructions."""
    content_type_instructions = {
        "insights": (
            "You are writing an INSIGHTS post. Format:\n"
            "- Open with '[Person], [title/role], on [specific topic]:'\n"
            "- Alternate between direct quotes from the source and your short commentary/analysis\n"
            "- Use lots of line breaks — every sentence or two gets its own paragraph\n"
            "- Weave a narrative thread: set up the context, build the insight, deliver the payoff\n"
            "- End with a punchy 1-2 line takeaway (often after 'The result?' or similar)\n"
            "- Use quotation marks for direct quotes from the person\n"
            "- Keep commentary sharp and brief — let the quotes do the heavy lifting\n"
            "- This is a Twitter/X post, keep it concise but complete"
        ),
        "essays": (
            "You are writing an ESSAY post. Format:\n"
            "- Open with a title or quote attribution in quotes (e.g. '\"Don't be a Career\" by Steve Jobs')\n"
            "- Present the person's words and ideas in flowing, thoughtful paragraphs\n"
            "- This is more curated excerpt than commentary — let the source material breathe\n"
            "- Minimal editorial voice — you're presenting their wisdom, not analyzing it\n"
            "- Use paragraph breaks between distinct ideas\n"
            "- The tone is reverent and thoughtful, like sharing something profound you found\n"
            "- This is a Twitter/X post, but longer-form — use the full character space"
        ),
        "transcripts": (
            "You are writing a TRANSCRIPT-STYLE post. Format:\n"
            "- Hook line at the top (e.g. 'Lessons Steve Jobs wanted to pass on.')\n"
            "- Short dramatic context line (e.g. 'Written right before he died.')\n"
            "- Then 'In his/her own words:'\n"
            "- Numbered sections (1. 2. 3. etc.) with ALL CAPS topic headers\n"
            "- Under each header, the person's direct quote on that topic\n"
            "- Like a curated listicle of the best moments from a talk or interview\n"
            "- Pick the 5-8 most powerful/interesting points from the source material\n"
            "- This is a Twitter/X post — structured and scannable"
        ),
        "quote-tweets": (
            "You are writing a QUOTE TWEET. Format:\n"
            "- Find the single most powerful quote from the source material\n"
            "- Put it in quotation marks\n"
            "- Line break, then '~ [Person's Full Name]'\n"
            "- That's it. No commentary, no analysis, no fluff\n"
            "- The quote should be punchy, memorable, and stand completely on its own\n"
            "- Max 2-3 sentences for the quote — shorter is better\n"
            "- This is designed to be posted as a quote tweet over someone else's post"
        ),
    }

    instructions = content_type_instructions.get(content_type, content_type_instructions["insights"])

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
