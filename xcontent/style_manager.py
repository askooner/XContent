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

    This is injected into the content generation prompt so Claude
    understands exactly how you write without you explaining it again.
    """
    profile = load_style(name)
    examples = profile["examples"]

    lines = [
        "# YOUR WRITING STYLE",
        "",
        f"Style profile: {profile['name']}",
    ]
    if profile.get("description"):
        lines.append(f"Description: {profile['description']}")

    lines.append("")
    lines.append(f"Below are {len(examples)} example posts that illustrate the PATTERNS of this style.")
    lines.append("These are a starting point, NOT templates to copy or imitate literally.")
    lines.append("Learn the underlying patterns — then be CREATIVE and original with every post.")
    lines.append("")

    for i, example in enumerate(examples, 1):
        lines.append(f"--- EXAMPLE {i} ---")
        lines.append(example.strip())
        lines.append("")

    lines.append("--- END EXAMPLES ---")
    lines.append("")
    lines.append("IMPORTANT — What to learn from these examples (the patterns):")
    lines.append("- The RHYTHM: short paragraphs, line breaks, punchy sentences")
    lines.append("- The STRUCTURE: how they open, build, and close")
    lines.append("- The MIX: direct quotes woven with narrative/commentary")
    lines.append("- The TONE: confident, direct, no fluff, no hedging")
    lines.append("")
    lines.append("What NOT to do:")
    lines.append("- Do NOT copy the exact opening formulas from the examples")
    lines.append("- Do NOT repeat the same sentence structures over and over")
    lines.append("- Do NOT use clichés or generic motivational language")
    lines.append("- Do NOT start every post the same way — VARY your hooks")
    lines.append("- Do NOT write like a summary or book report")
    lines.append("")
    lines.append("Be CREATIVE. Every post should feel fresh and unique.")
    lines.append("The examples show the voice — YOUR job is to find new ways to use it.")

    return "\n".join(lines)
