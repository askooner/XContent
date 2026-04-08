"""
Content Generator — Combine your style + source material to produce posts.

This is the assembly line: your style is the template, YouTube transcripts
are the raw material, and AI does the assembly.

Supports both Gemini (default) and Anthropic as backends.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

CONTENT_DIR = Path(__file__).resolve().parent.parent / "content"


def _ensure_content_dir():
    CONTENT_DIR.mkdir(parents=True, exist_ok=True)


# ── AI Backend ──────────────────────────────────────────────────────


def _use_gemini() -> bool:
    return os.getenv("AI_PROVIDER", "gemini").lower() == "gemini"


def _get_gemini_model(model_name: str | None = None, system: str = ""):
    import google.generativeai as genai

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY not set. Add it to your .env file."
        )
    genai.configure(api_key=api_key)
    model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-2.0-flash")
    return genai.GenerativeModel(model_name, system_instruction=system or None)


def _get_anthropic_client():
    import anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to your .env file.\n"
            "Get one at https://console.anthropic.com/settings/keys"
        )
    return anthropic.Anthropic(api_key=api_key)


def _call_ai(system: str, user_message: str, model: str | None = None, max_tokens: int = 4096) -> str:
    """Unified AI call — routes to Gemini or Anthropic based on config."""
    if _use_gemini():
        m = _get_gemini_model(model_name=model, system=system)
        response = m.generate_content(user_message)
        return response.text
    else:
        client = _get_anthropic_client()
        model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        response = client.messages.create(
            model=model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text


# ── Extraction & Generation ─────────────────────────────────────────


def _extract_key_material(transcript: str, topic: str, focus: str, video_title: str) -> str:
    """Step 1: Cheaply extract only the relevant parts of a long transcript."""
    extract_prompt = "Extract the most important quotes, stories, numbers, and insights"
    if topic:
        extract_prompt += f" related to: {topic}"
    if focus:
        extract_prompt += f" (focus on: {focus})"

    system = (
        "You are a research assistant. Your job is to extract the best raw material "
        "from a transcript for a content writer. Pull out:\n"
        "- The most powerful direct quotes (keep them exact)\n"
        "- Specific stories, anecdotes, and examples\n"
        "- Interesting numbers, facts, and data points\n"
        "- Key insights and frameworks\n\n"
        "Output ONLY the extracted material. No commentary. No summaries. "
        "Just the raw gold — quotes and facts, organized by theme."
    )

    user_msg = (
        f"Source: {video_title}\n\n{extract_prompt}\n\n"
        f"--- TRANSCRIPT ---\n{transcript}\n--- END TRANSCRIPT ---"
    )

    return _call_ai(system, user_msg, max_tokens=2000)


def extract_ideas(transcript: str, video_title: str = "", num_ideas: int = 0) -> list[dict]:
    """Extract multiple distinct post ideas from a single transcript.

    Args:
        num_ideas: Target number. 0 = auto-detect based on transcript length.

    Returns a list of dicts with 'title', 'angle', and 'key_material' for each idea.
    """
    # For very long transcripts, truncate to save costs
    extract_transcript = transcript
    if len(extract_transcript) > 80_000:
        extract_transcript = extract_transcript[:80_000]

    # Smart default based on transcript length
    if num_ideas <= 0:
        char_count = len(extract_transcript)
        if char_count < 15_000:
            num_ideas = 3
        elif char_count < 40_000:
            num_ideas = 5
        elif char_count < 70_000:
            num_ideas = 7
        else:
            num_ideas = 10

    system = (
        "You extract post ideas from transcripts. Output ONLY a valid JSON array.\n\n"
        "Each object must have exactly these 3 keys:\n"
        '- "title": short post title (specific, not generic)\n'
        '- "angle": the hook / why it\'s interesting (1 sentence)\n'
        '- "key_material": the actual quotes and facts to build the post from '
        "(include DIRECT QUOTES from the transcript, specific numbers, names, stories)\n\n"
        "Rules:\n"
        "- Each idea must be a DIFFERENT topic/story — not variations of the same thing\n"
        "- Include actual quotes from the transcript in key_material\n"
        "- Focus on stories, contrarian takes, surprising facts, frameworks\n"
        "- Skip generic insights like 'work hard' or 'be passionate' — only the stuff\n"
        "  that would make someone stop scrolling\n"
        "- Output ONLY the JSON array. No text before or after it. No markdown."
    )

    user_msg = (
        f"Source: {video_title}\n\n"
        f"Extract exactly {num_ideas} distinct post ideas.\n\n"
        f"--- TRANSCRIPT ---\n{extract_transcript}\n--- END TRANSCRIPT ---"
    )

    text = _call_ai(system, user_msg, max_tokens=6000).strip()

    # Strip markdown code fences if present
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    # Try parsing directly
    try:
        ideas = json.loads(text)
        if isinstance(ideas, list) and len(ideas) > 0:
            return ideas
    except json.JSONDecodeError:
        pass

    # Fallback: find the JSON array in the text
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            ideas = json.loads(match.group())
            if isinstance(ideas, list) and len(ideas) > 0:
                return ideas
        except json.JSONDecodeError:
            pass

    # Last resort: retry with stronger instruction
    retry_msg = (
        f"Source: {video_title}\n\n"
        f"Extract exactly {num_ideas} distinct post ideas from this transcript. "
        f"Each must have: title, angle, key_material (with direct quotes). "
        f"Output ONLY a JSON array. Start your response with [ and end with ].\n\n"
        f"--- TRANSCRIPT ---\n{extract_transcript[:40000]}\n--- END TRANSCRIPT ---"
    )

    text2 = _call_ai(system, retry_msg, max_tokens=6000).strip()

    if text2.startswith("```"):
        lines = text2.split("\n")
        text2 = "\n".join(lines[1:])
        if text2.rstrip().endswith("```"):
            text2 = text2.rstrip()[:-3]

    try:
        ideas = json.loads(text2)
        if isinstance(ideas, list) and len(ideas) > 0:
            return ideas
    except json.JSONDecodeError:
        pass

    raise ValueError(
        f"Could not extract ideas after 2 attempts. "
        f"Response started with: {text[:200]}"
    )


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

    Step 1: Extract N distinct ideas (one cheap call)
    Step 2: Generate a post for each idea (N cheap calls)

    Returns list of (content, file_path) tuples.
    """
    from .style_manager import build_style_prompt

    _ensure_content_dir()

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

        content = _call_ai(system_prompt, user_prompt, model=model)

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
    1. Cheaply extract the relevant quotes/stories/facts
    2. Generate the post from the compressed material
    """
    from .style_manager import build_style_prompt

    # For long transcripts, extract key material first (cheap step)
    if len(transcript) > 15_000:
        transcript = _extract_key_material(transcript, topic, focus, video_title)

    style_prompt = build_style_prompt(style_name)
    system_prompt = _build_system_prompt(style_prompt, content_type)
    user_prompt = _build_user_prompt(transcript, topic, focus, additional_instructions, video_title)

    return _call_ai(system_prompt, user_prompt, model=model)


def generate_and_save(
    style_name: str,
    transcript: str,
    topic: str = "",
    focus: str = "",
    content_type: str = "insights",
    additional_instructions: str = "",
    model: str | None = None,
    video_title: str = "",
    video_id: str = "",
) -> tuple[str, Path]:
    """Generate content and save it to the content directory."""
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

    slug = _slugify(topic or video_title or "untitled")
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = f"{timestamp}_{slug}"

    txt_path = CONTENT_DIR / f"{base}.txt"
    txt_path.write_text(content)

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
            "You are writing an INSIGHTS post for Twitter/X.\n"
            "- Pull a specific story, framework, or decision from the source material\n"
            "- Mix direct quotes with your own sharp commentary\n"
            "- Use lots of line breaks — short paragraphs, punchy rhythm\n"
            "- End with a strong takeaway or provocative closing line\n"
            "- VARY your openings — do NOT always start with '[Person] on [topic]'\n"
            "  Instead, try: a bold claim, a surprising stat, a question, a story hook,\n"
            "  a contrarian take, or drop straight into a quote\n"
            "- The hook (first 1-2 lines) must stop someone mid-scroll\n"
            "- Keep it concise but complete"
        ),
        "essays": (
            "You are writing an ESSAY post for Twitter/X.\n"
            "- Open with a title/attribution OR a thought-provoking framing\n"
            "- Present the person's words and ideas in flowing paragraphs\n"
            "- Let the source material breathe — minimal editorial voice\n"
            "- The tone is reverent and thoughtful\n"
            "- Use paragraph breaks between distinct ideas\n"
            "- VARY your openings — don't always use the same title format"
        ),
        "transcripts": (
            "You are writing a TRANSCRIPT-STYLE post for Twitter/X.\n"
            "- Hook line at the top that creates curiosity\n"
            "- Optional dramatic context line\n"
            "- Then 'In his/her own words:' or similar\n"
            "- Numbered sections with ALL CAPS topic headers\n"
            "- Under each header, the person's direct quote\n"
            "- Pick the 5-8 most powerful points from the source\n"
            "- VARY your hook — don't always use the same formula"
        ),
        "quote-tweets": (
            "You are writing a QUOTE TWEET.\n"
            "- Find the single most powerful quote from the source\n"
            "- Put it in quotation marks\n"
            "- Line break, then '~ [Person's Full Name]'\n"
            "- No commentary. The quote does all the work.\n"
            "- Max 2-3 sentences — shorter is better"
        ),
    }

    instructions = content_type_instructions.get(content_type, content_type_instructions["insights"])

    return f"""{style_prompt}

# CONTENT TYPE
{instructions}

# YOUR ROLE
You are a ghostwriter creating original Twitter/X content from source material.
You are NOT summarizing — you are finding the gold in a transcript and crafting
something that would stop someone mid-scroll.

CREATIVITY IS MANDATORY:
- Every post must feel FRESH and UNIQUE — never formulaic
- VARY your hooks — sometimes start with a bold claim, sometimes a quote,
  sometimes a story, sometimes a question, sometimes a surprising fact
- VARY your structure — don't follow the same pattern every time
- The examples in the style guide show the VOICE, not a rigid template
- Surprise the reader. Find unexpected angles. Be bold.

Rules:
- NEVER mention "this podcast" or "this video" or "according to"
- NEVER use generic motivational language or cliché phrases
- NEVER start with "I just listened to..." or "In a recent episode..."
- Extract specific stories, numbers, quotes, and details — specificity is what
  makes content interesting
- If a focus area is provided, go deep on that. If not, pull the most compelling
  insights from the material
- Write as if YOU are the author sharing things YOU know, not reporting on someone else
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

    max_transcript_chars = 100_000
    if len(transcript) > max_transcript_chars:
        transcript = transcript[:max_transcript_chars] + "\n\n[Transcript truncated for length]"

    parts.append(f"\n--- TRANSCRIPT ---\n{transcript}\n--- END TRANSCRIPT ---")
    parts.append("\nNow write the content. Output ONLY the finished post, nothing else.")

    return "\n\n".join(parts)


def _slugify(text: str) -> str:
    """Convert text to a filename-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[-\s]+", "-", text)
    return text[:60].strip("-")
