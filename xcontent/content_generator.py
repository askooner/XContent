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


def _get_library_context(client, topic: str, angle: str = "",
                         exclude_video_id: str = "", max_sources: int = 2) -> str:
    """Search the transcript library for material related to the current topic.

    Returns a block of text with relevant quotes/stories from OTHER transcripts
    that can be woven into the post for cross-founder connections.
    Returns empty string if library is empty or no matches found.
    """
    try:
        from .knowledge_base import search_transcripts, get_transcript_text
    except Exception:
        return ""

    search_terms = [topic]
    if angle:
        search_terms.append(angle)

    all_matches = []
    seen = set()
    if exclude_video_id:
        seen.add(exclude_video_id)

    for term in search_terms:
        try:
            matches = search_transcripts(term, limit=5)
        except Exception:
            continue
        for m in matches:
            if m["video_id"] not in seen:
                seen.add(m["video_id"])
                all_matches.append(m)

    if not all_matches:
        return ""

    top = all_matches[:max_sources]
    parts = []
    for match in top:
        full_text = get_transcript_text(match["video_id"])
        if not full_text:
            continue

        extract = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1000,
            system=(
                "Extract ONLY the parts of this transcript that relate to the "
                "topic below. Pull out specific verbatim quotes, stories, numbers. "
                "Keep quotes exact. If nothing relevant, output NOTHING_RELEVANT.\n\n"
                f"TOPIC: {topic}"
                + (f"\nANGLE: {angle}" if angle else "")
            ),
            messages=[{"role": "user", "content": full_text[:60000]}],
        )
        extracted = extract.content[0].text.strip()
        if extracted and "NOTHING_RELEVANT" not in extracted:
            parts.append(f"[From: {match['video_title']}]\n{extracted}")

    if not parts:
        return ""

    return (
        "\n\n--- RELATED MATERIAL FROM YOUR LIBRARY (use to weave cross-founder connections) ---\n"
        + "\n\n".join(parts)
        + "\n--- END RELATED MATERIAL ---"
    )


def _generate_with_quality_gate(
    client, model: str, system_prompt: str, user_prompt: str,
    content_type: str = "insights", max_attempts: int = 2,
) -> tuple[str, dict]:
    """Generate a post and run it through the quality gate.

    If the first attempt fails quality, regenerates with fix instructions.
    Returns (content, quality_result).
    """
    from .quality_scorer import score_post

    content = ""
    result = {"score": 0, "passed": False, "issues": []}

    for attempt in range(max_attempts):
        response = client.messages.create(
            model=model,
            max_tokens=4096,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        content = response.content[0].text
        result = score_post(content, content_type)

        if result["passed"]:
            return content, result

        if attempt < max_attempts - 1:
            fix_lines = "\n".join(f"- FIX: {issue}" for issue in result["issues"])
            user_prompt += (
                f"\n\nIMPORTANT — Your previous output failed quality checks. "
                f"Rewrite and fix these specific issues:\n{fix_lines}"
            )

    return content, result


def _extract_key_material(client, transcript: str, topic: str, focus: str, video_title: str) -> str:
    """Step 1: Use Haiku to cheaply extract only the relevant parts of a long transcript."""
    extract_prompt = "Extract the most important quotes, stories, numbers, and insights"
    if topic:
        extract_prompt += f" related to: {topic}"
    if focus:
        extract_prompt += f" (focus on: {focus})"

    response = client.messages.create(
        model="claude-sonnet-4-6",
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


def _load_rubric(client, style_name: str = "insights") -> str:
    """Analyze the user's real published posts to derive a scoring rubric.

    Instead of making up criteria, we look at what the user's actual best posts
    have in common and turn those patterns into checkable questions.
    Returns the rubric as a string for injection into scoring prompts.
    Caches to disk so we only regenerate when style examples change.
    """
    rubric_path = Path(__file__).resolve().parent.parent / "styles" / f"{style_name}.rubric.txt"

    try:
        from .style_manager import load_style
        style = load_style(style_name)
        examples = style.get("examples", [])
    except Exception:
        examples = []

    if not examples:
        return _default_rubric()

    # Check cache — rebuild if example count changed
    if rubric_path.exists():
        cached = rubric_path.read_text()
        header_line = cached.split("\n")[0] if cached else ""
        if header_line.startswith(f"# RUBRIC ({len(examples)} examples)"):
            return cached

    # Analyze the user's real posts to derive the rubric
    posts_text = ""
    for i, ex in enumerate(examples[:10], 1):
        posts_text += f"--- POST {i} ---\n{ex}\n\n"

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=3000,
        system=(
            "You are analyzing a set of published Twitter/X posts to reverse-engineer "
            "what makes them work. Your job is to produce a CONCRETE SCORING RUBRIC "
            "that can be used to evaluate whether a new idea is worth writing about.\n\n"
            "Study these posts carefully and answer:\n"
            "1. What do these posts have in common? (Be specific — not 'they're good')\n"
            "2. What concrete, checkable elements appear in most of them?\n"
            "3. What makes the IDEAS behind these posts work (not the writing)?\n\n"
            "Then produce a rubric of 5-7 YES/NO questions where each question tests "
            "a specific, verifiable quality. Each question must be answerable by looking "
            "at the raw idea and its source material — no subjectivity.\n\n"
            "Bad question: 'Is this surprising?' (subjective, everyone answers yes)\n"
            "Good question: 'Does the idea contain a specific decision where the founder "
            "chose the opposite of what experts/conventional wisdom recommended?'\n\n"
            "Bad question: 'Is this engaging?' (meaningless)\n"
            "Good question: 'Can you point to an exact quote from the source that would "
            "work as a standalone tweet?'\n\n"
            "Format: output ONLY the rubric as numbered questions, one per line.\n"
            "Before each question, write the PATTERN you observed that led to it.\n"
            "Format each entry as:\n"
            "PATTERN: [what you observed]\n"
            "QUESTION: [yes/no question to check for it]\n"
            "WEIGHT: [how many of the example posts had this — e.g. 8/10]\n\n"
            "Then at the end, write:\n"
            "THRESHOLD: An idea needs YES on at least N of these questions to be worth posting.\n\n"
            "Be ruthlessly specific. These questions will be used to filter ideas automatically."
        ),
        messages=[{"role": "user", "content": (
            f"Here are {len(examples[:10])} real published posts from the Founder Mode account. "
            f"Analyze what makes these ideas work and produce the scoring rubric.\n\n{posts_text}"
        )}],
    )

    rubric = f"# RUBRIC ({len(examples)} examples)\n\n{response.content[0].text}"

    try:
        rubric_path.parent.mkdir(parents=True, exist_ok=True)
        rubric_path.write_text(rubric)
    except Exception:
        pass

    return rubric


def _default_rubric() -> str:
    """Fallback rubric when no published posts exist yet."""
    return (
        "# DEFAULT RUBRIC (no published posts to analyze)\n\n"
        "Score each idea YES/NO on these questions:\n"
        "1. Does the idea name a SPECIFIC person and a SPECIFIC decision/action they took?\n"
        "2. Does the key_material contain at least 2 VERBATIM quotes from the transcript?\n"
        "3. Does the idea contain a specific number, dollar amount, date, or measurable outcome?\n"
        "4. Is there a clear TENSION — conventional wisdom vs what actually happened?\n"
        "5. Could you NOT write this post about a different founder and have it still work? "
        "(If yes, it's specific enough. If no, it's too generic.)\n"
        "6. Would someone who already follows business accounts learn something NEW from this?\n\n"
        "THRESHOLD: An idea needs YES on at least 4 of 6 to be worth posting."
    )


def extract_ideas(transcript: str, video_title: str = "", num_ideas: int = 0,
                   style_name: str = "insights") -> list[dict]:
    """Three-pass idea extraction: scan wide, score against rubric, return top ranked.

    Pass 1 — Derive rubric from user's real posts (cached).
    Pass 2 — Cast wide net: find every possible moment (up to 10).
    Pass 3 — Score each idea against the rubric, return top N that pass.
    """
    client = _get_anthropic_client()

    extract_transcript = transcript
    if len(extract_transcript) > 80_000:
        extract_transcript = extract_transcript[:80_000]

    if num_ideas <= 0:
        num_ideas = 3

    # ── Pass 1: Get the scoring rubric (derived from user's real posts) ──
    rubric = _load_rubric(client, style_name)

    # ── Pass 2: Cast wide net — find ALL possible moments ──
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=8000,
        system=(
            "You are the editorial brain for Founder Mode, a Twitter account about founders "
            "and entrepreneurship.\n\n"
            "WIDE SCAN: Find EVERY possible post-worthy moment in this transcript.\n"
            "Cast a wide net — up to 10 distinct moments. We score and filter separately.\n\n"
            "Output ONLY a valid JSON array. Each object has exactly 3 keys:\n"
            '- "title": specific post title (name the founder and the specific thing)\n'
            '- "angle": the hook in 1 sentence — why this would stop someone scrolling\n'
            '- "key_material": VERBATIM quotes from the transcript (2-3+ direct quotes), '
            "specific numbers, names, stories — the raw evidence\n\n"
            "What counts as a moment:\n"
            "- A specific founder DECISION that went against conventional wisdom\n"
            "- The exact moment something almost failed and what they did differently\n"
            "- A number or fact that reframes how you think about a business\n"
            "- A mental model from a builder that's immediately actionable\n"
            "- A direct quote so good it could stand on its own\n"
            "- A surprising origin story, pivot, or near-death experience\n"
            "- A contrarian take backed by real results\n\n"
            "SKIP: Generic motivation, politics, health, vague observations without evidence.\n\n"
            "Output ONLY the JSON array. No markdown, no text before or after."
        ),
        messages=[{"role": "user", "content": (
            f"Source: {video_title}\n\n"
            f"Find every possible post-worthy moment.\n\n"
            f"--- TRANSCRIPT ---\n{extract_transcript}\n--- END TRANSCRIPT ---"
        )}],
    )

    raw_ideas = _parse_json_array(response.content[0].text)
    if not raw_ideas:
        return []

    # ── Pass 3: Score each idea against the rubric ──
    ideas_json = json.dumps(raw_ideas, indent=2)

    score_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=6000,
        system=(
            "You are a scoring engine. You evaluate post ideas against a RUBRIC derived "
            "from the account's own published posts.\n\n"
            "THE RUBRIC (derived from analyzing the account's best posts):\n"
            f"{rubric}\n\n"
            "For EACH idea, answer EVERY rubric question YES or NO based on what's "
            "actually in the idea's title, angle, and key_material. Do NOT guess or "
            "assume — if the evidence isn't in the key_material, the answer is NO.\n\n"
            "Output ONLY a valid JSON array with one object per idea:\n"
            '- "index": 0-based index of the idea\n'
            '- "yes_count": how many rubric questions got YES\n'
            '- "total_questions": total rubric questions\n'
            '- "answers": object mapping question number to true/false\n'
            '- "passed": true if yes_count meets the threshold from the rubric\n'
            '- "reason": 1 sentence — which questions failed and why\n\n'
            "Be STRICT. Only answer YES when the evidence is clearly present.\n"
            "Output ONLY the JSON array. No markdown."
        ),
        messages=[{"role": "user", "content": (
            f"Score each of these {len(raw_ideas)} ideas against the rubric:\n\n{ideas_json}"
        )}],
    )

    scores = _parse_json_array(score_response.content[0].text)
    if not scores:
        return raw_ideas[:num_ideas]

    # Merge scores and sort by yes_count descending
    scored_ideas = []
    for s in scores:
        idx = s.get("index", -1)
        if 0 <= idx < len(raw_ideas):
            idea = raw_ideas[idx].copy()
            yes_count = s.get("yes_count", 0)
            total = s.get("total_questions", 1)
            idea["story_score"] = round(10 * yes_count / max(total, 1))
            idea["rubric_pass"] = s.get("passed", False)
            idea["yes_count"] = yes_count
            idea["total_questions"] = total
            idea["score_reason"] = s.get("reason", "")
            idea["rubric_answers"] = s.get("answers", {})
            scored_ideas.append(idea)

    scored_ideas.sort(key=lambda x: x.get("yes_count", 0), reverse=True)

    # Return ideas that passed the rubric threshold, capped at num_ideas
    passed = [i for i in scored_ideas if i.get("rubric_pass", False)]
    if not passed:
        # If nothing passes, return best one if it got at least half the questions
        if scored_ideas:
            best = scored_ideas[0]
            total = best.get("total_questions", 6)
            if best.get("yes_count", 0) >= total / 2:
                return scored_ideas[:1]
        return []

    return passed[:num_ideas]


def _parse_json_array(text: str) -> list[dict]:
    """Parse a JSON array from model output, handling markdown fences."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    try:
        result = json.loads(text)
        if isinstance(result, list):
            return result
    except json.JSONDecodeError:
        pass

    import re
    match = re.search(r'\[[\s\S]*\]', text)
    if match:
        try:
            result = json.loads(match.group())
            if isinstance(result, list):
                return result
        except json.JSONDecodeError:
            pass

    return []


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
    model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # Step 1: Extract ideas
    ideas = extract_ideas(transcript, video_title, num_ideas=num_posts)

    # Step 2: Generate a post for each idea
    style_prompt = build_style_prompt(style_name)
    system_prompt = _build_system_prompt(style_prompt, content_type, style_name)
    results = []

    for i, idea in enumerate(ideas):
        title = idea.get("title", f"idea-{i+1}")
        key_material = idea.get("key_material", idea.get("key_quotes", ""))
        angle = idea.get("angle", "")

        # Search the library for related material from OTHER transcripts
        library_context = _get_library_context(client, title, angle, exclude_video_id=video_id)

        source_material = key_material
        if library_context:
            source_material = key_material + "\n" + library_context

        user_prompt = _build_user_prompt(
            transcript=source_material,
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

        # Persist to the knowledge base so it's retrievable + searchable later
        try:
            from .knowledge_base import save_post
            save_post(
                style=style_name,
                content=content,
                content_type=content_type,
                topic=title,
                focus=angle,
                video_id=video_id,
                video_title=video_title,
                command="batch",
            )
        except Exception:
            pass

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
    video_id: str = "",
) -> str:
    """Generate content in your style from a transcript.

    For long transcripts (>15K chars), uses a two-step process:
    1. Haiku cheaply extracts the relevant quotes/stories/facts
    2. The writing model generates the post from the compressed material

    This cuts costs by ~80% on long transcripts.
    """
    from .style_manager import build_style_prompt

    client = _get_anthropic_client()
    model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # For long transcripts, extract key material first (cheap step)
    if len(transcript) > 15_000:
        transcript = _extract_key_material(client, transcript, topic, focus, video_title)

    # Search the library for related material from OTHER transcripts
    library_context = _get_library_context(client, topic or video_title, focus, exclude_video_id=video_id)
    if library_context:
        transcript = transcript + "\n" + library_context

    style_prompt = build_style_prompt(style_name)

    system_prompt = _build_system_prompt(style_prompt, content_type, style_name)
    user_prompt = _build_user_prompt(transcript, topic, focus, additional_instructions, video_title)

    response = client.messages.create(
        model=model,
        max_tokens=4096,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}],
    )

    content = response.content[0].text
    return content


def generate_quote_reply(
    tweet_text: str,
    style_name: str,
    model: str | None = None,
    additional_instructions: str = "",
) -> tuple[str, list[dict]]:
    """Generate a quote-tweet reply that ties the original tweet to a real entrepreneur story.

    Steps:
    1. Extract the core idea/theme from the tweet
    2. Search the transcript library for related stories, quotes, facts
    3. Generate a quote reply grounded in REAL material from the library

    Returns:
        Tuple of (generated reply text, list of source transcripts used)
    """
    from .knowledge_base import search_transcripts, get_transcript_text
    from .style_manager import build_style_prompt

    client = _get_anthropic_client()
    model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # Step 1: Extract keywords/themes from the tweet for library search
    theme_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=200,
        system=(
            "Extract 3-5 search keywords from this tweet that would help find "
            "related stories in a library of entrepreneur/business transcripts. "
            "Output ONLY the keywords, one per line. No commentary."
        ),
        messages=[{"role": "user", "content": tweet_text}],
    )
    keywords = theme_response.content[0].text.strip().split("\n")
    keywords = [k.strip() for k in keywords if k.strip()]

    # Step 2: Search library for related material
    all_matches = []
    seen_videos = set()
    for keyword in keywords:
        matches = search_transcripts(keyword, limit=5)
        for m in matches:
            if m["video_id"] not in seen_videos:
                seen_videos.add(m["video_id"])
                all_matches.append(m)

    if not all_matches:
        # No library matches — generate without transcript backing
        return _generate_quote_reply_no_library(
            client, tweet_text, style_name, model, additional_instructions
        ), []

    # Step 3: Pull relevant excerpts from top matches (up to 3 transcripts)
    top_matches = all_matches[:3]
    source_material = []
    for match in top_matches:
        full_text = get_transcript_text(match["video_id"])
        if not full_text:
            continue

        # Extract relevant parts only (cheap call)
        extract = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1500,
            system=(
                "Extract ONLY the parts of this transcript that relate to the tweet below. "
                "Pull out specific quotes, stories, numbers, and facts. "
                "If nothing is relevant, say NOTHING_RELEVANT.\n\n"
                f"TWEET: {tweet_text}"
            ),
            messages=[{"role": "user", "content": full_text[:60000]}],
        )
        extracted = extract.content[0].text.strip()
        if "NOTHING_RELEVANT" not in extracted:
            source_material.append({
                "video_title": match["video_title"],
                "channel": match.get("channel", ""),
                "material": extracted,
            })

    if not source_material:
        return _generate_quote_reply_no_library(
            client, tweet_text, style_name, model, additional_instructions
        ), []

    # Step 4: Generate the quote reply grounded in real material
    style_prompt = build_style_prompt(style_name)

    sources_text = ""
    for s in source_material:
        sources_text += f"\n--- Source: {s['video_title']} ---\n{s['material']}\n"

    system = f"""{style_prompt}

# YOUR TASK
You are writing a QUOTE TWEET reply to someone else's tweet.

CRITICAL RULES:
- Your reply MUST be grounded in the SOURCE MATERIAL provided below
- Use REAL quotes, stories, numbers, and facts from the sources — NEVER make things up
- Every claim must be traceable to the source material
- Connect the original tweet's idea to a specific entrepreneur story/quote
- Keep it punchy — this is a quote tweet, not an essay
- 3-8 lines max. Short paragraphs, strong rhythm.
- Don't start with "This reminds me of..." or "Great point..."
- Jump straight into the story/quote that connects
- End with a sharp line that ties it back to the original tweet's theme
- Write as if YOU are sharing something you know, not citing a source

FACTUAL ACCURACY IS NON-NEGOTIABLE:
- Only use quotes that appear VERBATIM in the source material
- Only reference stories/events that are explicitly described in the sources
- If you're not 100% sure something is in the source material, don't include it
- Attribute quotes to the correct person
"""

    user_msg = f"""ORIGINAL TWEET:
{tweet_text}

SOURCE MATERIAL (use ONLY facts from here):
{sources_text}

{f"Additional instructions: {additional_instructions}" if additional_instructions else ""}

Write a quote tweet reply. Output ONLY the finished reply, nothing else."""

    response = client.messages.create(
        model=model,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )

    return response.content[0].text, top_matches


def generate_story(
    topic: str,
    style_name: str,
    model: str | None = None,
    additional_instructions: str = "",
    max_sources: int = 5,
) -> tuple[str, list[dict]]:
    """Cross-library narrative synthesis.

    Mines the ENTIRE transcript library for anything related to the topic,
    extracts the real facts/quotes/stories from each matching source, and
    weaves them into one original narrative post (Steve Jobs/Japan style).

    Every claim must be grounded in the source material — no inventions.

    Returns:
        (generated_post, list of source transcripts used)
    """
    from .knowledge_base import search_transcripts, get_transcript_text
    from .style_manager import build_style_prompt

    client = _get_anthropic_client()
    model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    # Step 1: broaden the topic into a handful of search terms the FTS index
    # can actually hit — entity names, related concepts, synonyms.
    keyword_response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        system=(
            "You are a research assistant. Given a topic, produce 4-7 search "
            "terms that would find related material in a library of transcripts "
            "from entrepreneur/business podcasts. Include specific names, "
            "companies, related concepts, and synonyms. One term per line. "
            "No commentary."
        ),
        messages=[{"role": "user", "content": topic}],
    )
    keywords = [k.strip() for k in keyword_response.content[0].text.split("\n") if k.strip()]
    if topic not in keywords:
        keywords.insert(0, topic)

    # Step 2: FTS the library, dedupe by video.
    all_matches: list[dict] = []
    seen_videos: set[str] = set()
    for keyword in keywords:
        try:
            matches = search_transcripts(keyword, limit=5)
        except Exception:
            continue
        for m in matches:
            if m["video_id"] not in seen_videos:
                seen_videos.add(m["video_id"])
                all_matches.append(m)

    if not all_matches:
        raise ValueError(
            f"No library material found for topic: '{topic}'. "
            f"Add transcripts first with 'xcontent write --video ...' or "
            f"'xcontent batch --video ...'."
        )

    # Step 3: pull the most relevant bits from the top N matches.
    top_matches = all_matches[:max_sources]
    source_material: list[dict] = []
    for match in top_matches:
        full_text = get_transcript_text(match["video_id"])
        if not full_text:
            continue

        extract = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1800,
            system=(
                "Extract ONLY the parts of this transcript that relate to the "
                "topic below. Pull out specific quotes, stories, numbers, dates, "
                "people, and facts. Keep quotes VERBATIM. If nothing relevant, "
                "output NOTHING_RELEVANT.\n\n"
                f"TOPIC: {topic}"
            ),
            messages=[{"role": "user", "content": full_text[:70000]}],
        )
        extracted = extract.content[0].text.strip()
        if extracted and "NOTHING_RELEVANT" not in extracted:
            source_material.append({
                "video_title": match["video_title"],
                "channel": match.get("channel", ""),
                "material": extracted,
            })

    if not source_material:
        raise ValueError(
            f"Found matching transcripts but no relevant material for '{topic}'. "
            f"Try a more specific topic or add more transcripts."
        )

    # Step 4: weave the extracted material into a narrative post.
    style_prompt = build_style_prompt(style_name)

    sources_text = ""
    for s in source_material:
        sources_text += f"\n--- Source: {s['video_title']} ({s['channel']}) ---\n{s['material']}\n"

    system = f"""{style_prompt}

# YOUR TASK
You are synthesizing an ORIGINAL narrative post from multiple real sources.

This is NOT a summary. This is storytelling. Weave the facts, quotes, and
moments from the source material into one cohesive story that feels like
it came from someone who knows the subject deeply.

STRUCTURE:
- Open with a specific, surprising hook — a scene, a line, a number.
  Never open with "In [year]..." or "Many people know..."
- Build the story in short punchy paragraphs
- Use the real quotes, names, numbers, dates from the source material
- Every beat should earn its place — no filler, no connective tissue that
  adds nothing
- End with a sharp final line that lands the meaning

FACTUAL ACCURACY IS NON-NEGOTIABLE:
- Every quote must appear VERBATIM in the source material
- Every name, number, date, and event must be traceable to a source
- Never invent dialogue, never embellish details
- If two sources disagree, use the one you're more certain of and drop the other
- If you can't make the story work with only the real material, make it shorter
  rather than inventing anything

VOICE:
- Write as if YOU know this. Don't cite sources, don't say "according to".
- The reader should feel like an insider is telling them a story they hadn't heard.
"""

    user_msg = f"""TOPIC: {topic}

SOURCE MATERIAL (use ONLY facts from here):
{sources_text}

{f"Additional instructions: {additional_instructions}" if additional_instructions else ""}

Write the narrative post. Output ONLY the finished post, nothing else."""

    response = client.messages.create(
        model=model,
        max_tokens=2000,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )

    return response.content[0].text, top_matches


def _generate_quote_reply_no_library(
    client, tweet_text: str, style_name: str, model: str,
    additional_instructions: str = "",
) -> str:
    """Fallback: generate a quote reply without library material.
    Only extends the idea — no entrepreneur stories (to stay factual).
    """
    from .style_manager import build_style_prompt
    style_prompt = build_style_prompt(style_name)

    system = f"""{style_prompt}

# YOUR TASK
You are writing a QUOTE TWEET reply to someone else's tweet.

IMPORTANT: You have no source material for this reply, so:
- Do NOT reference specific entrepreneurs, quotes, or stories unless you are 100% certain they are real
- Instead, EXTEND the idea — add your own sharp take, a framework, or a provocative angle
- Keep it punchy — 3-8 lines max
- Don't start with "This reminds me of..." or "Great point..."
- Jump straight into your take
"""

    user_msg = f"""ORIGINAL TWEET:
{tweet_text}

{f"Additional instructions: {additional_instructions}" if additional_instructions else ""}

Write a quote tweet reply. Output ONLY the finished reply, nothing else."""

    response = client.messages.create(
        model=model,
        max_tokens=1000,
        system=system,
        messages=[{"role": "user", "content": user_msg}],
    )

    return response.content[0].text


_FOUNDER_KEYWORDS = {
    "founder", "ceo", "startup", "company", "business", "entrepreneur",
    "venture", "capital", "investor", "build", "scale", "growth", "revenue",
    "product", "market", "strategy", "leadership", "management", "hire",
    "culture", "innovation", "disruption", "acquisition", "ipo", "funding",
    "valuation", "profit", "customer", "saas", "software", "tech",
    "technology", "ai", "artificial intelligence", "machine learning",
    "engineer", "silicon valley", "amazon", "apple", "google", "meta",
    "microsoft", "tesla", "spacex", "stripe", "coinbase", "nvidia",
    "manufacturing", "supply chain", "operations", "decision", "compete",
    "moat", "monopoly", "network effect", "platform", "marketplace",
}


def _filter_on_topic(transcripts: list[dict]) -> list[dict]:
    """Filter transcripts to founder/business/tech topics.

    Core channels pass through. Mixed channels are filtered by title keywords.
    """
    channels_path = Path(__file__).resolve().parent.parent / "channels.json"
    mixed_channels: set[str] = set()
    if channels_path.exists():
        import json as _json
        for ch in _json.loads(channels_path.read_text()):
            if ch.get("focus") == "mixed":
                mixed_channels.add(ch["name"])
                mixed_channels.add(ch.get("handle", ""))

    result = []
    for t in transcripts:
        channel = t.get("channel", "")
        if channel not in mixed_channels:
            result.append(t)
            continue
        title_lower = t.get("video_title", "").lower()
        if any(kw in title_lower for kw in _FOUNDER_KEYWORDS):
            result.append(t)
    return result


def _score_story_value(client, video_title: str, transcript_excerpt: str,
                       recent_topics: list[str], style_name: str = "insights") -> dict | None:
    """Score whether a transcript has a moment worth posting about.

    Uses the rubric derived from the user's own posts to evaluate.
    Returns dict with {title, angle, format, score, yes_count} if it passes, else None.
    """
    rubric = _load_rubric(client, style_name)

    recent_context = ""
    if recent_topics:
        recent_context = (
            "\n\nPOSTS FROM THE LAST 7 DAYS (do NOT repeat these topics/angles):\n"
            + "\n".join(f"- {t}" for t in recent_topics[:20])
        )

    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2000,
        system=(
            "You are the editorial brain for Founder Mode, a Twitter account about founders, "
            "entrepreneurship, business building, and technology.\n\n"
            "Your job: read a transcript and find the SINGLE BEST moment worth a post, "
            "then evaluate it against the scoring rubric.\n\n"
            "SCORING RUBRIC (derived from the account's own published posts):\n"
            f"{rubric}\n\n"
            "SKIP these entirely:\n"
            "- Generic motivation without a specific story\n"
            "- Politics, health, geopolitics\n"
            "- Topics already covered in recent posts\n\n"
            "Also decide the BEST FORMAT for this moment:\n"
            "- 'insights': a narrative post with hook, tension, turn, evidence, closing\n"
            "- 'quote-tweets': a single devastating direct quote + attribution\n"
            "- 'essays': a longer reflective piece letting the founder's words breathe\n"
            "- 'transcripts': numbered key points from the founder's own words\n\n"
            "Output ONLY valid JSON with these keys:\n"
            '- "title": specific post title naming the founder and the specific thing\n'
            '- "angle": the hook — why this would stop someone scrolling\n'
            '- "format": best content format\n'
            '- "rubric_answers": object mapping each rubric question number to true/false\n'
            '- "yes_count": how many rubric questions got YES\n'
            '- "total_questions": total rubric questions\n'
            '- "passed": true if meets rubric threshold\n'
            '- "reason": 1 sentence explaining the evaluation\n\n'
            "If NOTHING in the transcript meets the rubric, return:\n"
            '{\"title\": \"\", \"angle\": \"\", \"format\": \"insights\", \"passed\": false, '
            '\"yes_count\": 0, \"total_questions\": 0, \"reason\": \"nothing worth posting\"}\n\n'
            "Output ONLY the JSON. No markdown."
        ),
        messages=[{"role": "user", "content": (
            f"Source: {video_title}\n"
            f"{recent_context}\n\n"
            f"--- TRANSCRIPT ---\n{transcript_excerpt}\n--- END TRANSCRIPT ---"
        )}],
    )

    text = response.content[0].text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.rstrip().endswith("```"):
            text = text.rstrip()[:-3]

    try:
        result = json.loads(text)
        if result.get("passed", False) and result.get("title"):
            yes = result.get("yes_count", 0)
            total = result.get("total_questions", 1)
            result["score"] = round(10 * yes / max(total, 1))
            return result
    except json.JSONDecodeError:
        pass

    return None


def _generate_from_full_transcript(
    client, model: str, style_name: str, transcript: str,
    video_title: str, video_id: str, story: dict,
    additional_instructions: str = "",
) -> tuple[str, dict]:
    """Generate a post from a FULL transcript — the model finds the moment itself."""
    from .style_manager import build_style_prompt

    content_type = story.get("format", "insights")
    style_prompt = build_style_prompt(style_name)
    system_prompt = _build_system_prompt(style_prompt, content_type, style_name)

    max_chars = 90_000
    if len(transcript) > max_chars:
        transcript = transcript[:max_chars]

    library_context = _get_library_context(
        client, story.get("title", ""), story.get("angle", ""),
        exclude_video_id=video_id
    )

    user_content = (
        f"Source: {video_title}\n\n"
        f"YOUR EDITORIAL BRIEF:\n"
        f"Title: {story['title']}\n"
        f"Angle: {story['angle']}\n"
        f"Format: {content_type}\n\n"
        f"Find the exact quotes, numbers, and story beats in the transcript below "
        f"that support this angle. Use VERBATIM quotes — they are the backbone.\n\n"
    )

    if library_context:
        user_content += library_context + "\n\n"

    if additional_instructions:
        user_content += f"Additional instructions: {additional_instructions}\n\n"

    user_content += (
        f"--- FULL TRANSCRIPT ---\n{transcript}\n--- END TRANSCRIPT ---\n\n"
        f"Now write the post. Output ONLY the finished post, nothing else."
    )

    content, quality = _generate_with_quality_gate(
        client, model, system_prompt, user_content, content_type
    )

    return content, quality


def generate_auto(
    style_name: str,
    content_type: str = "insights",
    count: int = 10,
    model: str | None = None,
    additional_instructions: str = "",
    mine_new: int = 5,
    on_progress=None,
) -> list[dict]:
    """Auto-generate posts from the transcript library — no manual input.

    Pipeline (BrandWorks-inspired):
    1. Pick diverse transcripts from the library.
    2. Story value gate: score each transcript — is there a moment worth posting?
    3. 7-day dedup: skip topics/angles already covered recently.
    4. Full-transcript generation: send the whole transcript to Sonnet, let it
       find the moment AND write the post in one shot (no lossy extraction).
    5. Quality gate: deterministic check on the finished post.

    Returns:
        List of dicts with content, scores, topic, etc.
    """
    from .knowledge_base import (
        get_random_transcripts,
        get_recent_post_topics,
        get_transcript_text,
        save_post,
    )

    client = _get_anthropic_client()
    model = model or os.getenv("CLAUDE_MODEL", "claude-sonnet-4-6")

    recent_topics = get_recent_post_topics(days=7)

    candidates = get_random_transcripts(limit=count * 4, min_chars=3000)
    candidates = _filter_on_topic(candidates)

    if not candidates:
        return []

    _ensure_content_dir()
    results = []
    rejected = 0

    for idx, t in enumerate(candidates):
        if len(results) >= count:
            break

        video_id = t["video_id"]
        video_title = t["video_title"]

        if on_progress:
            on_progress("scoring", idx + 1, len(candidates))

        text = get_transcript_text(video_id)
        if not text or len(text) < 1000:
            continue

        excerpt = text[:80_000]
        story = _score_story_value(
            client, video_title, excerpt, recent_topics, style_name
        )

        if not story:
            rejected += 1
            continue

        title = story.get("title", video_title)
        angle = story.get("angle", "")
        chosen_format = story.get("format", content_type)

        if on_progress:
            on_progress("generating", len(results) + 1, count)

        content, quality = _generate_from_full_transcript(
            client, model, style_name, text, video_title, video_id,
            story, additional_instructions,
        )

        slug = _slugify(title)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base = f"{timestamp}_auto_{slug}"
        txt_path = CONTENT_DIR / f"{base}.txt"
        txt_path.write_text(content)

        meta = {
            "style": style_name,
            "content_type": chosen_format,
            "topic": title,
            "focus": angle,
            "video_title": video_title,
            "video_id": video_id,
            "story_score": story.get("score", 0),
            "story_reason": story.get("reason", ""),
            "quality_score": quality["score"],
            "quality_passed": quality["passed"],
            "generated_at": datetime.now().isoformat(),
        }
        meta_path = CONTENT_DIR / f"{base}.meta.json"
        meta_path.write_text(json.dumps(meta, indent=2))

        try:
            save_post(
                style=style_name,
                content=content,
                content_type=chosen_format,
                topic=title,
                focus=angle,
                video_id=video_id,
                video_title=video_title,
                command="auto",
            )
        except Exception:
            pass

        recent_topics.append(title)

        results.append({
            "content": content,
            "score": quality["score"],
            "passed": quality["passed"],
            "issues": quality["issues"],
            "topic": title,
            "angle": angle,
            "format": chosen_format,
            "story_score": story.get("score", 0),
            "video_title": video_title,
            "file_path": txt_path,
        })

    if on_progress and rejected > 0:
        on_progress("rejected", rejected, rejected + len(results))

    return results


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
        video_id=video_id,
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

    # Persist to the knowledge base so it's retrievable + searchable later
    try:
        from .knowledge_base import save_post
        save_post(
            style=style_name,
            content=content,
            content_type=content_type,
            topic=topic,
            focus=focus,
            video_id=video_id,
            video_title=video_title,
            command="write",
        )
    except Exception:
        pass

    return content, txt_path


def _build_feedback_section(style_name: str, content_type: str) -> str:
    """Build a feedback section from past generated-vs-posted pairs."""
    try:
        from .knowledge_base import get_recent_feedback
        pairs = get_recent_feedback(style=style_name, content_type=content_type, limit=3)
        if not pairs:
            # Try without content_type filter
            pairs = get_recent_feedback(style=style_name, limit=3)
        if not pairs:
            return ""

        section = "\n# LEARN FROM MY EDITS\n"
        section += "Below are examples of what you generated vs what I actually posted.\n"
        section += "Study the differences — this is how I want you to write.\n\n"

        for i, pair in enumerate(pairs, 1):
            # Truncate to keep prompt manageable
            gen = pair["generated_text"][:500]
            posted = pair["posted_text"][:500]
            section += f"## Edit Example {i}\n"
            section += f"GENERATED:\n{gen}\n\n"
            section += f"WHAT I ACTUALLY POSTED:\n{posted}\n\n"

        section += "Apply these editing patterns to your new output.\n"
        return section
    except Exception:
        return ""


def _build_system_prompt(style_prompt: str, content_type: str, style_name: str = "") -> str:
    """Build the full system prompt combining style + content type instructions + feedback."""
    content_type_instructions = {
        "insights": (
            "You are writing an INSIGHTS post for Twitter/X.\n"
            "STRUCTURE: Build tension around ONE specific story or decision.\n"
            "  1. Hook — a bold claim, a counterintuitive fact, or a scene. 1-2 lines max.\n"
            "  2. Setup — the context, the conventional approach.\n"
            "  3. Turn — what they actually did, and why it's the opposite of expected.\n"
            "  4. The math / the evidence — concrete numbers, quotes, comparisons.\n"
            "  5. Closing line — the universal principle, distilled to one sentence.\n"
            "VOICE:\n"
            "- Short paragraphs, often single sentences. Lots of line breaks.\n"
            "- Embed real quotes mid-post as proof, not decoration.\n"
            "- Write like you know this cold — confident, no hedging.\n"
            "- No filler transitions. Every line moves the argument forward.\n"
            "OPENINGS — NEVER start with '[Person] on [topic]:'\n"
            "  Instead: a bold claim ('Nvidia could easily become a hyperscaler.'),\n"
            "  a surprising fact, a specific scene, or drop straight into the tension.\n"
            "ENDING: A single distilled line — the principle that makes someone screenshot it."
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

    prompt = f"""{style_prompt}

# CONTENT TYPE
{instructions}

# YOUR ROLE
You are a ghostwriter creating original Twitter/X content from source material.
You are NOT summarizing — you are finding the gold in a transcript and crafting
something that would stop someone mid-scroll.

QUOTES: Use real, verbatim quotes from the source material. They are the backbone
of every post. Quotes are proof, not decoration.

CROSS-FOUNDER CONNECTIONS: When the source material reminds you of another founder's
story, decision, or quote, weave it in. Show the pattern across different people.
Only connect to founders whose stories you can state accurately.

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
- NEVER start a sentence with "So," or "Now,"
- NEVER use filler transitions: "Meanwhile", "Additionally", "Furthermore", "Moreover"
- NEVER explain what the reader should feel: "This should worry investors"
- NEVER use first-person singular ("I think", "I believe")
- NEVER use emojis or hashtags
- NEVER fabricate numbers, dates, or quotes
- Extract specific stories, numbers, quotes, and details — specificity is what
  makes content interesting
- If a focus area is provided, go deep on that. If not, pull the most compelling
  insights from the material
- Write as if YOU are the author sharing things YOU know, not reporting on someone else

PROHIBITED PHRASES — never use any of these:
Sentence patterns:
- "It's not [X]. It's [Y]." or "This is not [X]. This is [Y]." (any variant)
- "This is what happens when [X] meets [Y]."
- "The real [X] is [Y]"
- "[X] was simple:" or "[X] was blunt:"
- Dramatic repetition: "The 2-year. The 2-year."

Phrases:
- "Here's the thing:"
- "Let that sink in."
- "Translation: ..."
- "For context, ..."
- "Hits home" or "Hits different"
- "Most do [X]..."

Hedging: "I think", "in my opinion", "it seems like", "could potentially",
"might suggest", "perhaps"

AI slop: "this is huge", "buckle up", "let that sink in", "the implications
are staggering", "game-changer", "paradigm shift", "sends shockwaves",
"raises big questions", "all eyes on", "only time will tell", "remains to
be seen"

Soft editorial: "it's worth noting", "this matters because", "here's why
this is important", "it cannot be overstated", "this is something to watch"

Literary/flowery: "seismic shift", "perfect storm", "watershed moment",
"there's nowhere to hide"

Buzzwords: "game-changer", "revolutionary", "disrupting", "reframe",
"framing"

Engagement bait: "What do you think?", "Thoughts?", "Agree or disagree?",
"Follow for more"

Structural:
- Emojis, hashtags
- Listicle framing inside prose (numbered lists embedded in narrative)
- Do NOT overuse em-dashes as a stylistic crutch

PARALLEL STRUCTURE BAN — THIS IS CRITICAL:
Do NOT repeat the same grammatical opening 2+ times in a row. Period.
This is the single most common failure mode. Examples of what NEVER to write:
  BAD: "Not clean. Not restaurant clean. Baby-lickable clean."
  BAD: "No five-year lock. No database reminders. Just raw exposure."
  BAD: "You can't cut corners. You can't hire badly. You can't pretend."
  BAD: "Not because they invented X. Not because they have Y."
  BAD: "He didn't do X. He didn't do Y. He did Z."
  BAD: "It forces you to build. Train. Think. Hire."
Every one of these is a crutch. If you catch yourself starting consecutive
sentences with the same word or phrase, STOP and rewrite. Vary the sentence
structure. Make each sentence arrive differently than the one before it.
The reader should never be able to predict the next sentence's shape.
"""

    # Inject feedback loop if available
    feedback_section = _build_feedback_section(style_name, content_type)
    if feedback_section:
        prompt += feedback_section

    return prompt


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
