"""
Style Manager — Save, analyze, and load writing style profiles.

You paste 3-5 example posts. The system extracts your style DNA
(hooks, tone, structure, length, vocabulary patterns) and saves it
so you never have to re-explain how you write.
"""

from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

STYLES_DIR = Path(__file__).resolve().parent.parent / "styles"


def _ensure_styles_dir():
    STYLES_DIR.mkdir(parents=True, exist_ok=True)


def save_style(name: str, examples: list[str], description: str = "") -> Path:
    """Save a writing style profile from example posts.

    Args:
        name: Profile name (e.g. "linkedin-thought-leadership", "twitter-thread")
        examples: List of 3-5 example posts that represent the style
        description: Optional description of when to use this style

    Returns:
        Path to the saved style file
    """
    _ensure_styles_dir()

    profile = {
        "name": name,
        "description": description,
        "examples": examples,
        "created_at": datetime.now().isoformat(),
        "updated_at": datetime.now().isoformat(),
    }

    path = STYLES_DIR / f"{name}.json"
    path.write_text(json.dumps(profile, indent=2))
    return path


def load_style(name: str) -> dict:
    """Load a saved style profile by name."""
    path = STYLES_DIR / f"{name}.json"
    if not path.exists():
        raise FileNotFoundError(f"Style profile '{name}' not found. Run 'xcontent style add' first.")
    return json.loads(path.read_text())


def list_styles() -> list[dict]:
    """List all saved style profiles."""
    _ensure_styles_dir()
    styles = []
    for path in sorted(STYLES_DIR.glob("*.json")):
        data = json.loads(path.read_text())
        styles.append({
            "name": data["name"],
            "description": data.get("description", ""),
            "num_examples": len(data.get("examples", [])),
            "updated_at": data.get("updated_at", ""),
        })
    return styles


def delete_style(name: str) -> bool:
    """Delete a style profile."""
    path = STYLES_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


def update_style(name: str, examples: list[str] | None = None, description: str | None = None) -> dict:
    """Update an existing style profile with new examples or description."""
    profile = load_style(name)

    if examples is not None:
        profile["examples"] = examples
    if description is not None:
        profile["description"] = description
    profile["updated_at"] = datetime.now().isoformat()

    path = STYLES_DIR / f"{name}.json"
    path.write_text(json.dumps(profile, indent=2))
    return profile


def build_style_prompt(name: str) -> str:
    """Build a prompt section that teaches the AI your writing style.

    Uses the user's best posts as the PRIMARY instruction — the model should
    match these exactly in voice, structure, and rhythm. Not as inspiration,
    as the template.
    """
    profile = load_style(name)
    examples = profile["examples"]

    # Pick 8 diverse examples — enough to show the range, not so many it dilutes
    import random
    if len(examples) > 8:
        sample = random.sample(examples, 8)
    else:
        sample = examples

    lines = [
        "# HOW YOU WRITE",
        "",
        "These are YOUR published posts. This is YOUR voice.",
        "Study them obsessively. Match their exact rhythm, length, structure, and tone.",
        "Your output should be INDISTINGUISHABLE from these examples.",
        "",
        "If your draft doesn't read like it belongs in this list, throw it out and start over.",
        "",
    ]

    for i, example in enumerate(sample, 1):
        lines.append(f"--- YOUR POST {i} ---")
        lines.append(example.strip())
        lines.append("")

    lines.append("--- END YOUR POSTS ---")
    lines.append("")
    lines.append("MATCH THESE EXACTLY:")
    lines.append("- Same sentence lengths. Same paragraph lengths. Same number of line breaks.")
    lines.append("- Same ratio of quotes to narrative. Same density of specific facts.")
    lines.append("- Same kinds of openings. Same kinds of endings.")
    lines.append("- If your posts are typically 8-15 lines, write 8-15 lines. Not 30.")
    lines.append("- If your posts use 1-2 quotes, use 1-2 quotes. Not 5.")
    lines.append("")
    lines.append("THE ONE RULE: Your output must pass as one of the posts above.")
    lines.append("A reader scrolling through your timeline should not be able to tell")
    lines.append("which posts are real and which you generated.")

    return "\n".join(lines)
