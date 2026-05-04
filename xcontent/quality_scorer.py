"""
Quality Scorer — Deterministic quality gate for generated posts.

Checks for prohibited phrases, parallel structures, AI slop,
and structural issues. Posts below threshold get auto-regenerated.
"""

from __future__ import annotations

import re
import unicodedata

QUALITY_THRESHOLD = 70

BANNED_PHRASES = [
    "here's the thing",
    "here's what",
    "let that sink in",
    "translation:",
    "for context,",
    "hits home",
    "hits different",
    "this is huge",
    "buckle up",
    "the implications are staggering",
    "game-changer",
    "paradigm shift",
    "sends shockwaves",
    "raises big questions",
    "all eyes on",
    "only time will tell",
    "remains to be seen",
    "it's worth noting",
    "this matters because",
    "here's why this is important",
    "here's why",
    "it cannot be overstated",
    "this is something to watch",
    "seismic shift",
    "perfect storm",
    "watershed moment",
    "there's nowhere to hide",
    "revolutionary",
    "what do you think?",
    "thoughts?",
    "agree or disagree?",
    "follow for more",
    "in my opinion",
    "it seems like",
    "could potentially",
    "might suggest",
    "the brilliance",
    "the genius",
    "the beauty of",
]

BANNED_PATTERNS = [
    r"it'?s not .{1,50}\.\s+it'?s .{1,50}\.",
    r"this is not .{1,50}\.\s+this is .{1,50}\.",
    r"this is what happens when .{1,50} meets",
    r"the real \w+ is ",
    r"\w+ was simple:",
    r"\w+ was blunt:",
    # "No X. No Y. Just Z." and variants
    r"no \w[^.]{0,30}\.\s*no \w[^.]{0,30}\.\s*(just|only)",
    # "You can X. You can Y. You can't Z." and similar repeated subject+verb
    r"(you|he|she|they|it|we) (can|could|don't|didn't|won't|wouldn't|can't|couldn't) [^.]{1,40}\.\s*\1 \2",
    # "Not because X. Not because Y."
    r"not because [^.]{1,50}\.\s*not because ",
    # "Maybe X. Maybe Y."
    r"maybe [^.]{1,50}\.\s*maybe ",
]

PARALLEL_TRIGGER_WORDS = frozenset({
    "not", "no", "never", "don't", "doesn't", "didn't", "can't",
    "won't", "isn't", "wasn't", "couldn't", "wouldn't", "shouldn't",
    "every", "each", "just", "it's", "you", "he", "she", "they",
    "it", "we", "maybe", "perhaps", "this",
})

BAD_OPENERS = [
    "in a recent", "i just listened", "i just watched",
    "according to", "so,", "now,", "meanwhile",
    "additionally", "furthermore", "moreover",
]


def score_post(content: str, content_type: str = "insights") -> dict:
    """Score a generated post. Returns {"score": int, "passed": bool, "issues": list}."""
    issues = []
    deductions = 0

    phrase_issues = _check_prohibited_phrases(content)
    issues.extend(phrase_issues)
    deductions += len(phrase_issues) * 25

    parallel_issues = _check_parallel_structures(content)
    issues.extend(parallel_issues)
    deductions += len(parallel_issues) * 25

    format_issues = _check_formatting(content)
    issues.extend(format_issues)
    deductions += len(format_issues) * 10

    length_issues = _check_length(content, content_type)
    issues.extend(length_issues)
    deductions += len(length_issues) * 10

    opening_issues = _check_opening(content)
    issues.extend(opening_issues)
    deductions += len(opening_issues) * 10

    score = max(0, 100 - deductions)
    return {"score": score, "passed": score >= QUALITY_THRESHOLD, "issues": issues}


def _check_prohibited_phrases(content: str) -> list[str]:
    issues = []
    lower = content.lower()
    for phrase in BANNED_PHRASES:
        if phrase in lower:
            issues.append(f"Banned phrase: \"{phrase}\"")
    for pattern in BANNED_PATTERNS:
        if re.search(pattern, lower):
            issues.append(f"Banned pattern match")
    return issues


def _check_parallel_structures(content: str) -> list[str]:
    issues = []
    paragraphs = [p.strip() for p in content.split("\n") if p.strip()]

    for i in range(len(paragraphs) - 1):
        _check_pair(paragraphs[i], paragraphs[i + 1], issues)

    for para in paragraphs:
        sentences = re.split(r"(?<=[.!?])\s+", para)
        if len(sentences) < 2:
            continue
        for i in range(len(sentences) - 1):
            _check_pair(sentences[i], sentences[i + 1], issues)

    return issues


def _check_pair(a: str, b: str, issues: list[str]) -> None:
    prefix_2a = _first_n_words(a, 2)
    prefix_2b = _first_n_words(b, 2)
    if prefix_2a and prefix_2b and prefix_2a == prefix_2b:
        issues.append(f"Parallel: \"{prefix_2a}...\" repeated")
        return

    prefix_1a = _first_n_words(a, 1)
    prefix_1b = _first_n_words(b, 1)
    if prefix_1a and prefix_1b and prefix_1a == prefix_1b:
        if prefix_1a in PARALLEL_TRIGGER_WORDS:
            issues.append(f"Parallel: \"{prefix_1a}...\" repeated")


def _first_n_words(text: str, n: int) -> str:
    text = text.strip().lstrip("\"'")
    words = text.split()[:n]
    if not words:
        return ""
    return " ".join(w.lower().rstrip(".,;:!?") for w in words)


def _check_formatting(content: str) -> list[str]:
    issues = []
    emoji_count = sum(1 for c in content if unicodedata.category(c).startswith("So"))
    if emoji_count > 0:
        issues.append(f"Contains {emoji_count} emoji(s)")

    hashtags = re.findall(r"#\w+", content)
    if hashtags:
        issues.append(f"Contains hashtag(s): {', '.join(hashtags[:3])}")

    em_dash_count = content.count("—") + content.count("--")
    if em_dash_count > 3:
        issues.append(f"Excessive em-dashes ({em_dash_count})")

    return issues


def _check_length(content: str, content_type: str) -> list[str]:
    issues = []
    n = len(content)
    limits = {
        "insights": (200, 1800),
        "essays": (200, 2200),
        "transcripts": (300, 2500),
        "quote-tweets": (50, 500),
    }
    lo, hi = limits.get(content_type, (100, 3000))
    if n < lo:
        issues.append(f"Too short ({n} chars, min {lo})")
    elif n > hi:
        issues.append(f"Too long ({n} chars, max {hi})")
    return issues


def _check_opening(content: str) -> list[str]:
    issues = []
    first_line = content.strip().split("\n")[0].lower()
    for opener in BAD_OPENERS:
        if first_line.startswith(opener):
            issues.append(f"Bad opening: \"{opener}...\"")
    return issues
