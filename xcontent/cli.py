"""
XContent CLI — The main interface for the content system.

Usage:
    xcontent style add <name>          Teach the system your writing style
    xcontent style list                List saved styles
    xcontent style show <name>         Show a style's examples
    xcontent style remove <name>       Delete a style

    xcontent source add <channel>      Add a YouTube channel
    xcontent source list               List saved channels
    xcontent source remove <id>        Remove a channel

    xcontent search <query>            Search videos across your channels
    xcontent transcript <video_id>     Fetch a video's transcript

    xcontent write                     Generate content (interactive)
    xcontent write --style <s> --video <id> --topic <t>   Generate content (one-shot)

    xcontent history                   List previously generated content
"""

import os
import sys
from datetime import datetime
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

console = Console()


@click.group()
def cli():
    """XContent — Your content creation machine for Found Remote."""
    pass


# ── Style Commands ───────────────────────────────────────────────────


@cli.group()
def style():
    """Manage your writing style profiles."""
    pass


@style.command("add")
@click.argument("name")
@click.option("--description", "-d", default="", help="When to use this style")
@click.option("--file", "-f", "files", multiple=True, help="Text files containing example posts (one post per file)")
def style_add(name, description, files):
    """Save a new writing style from example posts."""
    from .style_manager import save_style

    examples = []

    if files:
        for f in files:
            with open(f) as fh:
                examples.append(fh.read().strip())
        console.print(f"[green]Loaded {len(examples)} examples from files.[/green]")
    else:
        console.print(
            Panel(
                "Paste your example posts one at a time.\n"
                "After each post, press Enter twice (empty line) to confirm.\n"
                "Type [bold]DONE[/bold] on a new line when finished.\n"
                "Aim for 3-5 examples for best results.",
                title="Style Setup",
            )
        )

        while True:
            console.print(f"\n[cyan]Example {len(examples) + 1}[/cyan] (or type DONE):")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "DONE":
                    break
                if line == "" and lines and lines[-1] == "":
                    lines.pop()  # remove trailing empty line
                    break
                lines.append(line)

            text = "\n".join(lines).strip()
            if not text or text == "DONE":
                break
            examples.append(text)
            console.print(f"[green]✓ Saved example {len(examples)} ({len(text)} chars)[/green]")

    if not examples:
        console.print("[red]No examples provided. Aborting.[/red]")
        return

    path = save_style(name, examples, description)
    console.print(f"\n[bold green]Style '{name}' saved with {len(examples)} examples.[/bold green]")
    console.print(f"File: {path}")


@style.command("list")
def style_list():
    """List all saved writing styles."""
    from .style_manager import list_styles

    styles = list_styles()
    if not styles:
        console.print("[yellow]No styles saved yet. Run 'xcontent style add <name>' to create one.[/yellow]")
        return

    table = Table(title="Writing Styles")
    table.add_column("Name", style="cyan")
    table.add_column("Examples", justify="right")
    table.add_column("Description")
    table.add_column("Updated")

    for s in styles:
        table.add_row(s["name"], str(s["num_examples"]), s["description"], s["updated_at"][:10])

    console.print(table)


@style.command("show")
@click.argument("name")
def style_show(name):
    """Show a style profile's examples."""
    from .style_manager import load_style

    try:
        profile = load_style(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        return

    console.print(f"\n[bold]{profile['name']}[/bold]")
    if profile.get("description"):
        console.print(f"[dim]{profile['description']}[/dim]")
    console.print()

    for i, example in enumerate(profile["examples"], 1):
        console.print(Panel(example, title=f"Example {i}", border_style="blue"))


@style.command("remove")
@click.argument("name")
def style_remove(name):
    """Delete a style profile."""
    from .style_manager import delete_style

    if delete_style(name):
        console.print(f"[green]Style '{name}' deleted.[/green]")
    else:
        console.print(f"[red]Style '{name}' not found.[/red]")


@style.command("add-example")
@click.argument("name")
@click.option("--file", "-f", "files", multiple=True, help="Text files with example posts")
def style_add_example(name, files):
    """Add more example posts to an existing style (makes output better)."""
    from .style_manager import load_style, update_style

    try:
        profile = load_style(name)
    except FileNotFoundError as e:
        console.print(f"[red]{e}[/red]")
        return

    existing = profile.get("examples", [])
    new_examples = []

    if files:
        for f in files:
            with open(f) as fh:
                new_examples.append(fh.read().strip())
    else:
        console.print(
            f"[cyan]Style '{name}' currently has {len(existing)} examples.[/cyan]\n"
            "Paste additional examples. Enter twice (empty line) after each.\n"
            "Type DONE when finished."
        )
        while True:
            console.print(f"\n[cyan]Example {len(existing) + len(new_examples) + 1}[/cyan] (or DONE):")
            lines = []
            while True:
                try:
                    line = input()
                except EOFError:
                    break
                if line.strip() == "DONE":
                    break
                if line == "" and lines and lines[-1] == "":
                    lines.pop()
                    break
                lines.append(line)

            text = "\n".join(lines).strip()
            if not text or text == "DONE":
                break
            new_examples.append(text)
            console.print(f"[green]Added example ({len(text)} chars)[/green]")

    if not new_examples:
        console.print("[yellow]No examples added.[/yellow]")
        return

    update_style(name, examples=existing + new_examples)
    console.print(f"\n[bold green]Added {len(new_examples)} examples to '{name}' "
                  f"(now {len(existing) + len(new_examples)} total).[/bold green]")


# ── Source Commands ──────────────────────────────────────────────────


@cli.group()
def source():
    """Manage YouTube channel sources."""
    pass


@source.command("add")
@click.argument("channel")
def source_add(channel):
    """Add a YouTube channel (URL, @handle, or name)."""
    from .source_manager import add_channel

    try:
        with console.status("Looking up channel..."):
            info = add_channel(channel)
        console.print(f"\n[bold green]Added:[/bold green] {info['title']}")
        console.print(f"  ID: {info['id']}")
        console.print(f"  Videos: {info['video_count']}")
        console.print(f"  Subscribers: {info['subscriber_count']}")
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")


@source.command("list")
def source_list():
    """List all saved YouTube channels."""
    from .source_manager import list_channels

    channels = list_channels()
    if not channels:
        console.print("[yellow]No channels added yet. Run 'xcontent source add <channel>' to add one.[/yellow]")
        return

    table = Table(title="YouTube Sources")
    table.add_column("Channel", style="cyan")
    table.add_column("Videos", justify="right")
    table.add_column("Channel ID", style="dim")
    table.add_column("Added")

    for ch in channels:
        table.add_row(ch["title"], str(ch["video_count"]), ch["id"], ch.get("added_at", "")[:10])

    console.print(table)


@source.command("remove")
@click.argument("channel_id")
def source_remove(channel_id):
    """Remove a YouTube channel by its ID."""
    from .source_manager import remove_channel

    if remove_channel(channel_id):
        console.print(f"[green]Channel removed.[/green]")
    else:
        console.print(f"[red]Channel ID '{channel_id}' not found.[/red]")


# ── Search & Transcript ─────────────────────────────────────────────


@cli.command()
@click.argument("query")
@click.option("--channel", "-c", "channel_id", default=None, help="Restrict to a specific channel ID")
@click.option("--max", "-n", "max_results", default=10, help="Max results per channel")
def search(query, channel_id, max_results):
    """Search videos across your saved YouTube channels."""
    from .source_manager import search_videos

    channel_ids = [channel_id] if channel_id else None

    try:
        with console.status("Searching..."):
            results = search_videos(query, channel_ids=channel_ids, max_results=max_results)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if not results:
        console.print("[yellow]No results found.[/yellow]")
        return

    table = Table(title=f"Results for '{query}'")
    table.add_column("#", style="dim", width=3)
    table.add_column("Title", style="cyan", max_width=60)
    table.add_column("Channel")
    table.add_column("Date")
    table.add_column("Video ID", style="dim")

    for i, v in enumerate(results, 1):
        table.add_row(str(i), v["title"], v["channel"], v["published"], v["video_id"])

    console.print(table)
    console.print("\n[dim]Use the Video ID with 'xcontent transcript <video_id>' to fetch the transcript.[/dim]")


@cli.command()
@click.argument("video_id")
@click.option("--save", "-s", is_flag=True, help="Save transcript to a file")
@click.option("--timestamps", "-t", is_flag=True, help="Include timestamps")
def transcript(video_id, save, timestamps):
    """Fetch the transcript for a YouTube video."""
    from .source_manager import get_transcript, get_transcript_with_timestamps

    try:
        with console.status("Fetching transcript..."):
            if timestamps:
                data = get_transcript_with_timestamps(video_id)
                text = "\n".join(
                    f"[{_format_time(s['start'])}] {s['text']}" for s in data
                )
            else:
                text = get_transcript(video_id)
    except Exception as e:
        console.print(f"[red]Error fetching transcript: {e}[/red]")
        return

    if save:
        path = f"content/transcript_{video_id}.txt"
        with open(path, "w") as f:
            f.write(text)
        console.print(f"[green]Transcript saved to {path}[/green]")
    else:
        console.print(text)

    console.print(f"\n[dim]Length: {len(text)} characters[/dim]")


def _format_time(seconds: float) -> str:
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ── Write Command ───────────────────────────────────────────────────


@cli.command()
@click.option("--style", "-s", "style_name", required=True, help="Style profile to use")
@click.option("--video", "-v", "video_id", default=None, help="YouTube video ID or URL")
@click.option("--topic", "-t", default="", help="What the post should be about (also used to auto-search videos)")
@click.option("--focus", "-f", default="", help="Specific angle or moment to focus on")
@click.option("--type", "-T", "content_type", default="insights",
              type=click.Choice(["insights", "essays", "transcripts", "quote-tweets"]),
              help="Content format")
@click.option("--instructions", "-i", default="", help="Additional instructions")
@click.option("--transcript-file", default=None, help="Path to a transcript file (instead of --video)")
@click.option("--from-library", "-l", "library_query", default=None,
              help="Search your transcript library instead of fetching from YouTube")
@click.option("--model", "-m", default=None, help="Claude model to use")
@click.option("--no-save", is_flag=True, help="Don't save the output to a file")
@click.option("--no-typefully", is_flag=True, help="Don't push to Typefully (local save only)")
def write(style_name, video_id, topic, focus, content_type, instructions, transcript_file, library_query, model, no_save, no_typefully):
    """Generate content in your style from a source transcript.

    If no --video is given but --topic is, it will search your channels
    and let you pick a video. You can also pass a full YouTube URL as --video.
    Use --from-library to search your stored transcripts (free, no API calls).
    """
    import re

    from .content_generator import generate, generate_and_save
    from .source_manager import get_transcript, get_video_details, search_videos

    # Extract video ID from full YouTube URL if given
    if video_id and ("youtube.com" in video_id or "youtu.be" in video_id):
        m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", video_id)
        if m:
            video_id = m.group(1)

    # Get transcript
    if library_query:
        # Search local library — free, no API calls
        from .knowledge_base import search_transcripts, get_transcript_text as kb_get
        results = search_transcripts(library_query)
        if not results:
            console.print(f"[yellow]No matches for '{library_query}' in your library.[/yellow]")
            return

        console.print(f"\n[bold]Found {len(results)} matches in your library:[/bold]\n")
        for i, r in enumerate(results, 1):
            console.print(f"  [cyan]{i}[/cyan]. {r['video_title']} — [dim]{r['channel']}[/dim]")

        console.print()
        choice = click.prompt("Pick a video", type=int, default=1)
        if choice < 1 or choice > len(results):
            console.print("[red]Invalid choice.[/red]")
            return

        picked = results[choice - 1]
        video_id = picked["video_id"]
        video_title = picked["video_title"]
        transcript_text = kb_get(video_id)
        console.print(f"\n[green]Source (from library):[/green] {video_title}")
        console.print(f"[dim]Transcript: {len(transcript_text)} characters — no API call needed[/dim]\n")
    elif transcript_file:
        with open(transcript_file) as f:
            transcript_text = f.read()
        video_title = transcript_file
    elif video_id:
        try:
            with console.status("Fetching video info and transcript..."):
                details = get_video_details(video_id)
                video_title = details["title"]
                transcript_text = get_transcript(video_id, video_title=video_title,
                                                 channel=details.get("channel", ""))
            console.print(f"[green]Source:[/green] {video_title}")
            console.print(f"[dim]Transcript: {len(transcript_text)} characters[/dim]")
            if len(transcript_text) > 15_000:
                console.print(f"[dim]Will extract key material first to save costs[/dim]\n")
            else:
                console.print()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return
    elif topic:
        # Auto-search: find a video matching the topic
        try:
            with console.status(f"Searching for '{topic}' across your channels..."):
                results = search_videos(topic, max_results=5)
        except Exception as e:
            console.print(f"[red]Error searching: {e}[/red]")
            return

        if not results:
            console.print(f"[yellow]No videos found for '{topic}'.[/yellow]")
            return

        # Show results and let user pick
        console.print(f"\n[bold]Found {len(results)} videos for '{topic}':[/bold]\n")
        for i, v in enumerate(results, 1):
            console.print(f"  [cyan]{i}[/cyan]. {v['title']} — [dim]{v['channel']} ({v['published']})[/dim]")

        console.print()
        choice = click.prompt("Pick a video (number)", type=int, default=1)
        if choice < 1 or choice > len(results):
            console.print("[red]Invalid choice.[/red]")
            return

        picked = results[choice - 1]
        video_id = picked["video_id"]

        try:
            with console.status("Fetching transcript..."):
                video_title = picked["title"]
                transcript_text = get_transcript(video_id, video_title=video_title,
                                                 channel=picked.get("channel", ""))
            console.print(f"\n[green]Source:[/green] {video_title}")
            console.print(f"[dim]Transcript: {len(transcript_text)} characters[/dim]")
            if len(transcript_text) > 15_000:
                console.print(f"[dim]Will extract key material first to save costs[/dim]\n")
            else:
                console.print()
        except Exception as e:
            console.print(f"[red]Error fetching transcript: {e}[/red]")
            return
    else:
        console.print("[yellow]Paste your transcript below. Press Ctrl+D (or Ctrl+Z on Windows) when done:[/yellow]")
        transcript_text = sys.stdin.read()
        video_title = ""

    if not transcript_text.strip():
        console.print("[red]No transcript provided.[/red]")
        return

    # Generate content
    with console.status(f"Writing {content_type} post in '{style_name}' style..."):
        if no_save:
            content = generate(
                style_name=style_name,
                transcript=transcript_text,
                topic=topic,
                focus=focus,
                content_type=content_type,
                additional_instructions=instructions,
                model=model,
                video_title=video_title,
            )
            path = None
        else:
            content, path = generate_and_save(
                style_name=style_name,
                transcript=transcript_text,
                topic=topic,
                focus=focus,
                content_type=content_type,
                additional_instructions=instructions,
                model=model,
                video_title=video_title,
                video_id=video_id or "",
            )

    # Output the content cleanly
    console.print(f"\n[bold green]── {content_type.upper()} Post ──[/bold green]\n")
    console.print(content)
    console.print()

    # Copy to clipboard (macOS)
    try:
        import subprocess
        subprocess.run(["pbcopy"], input=content.encode(), check=True)
        console.print("[green]Copied to clipboard.[/green] Just Cmd+V to paste.")
    except Exception:
        pass

    if path:
        console.print(f"[dim]Saved to: {path}[/dim]")

    # Push to Typefully
    if not no_typefully:
        try:
            from .typefully import create_draft
            with console.status("Pushing to Typefully..."):
                result = create_draft(content)
            console.print("[green]Pushed to Typefully as a draft.[/green]")
        except RuntimeError as e:
            if "TYPEFULLY_API_KEY not set" in str(e):
                pass  # Silently skip if no key configured
            else:
                console.print(f"[yellow]Typefully: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Typefully push failed: {e}[/yellow]")


# ── Batch Command ────────────────────────────────────────────────────


@cli.command()
@click.option("--style", "-s", "style_name", required=True, help="Style profile to use")
@click.option("--video", "-v", "video_id", default=None, help="YouTube video ID or URL")
@click.option("--topic", "-t", default="", help="Search topic to find a video")
@click.option("--type", "-T", "content_type", default="insights",
              type=click.Choice(["insights", "essays", "transcripts", "quote-tweets"]),
              help="Content format for all posts")
@click.option("--num", "-n", "num_posts", default=0, help="Number of posts (0 = auto, defaults to 3 best ideas)")
@click.option("--transcript-file", default=None, help="Path to a transcript file")
@click.option("--from-library", "-l", "library_query", default=None,
              help="Search your transcript library instead of fetching from YouTube")
@click.option("--model", "-m", default=None, help="Claude model to use")
@click.option("--instructions", "-i", default="", help="Additional instructions for all posts")
@click.option("--no-typefully", is_flag=True, help="Don't push to Typefully (local save only)")
@click.option("--fresh", is_flag=True, help="Force fresh idea extraction (ignore cached ideas)")
def batch(style_name, video_id, topic, content_type, num_posts, transcript_file, library_query, model, instructions, no_typefully, fresh):
    """Generate multiple posts from a single video.

    Extracts 4-5+ distinct ideas from one transcript and writes a separate
    post for each. One video = a week of content.
    Use --from-library to reuse a stored transcript (free, no API calls).
    Use --fresh to force new idea extraction even if ideas already exist.
    """
    import re

    from .content_generator import generate_batch
    from .source_manager import get_transcript, get_video_details, search_videos

    # Extract video ID from full YouTube URL if given
    if video_id and ("youtube.com" in video_id or "youtu.be" in video_id):
        m = re.search(r"(?:v=|youtu\.be/)([\w-]{11})", video_id)
        if m:
            video_id = m.group(1)

    # Get transcript
    if library_query:
        from .knowledge_base import search_transcripts, get_transcript_text as kb_get
        results = search_transcripts(library_query)
        if not results:
            console.print(f"[yellow]No matches for '{library_query}' in your library.[/yellow]")
            return

        console.print(f"\n[bold]Found {len(results)} matches in your library:[/bold]\n")
        for i, r in enumerate(results, 1):
            console.print(f"  [cyan]{i}[/cyan]. {r['video_title']} — [dim]{r['channel']}[/dim]")

        console.print()
        choice = click.prompt("Pick a video", type=int, default=1)
        if choice < 1 or choice > len(results):
            console.print("[red]Invalid choice.[/red]")
            return

        picked = results[choice - 1]
        video_id = picked["video_id"]
        video_title = picked["video_title"]
        transcript_text = kb_get(video_id)
        console.print(f"\n[green]Source (from library):[/green] {video_title}")
        console.print(f"[dim]Transcript: {len(transcript_text)} characters — no API call needed[/dim]\n")
    elif transcript_file:
        with open(transcript_file) as f:
            transcript_text = f.read()
        video_title = transcript_file
    elif video_id:
        try:
            with console.status("Fetching video info and transcript..."):
                details = get_video_details(video_id)
                video_title = details["title"]
                transcript_text = get_transcript(video_id, video_title=video_title,
                                                 channel=details.get("channel", ""))
            console.print(f"[green]Source:[/green] {video_title}")
            console.print(f"[dim]Transcript: {len(transcript_text)} characters[/dim]\n")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return
    elif topic:
        try:
            with console.status(f"Searching for '{topic}'..."):
                results = search_videos(topic, max_results=5)
        except Exception as e:
            console.print(f"[red]Error searching: {e}[/red]")
            return

        if not results:
            console.print(f"[yellow]No videos found for '{topic}'.[/yellow]")
            return

        console.print(f"\n[bold]Found {len(results)} videos:[/bold]\n")
        for i, v in enumerate(results, 1):
            console.print(f"  [cyan]{i}[/cyan]. {v['title']} — [dim]{v['channel']} ({v['published']})[/dim]")

        console.print()
        choice = click.prompt("Pick a video", type=int, default=1)
        if choice < 1 or choice > len(results):
            console.print("[red]Invalid choice.[/red]")
            return

        picked = results[choice - 1]
        video_id = picked["video_id"]

        try:
            with console.status("Fetching transcript..."):
                video_title = picked["title"]
                transcript_text = get_transcript(video_id, video_title=video_title,
                                                 channel=picked.get("channel", ""))
            console.print(f"\n[green]Source:[/green] {video_title}")
            console.print(f"[dim]Transcript: {len(transcript_text)} characters[/dim]\n")
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
            return
    else:
        console.print("[red]Provide --video, --topic, or --transcript-file.[/red]")
        return

    if not transcript_text.strip():
        console.print("[red]No transcript provided.[/red]")
        return

    # Generate batch — check library for existing ideas first
    ideas = None
    if video_id and not fresh:
        from .knowledge_base import get_ideas_for_video, save_ideas
        existing = get_ideas_for_video(video_id)
        if existing:
            console.print(f"[green]Found {len(existing)} ideas already extracted for this video (no tokens used).[/green]\n")
            # Convert DB rows back to the format extract_ideas returns
            ideas = [
                {"title": e["title"], "angle": e["angle"], "key_material": e["key_material"]}
                for e in existing
            ]

    if ideas is None:
        if num_posts > 0:
            console.print(f"[bold]Extracting {num_posts} post ideas and generating content...[/bold]\n")
        else:
            console.print(f"[bold]Mining transcript for all post-worthy ideas...[/bold]\n")

        with console.status("Step 1: Mining transcript for post ideas..."):
            from .content_generator import extract_ideas
            ideas = extract_ideas(transcript_text, video_title, num_ideas=num_posts)

        # Save ideas to knowledge base
        if video_id:
            from .knowledge_base import save_ideas
            save_ideas(video_id, ideas)

    try:

        console.print(f"[green]Found {len(ideas)} ideas:[/green]\n")
        for i, idea in enumerate(ideas, 1):
            console.print(f"  [cyan]{i}[/cyan]. {idea.get('title', 'Untitled')}")
            if idea.get('angle'):
                console.print(f"     [dim]{idea['angle'][:80]}[/dim]")
        console.print()

        results = []
        for i, idea in enumerate(ideas, 1):
            with console.status(f"Writing post {i}/{len(ideas)}: {idea.get('title', '')}..."):
                from .content_generator import generate, _slugify
                from .style_manager import build_style_prompt

                style_prompt = build_style_prompt(style_name)

                from .content_generator import _build_system_prompt, _build_user_prompt, _get_anthropic_client
                client = _get_anthropic_client()
                write_model = model or os.getenv("CLAUDE_MODEL", "claude-haiku-4-5-20251001")

                system_prompt = _build_system_prompt(style_prompt, content_type, style_name)
                key_material = idea.get("key_material", idea.get("key_quotes", ""))
                user_prompt = _build_user_prompt(
                    transcript=key_material,
                    topic=idea.get("title", ""),
                    focus=idea.get("angle", ""),
                    additional_instructions=instructions,
                    video_title=video_title,
                )

                response = client.messages.create(
                    model=write_model,
                    max_tokens=4096,
                    system=system_prompt,
                    messages=[{"role": "user", "content": user_prompt}],
                )
                content = response.content[0].text

                # Save
                from pathlib import Path as P
                content_dir = P(__file__).resolve().parent.parent / "content"
                content_dir.mkdir(parents=True, exist_ok=True)

                slug = _slugify(idea.get("title", f"post-{i}"))
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                base = f"{timestamp}_{slug}"

                txt_path = content_dir / f"{base}.txt"
                txt_path.write_text(content)

                import json as _json
                meta = {
                    "style": style_name,
                    "content_type": content_type,
                    "topic": idea.get("title", ""),
                    "focus": idea.get("angle", ""),
                    "video_title": video_title,
                    "video_id": video_id or "",
                    "batch_index": i,
                    "batch_total": len(ideas),
                    "generated_at": datetime.now().isoformat(),
                }
                meta_path = content_dir / f"{base}.meta.json"
                meta_path.write_text(_json.dumps(meta, indent=2))

                results.append((content, txt_path))

            console.print(f"  [green]Post {i}:[/green] {idea.get('title', '')}")

    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    # Show all generated posts
    console.print(f"\n[bold green]Generated {len(results)} posts:[/bold green]\n")
    for i, (content, path) in enumerate(results, 1):
        console.print(f"[bold cyan]── Post {i} ──[/bold cyan]\n")
        console.print(content)
        console.print(f"\n[dim]Saved: {path}[/dim]\n")

    # Copy all to clipboard (separated by dividers)
    try:
        import subprocess
        all_content = "\n\n---\n\n".join(c for c, _ in results)
        subprocess.run(["pbcopy"], input=all_content.encode(), check=True)
        console.print(f"[green]All {len(results)} posts copied to clipboard (separated by ---).[/green]")
    except Exception:
        pass

    # Push all to Typefully
    if not no_typefully:
        try:
            from .typefully import push_drafts
            with console.status(f"Pushing {len(results)} drafts to Typefully..."):
                drafts = push_drafts([c for c, _ in results])
            console.print(f"[green]Pushed {len(drafts)} drafts to Typefully.[/green]")
        except RuntimeError as e:
            if "TYPEFULLY_API_KEY not set" in str(e):
                pass  # Silently skip if no key configured
            else:
                console.print(f"[yellow]Typefully: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Typefully push failed: {e}[/yellow]")


# ── History ──────────────────────────────────────────────────────────


@cli.command()
@click.option("--limit", "-n", default=20, help="Number of items to show")
def history(limit):
    """List previously generated content."""
    from pathlib import Path

    content_dir = Path(__file__).resolve().parent.parent / "content"
    if not content_dir.exists():
        console.print("[yellow]No content generated yet.[/yellow]")
        return

    files = sorted(content_dir.glob("*.meta.json"), reverse=True)[:limit]
    if not files:
        # Fallback: check for old-style .json files
        files = sorted(content_dir.glob("*.json"), reverse=True)[:limit]
    if not files:
        console.print("[yellow]No content generated yet.[/yellow]")
        return

    import json

    table = Table(title="Generated Content")
    table.add_column("Date", style="dim")
    table.add_column("Style", style="cyan")
    table.add_column("Type")
    table.add_column("Topic", max_width=40)
    table.add_column("File", style="dim")

    for f in files:
        data = json.loads(f.read_text())
        meta = data if f.name.endswith(".meta.json") else data.get("metadata", {})
        txt_name = f.name.replace(".meta.json", ".txt")
        table.add_row(
            meta.get("generated_at", "")[:16],
            meta.get("style", "?"),
            meta.get("content_type", "?"),
            meta.get("topic", meta.get("video_title", ""))[:40],
            txt_name,
        )

    console.print(table)


# ── Quote Reply Command ────────────────────────────────────────────


@cli.command("quote-reply")
@click.argument("tweet_text")
@click.option("--style", "-s", "style_name", default="quote-tweets", help="Style profile to use")
@click.option("--model", "-m", default=None, help="Claude model to use")
@click.option("--instructions", "-i", default="", help="Additional instructions")
@click.option("--no-typefully", is_flag=True, help="Don't push to Typefully")
@click.option("--no-save", is_flag=True, help="Don't save to file")
def quote_reply(tweet_text, style_name, model, instructions, no_typefully, no_save):
    """Generate a quote-tweet reply grounded in real entrepreneur stories.

    \b
    Searches your transcript library for related material, then writes
    a factual reply connecting the tweet's idea to a real story.

    \b
    Example:
        xcontent quote-reply "Peter Thiel on why you should work with people you like..."
    """
    from .content_generator import generate_quote_reply

    console.print(f"\n[bold]Analyzing tweet and searching your library...[/bold]\n")

    try:
        with console.status("Searching library for related stories..."):
            reply, sources = generate_quote_reply(
                tweet_text=tweet_text,
                style_name=style_name,
                model=model,
                additional_instructions=instructions,
            )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    # Show sources used
    if sources:
        console.print(f"[dim]Sources found in library:[/dim]")
        for s in sources:
            console.print(f"  [dim]- {s['video_title']} ({s.get('channel', '')})[/dim]")
        console.print()
    else:
        console.print("[yellow]No matching transcripts in library — reply is based on extending the idea only.[/yellow]\n")

    # Show the reply
    console.print(f"[bold green]── QUOTE REPLY ──[/bold green]\n")
    console.print(reply)
    console.print()

    # Copy to clipboard
    try:
        import subprocess
        subprocess.run(["pbcopy"], input=reply.encode(), check=True)
        console.print("[green]Copied to clipboard.[/green]")
    except Exception:
        pass

    # Save to file
    if not no_save:
        from pathlib import Path as P
        from .content_generator import _slugify

        content_dir = P(__file__).resolve().parent.parent / "content"
        content_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _slugify(tweet_text[:40])
        base = f"{timestamp}_qr_{slug}"

        txt_path = content_dir / f"{base}.txt"
        txt_path.write_text(reply)

        import json as _json
        meta = {
            "style": style_name,
            "content_type": "quote-reply",
            "original_tweet": tweet_text[:500],
            "sources": [s.get("video_title", "") for s in sources],
            "generated_at": datetime.now().isoformat(),
        }
        meta_path = content_dir / f"{base}.meta.json"
        meta_path.write_text(_json.dumps(meta, indent=2))
        console.print(f"[dim]Saved to: {txt_path}[/dim]")

        # Persist to the knowledge base
        try:
            from .knowledge_base import save_post
            save_post(
                style=style_name,
                content=reply,
                content_type="quote-reply",
                topic=tweet_text[:120],
                source_videos=" | ".join(s.get("video_title", "") for s in sources),
                command="quote-reply",
            )
        except Exception:
            pass

    # Push to Typefully
    if not no_typefully:
        try:
            from .typefully import create_draft
            with console.status("Pushing to Typefully..."):
                create_draft(reply)
            console.print("[green]Pushed to Typefully as a draft.[/green]")
        except RuntimeError as e:
            if "TYPEFULLY_API_KEY not set" in str(e):
                pass
            else:
                console.print(f"[yellow]Typefully: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Typefully push failed: {e}[/yellow]")


# ── Story Command (Cross-Library Narrative Synthesis) ────────────────


@cli.command()
@click.argument("topic")
@click.option("--style", "-s", "style_name", default="insights", help="Style profile to use")
@click.option("--model", "-m", default=None, help="Claude model to use")
@click.option("--instructions", "-i", default="", help="Additional instructions")
@click.option("--max-sources", default=5, help="Max transcripts to weave from")
@click.option("--no-typefully", is_flag=True, help="Don't push to Typefully")
@click.option("--no-save", is_flag=True, help="Don't save to file")
def story(topic, style_name, model, instructions, max_sources, no_typefully, no_save):
    """Synthesize an original narrative post from your entire library.

    \b
    Mines every transcript in your library for material related to TOPIC,
    then weaves the real facts, quotes and moments into one narrative post.
    Every claim is grounded in a real source — no inventions.

    \b
    Example:
        xcontent story "Steve Jobs pilgrimage to Japan"
        xcontent story "Rockefeller's obsession with cost accounting"
    """
    from .content_generator import generate_story

    console.print(f"\n[bold]Mining your library for: [cyan]{topic}[/cyan][/bold]\n")

    try:
        with console.status("Searching library, extracting material, weaving story..."):
            post, sources = generate_story(
                topic=topic,
                style_name=style_name,
                model=model,
                additional_instructions=instructions,
                max_sources=max_sources,
            )
    except ValueError as e:
        console.print(f"[yellow]{e}[/yellow]")
        return
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if sources:
        console.print(f"[dim]Wove material from {len(sources)} source(s):[/dim]")
        for s in sources:
            console.print(f"  [dim]- {s['video_title']} ({s.get('channel', '')})[/dim]")
        console.print()

    console.print(f"[bold green]── STORY ──[/bold green]\n")
    console.print(post)
    console.print()

    try:
        import subprocess
        subprocess.run(["pbcopy"], input=post.encode(), check=True)
        console.print("[green]Copied to clipboard.[/green]")
    except Exception:
        pass

    if not no_save:
        from pathlib import Path as P
        from .content_generator import _slugify

        content_dir = P(__file__).resolve().parent.parent / "content"
        content_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        slug = _slugify(topic)
        base = f"{timestamp}_story_{slug}"

        txt_path = content_dir / f"{base}.txt"
        txt_path.write_text(post)

        import json as _json
        meta = {
            "style": style_name,
            "content_type": "story",
            "topic": topic,
            "sources": [s.get("video_title", "") for s in sources],
            "generated_at": datetime.now().isoformat(),
        }
        meta_path = content_dir / f"{base}.meta.json"
        meta_path.write_text(_json.dumps(meta, indent=2))
        console.print(f"[dim]Saved to: {txt_path}[/dim]")

        try:
            from .knowledge_base import save_post
            save_post(
                style=style_name,
                content=post,
                content_type="story",
                topic=topic,
                source_videos=" | ".join(s.get("video_title", "") for s in sources),
                command="story",
            )
        except Exception:
            pass

    if not no_typefully:
        try:
            from .typefully import create_draft
            with console.status("Pushing to Typefully..."):
                create_draft(post)
            console.print("[green]Pushed to Typefully as a draft.[/green]")
        except RuntimeError as e:
            if "TYPEFULLY_API_KEY not set" in str(e):
                pass
            else:
                console.print(f"[yellow]Typefully: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Typefully push failed: {e}[/yellow]")


# ── Ingest Command (Bulk Import) ──────────────────────────────────


def _ingest_channel(channel_handle: str, channel_name: str, limit: int) -> tuple[int, int]:
    """Ingest transcripts from a single channel. Returns (success, skipped) counts."""
    from .knowledge_base import get_transcript_text, save_transcript
    from .source_manager import list_channel_videos

    try:
        videos = list_channel_videos(channel_handle, max_results=limit)
    except Exception as e:
        console.print(f"  [red]Error listing channel: {e}[/red]")
        return 0, 0

    new_videos = [v for v in videos if not get_transcript_text(v["video_id"])]

    if not new_videos:
        console.print(f"  [dim]All {len(videos)} videos already stored.[/dim]")
        return 0, 0

    console.print(f"  [cyan]{len(new_videos)} new videos ({len(videos) - len(new_videos)} already stored)[/cyan]")

    from youtube_transcript_api import YouTubeTranscriptApi
    ytt_api = YouTubeTranscriptApi()

    success = 0
    skipped = 0
    for i, v in enumerate(new_videos, 1):
        try:
            transcript = ytt_api.fetch(v["video_id"], languages=["en"])
            text = " ".join(entry.text for entry in transcript.snippets)
            save_transcript(v["video_id"], v["title"], text, v["channel"])
            success += 1
        except Exception:
            skipped += 1

    console.print(f"  [green]{success} added, {skipped} skipped[/green]")
    return success, skipped


@cli.command()
@click.argument("channel", required=False)
@click.option("--all", "ingest_all", is_flag=True, help="Ingest from all channels in channels.json")
@click.option("--limit", "-n", default=100, help="Max videos per channel")
def ingest(channel, ingest_all, limit):
    """Bulk-import transcripts from YouTube channels into your library.

    \b
    Single channel:
        xcontent ingest "@founderspodcast" --limit 50

    \b
    All saved channels (from channels.json):
        xcontent ingest --all --limit 50
    """
    import json as _json

    from .knowledge_base import count_transcripts

    if not channel and not ingest_all:
        console.print("[red]Provide a channel or use --all to ingest from all saved channels.[/red]")
        return

    before = count_transcripts()

    if ingest_all:
        channels_file = Path(__file__).resolve().parent.parent / "channels.json"
        if not channels_file.exists():
            console.print("[red]channels.json not found. Create it in the project root.[/red]")
            return

        channels = _json.loads(channels_file.read_text())
        console.print(f"\n[bold]Ingesting from {len(channels)} channels (limit {limit} per channel)...[/bold]\n")

        total_success = 0
        total_skipped = 0
        for ch in channels:
            name = ch.get("name", ch.get("handle", ""))
            handle = ch.get("handle", ch.get("url", ""))
            console.print(f"[bold]{name}[/bold] ({handle})")
            s, sk = _ingest_channel(handle, name, limit)
            total_success += s
            total_skipped += sk
            console.print()

        after = count_transcripts()
        console.print(f"[bold green]Done. Added {total_success} transcripts total ({total_skipped} skipped).[/bold green]")
        console.print(f"[dim]Library: {before} → {after} transcripts.[/dim]")
    else:
        console.print(f"\n[bold]Ingesting from channel...[/bold]\n")
        console.print(f"[bold]{channel}[/bold]")
        s, sk = _ingest_channel(channel, channel, limit)
        after = count_transcripts()
        console.print(f"\n[bold green]Done. Added {s} transcripts ({sk} skipped).[/bold green]")
        console.print(f"[dim]Library: {before} → {after} transcripts.[/dim]")


# ── Auto Command (Generate from Library) ─────────────────────────


@cli.command()
@click.option("--style", "-s", "style_name", default="insights", help="Style profile to use")
@click.option("--count", "-n", default=10, help="Number of posts to generate")
@click.option("--type", "-T", "content_type", default="insights",
              type=click.Choice(["insights", "essays", "transcripts", "quote-tweets"]),
              help="Content format")
@click.option("--model", "-m", default=None, help="Claude model to use")
@click.option("--instructions", "-i", default="", help="Additional instructions")
@click.option("--no-typefully", is_flag=True, help="Don't push to Typefully")
@click.option("--mine", default=5, help="Max unmined transcripts to process if ideas run low")
def auto(style_name, count, content_type, model, instructions, no_typefully, mine):
    """Auto-generate posts from your library — no links needed.

    \b
    Picks unused ideas from your transcript library, diversifies across
    different founders, generates posts through a quality gate, and
    only shows you the ones that pass.

    \b
    Fill your library first with 'xcontent ingest', then:
        xcontent auto --count 20 --style insights --no-typefully
    """
    from .knowledge_base import count_transcripts, get_unused_ideas

    total_transcripts = count_transcripts()
    if total_transcripts == 0:
        console.print("[red]Your library is empty. Run 'xcontent ingest <channel>' first.[/red]")
        return

    unused = get_unused_ideas(limit=1)
    console.print(f"\n[bold]Auto-generating {count} posts from your library[/bold]")
    console.print(f"[dim]{total_transcripts} transcripts available[/dim]\n")

    from .content_generator import generate_auto

    def on_progress(step, current, total):
        if step == "mining":
            console.print("[dim]  Mining new transcript for ideas...[/dim]")
        elif step == "generating":
            console.print(f"[dim]  Generating post {current}/{total}...[/dim]")

    try:
        results = generate_auto(
            style_name=style_name,
            content_type=content_type,
            count=count,
            model=model,
            additional_instructions=instructions,
            mine_new=mine,
            on_progress=on_progress,
        )
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        return

    if not results:
        console.print("[yellow]No posts generated. Add more transcripts with 'xcontent ingest'.[/yellow]")
        return

    passed = [r for r in results if r["passed"]]
    failed = [r for r in results if not r["passed"]]

    console.print(f"\n[bold green]Generated {len(results)} posts ({len(passed)} passed quality, {len(failed)} flagged).[/bold green]\n")

    for i, r in enumerate(results, 1):
        status = "[green]PASS[/green]" if r["passed"] else f"[yellow]FLAGGED ({r['score']})[/yellow]"
        console.print(f"[bold cyan]── Post {i} ── {status} ── {r['topic'][:50]} ──[/bold cyan]\n")
        console.print(r["content"])
        if r["issues"]:
            console.print(f"\n[dim]Issues: {'; '.join(r['issues'][:3])}[/dim]")
        console.print(f"[dim]Score: {r['score']} | Source: {r['video_title'][:40]}[/dim]")
        console.print(f"[dim]Saved: {r['file_path']}[/dim]\n")

    # Copy passed posts to clipboard
    try:
        import subprocess
        clipboard = "\n\n---\n\n".join(r["content"] for r in passed)
        subprocess.run(["pbcopy"], input=clipboard.encode(), check=True)
        console.print(f"[green]{len(passed)} quality posts copied to clipboard.[/green]")
    except Exception:
        pass

    # Push passed posts to Typefully
    if not no_typefully and passed:
        try:
            from .typefully import push_drafts
            with console.status(f"Pushing {len(passed)} drafts to Typefully..."):
                drafts = push_drafts([r["content"] for r in passed])
            console.print(f"[green]Pushed {len(drafts)} drafts to Typefully.[/green]")
        except RuntimeError as e:
            if "TYPEFULLY_API_KEY not set" in str(e):
                pass
            else:
                console.print(f"[yellow]Typefully: {e}[/yellow]")
        except Exception as e:
            console.print(f"[yellow]Typefully push failed: {e}[/yellow]")

    # Summary table
    console.print()
    table = Table(title="Summary")
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", width=6)
    table.add_column("Status", width=8)
    table.add_column("Topic", max_width=40)
    table.add_column("Source", style="dim", max_width=30)

    for i, r in enumerate(results, 1):
        status = "PASS" if r["passed"] else "FLAG"
        style = "green" if r["passed"] else "yellow"
        table.add_row(str(i), str(r["score"]), f"[{style}]{status}[/{style}]",
                       r["topic"][:40], r["video_title"][:30])

    console.print(table)


# ── Sync Edits (Edit Detection from Typefully) ──────────────────────


@cli.command("sync-edits")
@click.option("--style", "-s", "style_name", default="insights", help="Style to tag feedback as")
@click.option("--type", "-T", "content_type", default="insights", help="Content type to tag feedback as")
@click.option("--dry-run", is_flag=True, help="Show matches without saving feedback")
def sync_edits(style_name, content_type, dry_run):
    """Pull published posts from Typefully and learn from your edits.

    \b
    Compares what you actually posted vs what the system generated.
    Every edit you made becomes a training signal — the system learns
    your corrections automatically.

    \b
    Run this after you've published some posts:
        xcontent sync-edits
        xcontent sync-edits --dry-run   # preview without saving
    """
    from .knowledge_base import (
        count_feedback,
        find_matching_post,
        is_draft_synced,
        mark_draft_synced,
        save_feedback,
    )
    from .typefully import get_published_drafts

    console.print("\n[bold]Pulling published posts from Typefully...[/bold]")

    try:
        published = get_published_drafts(limit=50)
    except Exception as e:
        console.print(f"[red]Error fetching from Typefully: {e}[/red]")
        return

    if not published:
        console.print("[yellow]No published posts found on Typefully.[/yellow]")
        return

    console.print(f"[green]Found {len(published)} published posts.[/green]\n")

    new_count = 0
    skip_count = 0
    no_match_count = 0
    identical_count = 0
    feedback_before = count_feedback()

    for post in published:
        draft_id = post["id"]

        if is_draft_synced(draft_id):
            skip_count += 1
            continue

        published_text = post["text"]
        match = find_matching_post(published_text)

        if not match:
            no_match_count += 1
            if not dry_run:
                mark_draft_synced(draft_id, 0, 0.0)
            continue

        similarity = match["similarity"]

        if similarity >= 0.95:
            identical_count += 1
            if not dry_run:
                mark_draft_synced(draft_id, match["id"], similarity)
            continue

        # Found edited post — this is the gold
        new_count += 1
        topic = match.get("topic", "")[:40]
        console.print(f"  [green]Match:[/green] {topic} — [cyan]{similarity:.0%} similar[/cyan]")

        # Show a brief diff preview
        gen_preview = match["content"][:80].replace("\n", " ")
        pub_preview = published_text[:80].replace("\n", " ")
        console.print(f"    [dim]Generated: {gen_preview}...[/dim]")
        console.print(f"    [dim]Posted:    {pub_preview}...[/dim]")

        if not dry_run:
            save_feedback(
                style=style_name,
                content_type=content_type,
                generated_text=match["content"],
                posted_text=published_text,
                video_title=match.get("video_title", ""),
            )
            mark_draft_synced(draft_id, match["id"], similarity)

    console.print()
    action = "Would save" if dry_run else "Saved"
    console.print(f"[bold green]{action} {new_count} edit pair(s) as feedback.[/bold green]")
    if identical_count:
        console.print(f"[dim]{identical_count} posts published without edits (no feedback needed).[/dim]")
    if no_match_count:
        console.print(f"[dim]{no_match_count} posts didn't match any generated content (written manually?).[/dim]")
    if skip_count:
        console.print(f"[dim]{skip_count} already synced.[/dim]")

    if not dry_run and new_count > 0:
        total = count_feedback()
        console.print(f"\n[bold]Feedback bank: {feedback_before} → {total} pairs.[/bold]")
        console.print("[dim]These edits will be injected into future generation prompts automatically.[/dim]")


# ── Library Commands (Knowledge Base) ──────────────────────────────


@cli.group()
def library():
    """Your transcript library — search past videos without re-fetching."""
    pass


@library.command("list")
@click.option("--limit", "-n", default=30, help="Number of transcripts to show")
def library_list(limit):
    """List all stored transcripts."""
    from .knowledge_base import list_transcripts

    transcripts = list_transcripts(limit)
    if not transcripts:
        console.print("[yellow]No transcripts stored yet. They auto-save when you use --video.[/yellow]")
        return

    table = Table(title=f"Transcript Library ({len(transcripts)} stored)")
    table.add_column("Video ID", style="dim", width=12)
    table.add_column("Title", style="cyan", max_width=50)
    table.add_column("Channel")
    table.add_column("Length", justify="right")
    table.add_column("Fetched", style="dim")

    for t in transcripts:
        length = f"{t['char_count']:,} chars"
        table.add_row(t["video_id"], t["video_title"][:50], t["channel"], length, t["fetched_at"][:10])

    console.print(table)


@library.command("search")
@click.argument("query")
@click.option("--limit", "-n", default=10, help="Max results")
def library_search(query, limit):
    """Search across all stored transcripts (free, no API tokens)."""
    from .knowledge_base import search_transcripts

    results = search_transcripts(query, limit)
    if not results:
        console.print(f"[yellow]No matches for '{query}' in your library.[/yellow]")
        return

    console.print(f"\n[bold]Found {len(results)} matches for '{query}':[/bold]\n")
    for i, r in enumerate(results, 1):
        console.print(f"  [cyan]{i}[/cyan]. [bold]{r['video_title']}[/bold] — {r['channel']}")
        console.print(f"     [dim]{r['video_id']} | {r['char_count']:,} chars | fetched {r['fetched_at'][:10]}[/dim]")
        if r.get("excerpt"):
            console.print(f"     {r['excerpt']}")
        console.print()


@library.command("ideas")
@click.option("--video", "-v", "video_id", default=None, help="Filter by video ID")
@click.option("--limit", "-n", default=30, help="Max results")
def library_ideas(video_id, limit):
    """Show unused ideas from past extractions."""
    from .knowledge_base import get_unused_ideas

    ideas = get_unused_ideas(video_id, limit)
    if not ideas:
        console.print("[yellow]No unused ideas. Run a batch to extract some.[/yellow]")
        return

    table = Table(title=f"Unused Ideas ({len(ideas)})")
    table.add_column("#", style="dim", width=4)
    table.add_column("Idea", style="cyan", max_width=50)
    table.add_column("Video", max_width=30)
    table.add_column("Angle", max_width=40, style="dim")

    for idea in ideas:
        table.add_row(str(idea["id"]), idea["title"], idea.get("video_title", "")[:30], idea["angle"][:40])

    console.print(table)


@library.command("posts")
@click.option("--limit", "-n", default=30, help="Number of posts to show")
@click.option("--style", "-s", "style_name", default="", help="Filter by style")
@click.option("--search", "search_query", default="", help="Full-text search posts")
def library_posts(limit, style_name, search_query):
    """List or search the posts you've generated."""
    from .knowledge_base import list_posts, search_posts, count_posts

    total = count_posts()
    if total == 0:
        console.print("[yellow]No posts saved yet. Generate some with 'write', 'batch', 'story', or 'quote-reply'.[/yellow]")
        return

    if search_query:
        rows = search_posts(search_query, limit=limit)
        if not rows:
            console.print(f"[yellow]No posts match '{search_query}'.[/yellow]")
            return
        console.print(f"\n[bold]{len(rows)} posts matching '{search_query}':[/bold]\n")
        for r in rows:
            console.print(f"  [cyan]#{r['id']}[/cyan] [bold]{r['topic'] or '(no topic)'}[/bold] "
                          f"[dim]{r['style']}/{r['content_type']} — {r['created_at'][:10]}[/dim]")
            if r.get("excerpt"):
                console.print(f"     {r['excerpt']}")
            console.print()
        return

    rows = list_posts(limit=limit, style=style_name)
    console.print(f"\n[bold]Recent posts ({len(rows)} of {total}):[/bold]\n")
    table = Table()
    table.add_column("#", style="cyan", width=5)
    table.add_column("When", style="dim", width=10)
    table.add_column("Style", width=12)
    table.add_column("Cmd", width=11)
    table.add_column("Topic", max_width=35)
    table.add_column("Preview", style="dim", max_width=50)
    for r in rows:
        table.add_row(
            str(r["id"]),
            r["created_at"][:10],
            r["style"],
            r.get("command", "") or "",
            (r["topic"] or r.get("video_title", ""))[:35],
            (r.get("preview") or "").replace("\n", " ")[:50],
        )
    console.print(table)


@library.command("post")
@click.argument("post_id", type=int)
def library_post(post_id):
    """Show a single saved post by id."""
    from .knowledge_base import get_post

    row = get_post(post_id)
    if not row:
        console.print(f"[red]No post with id {post_id}.[/red]")
        return

    console.print(f"\n[bold]Post #{row['id']}[/bold]")
    console.print(f"[dim]{row['style']}/{row['content_type']} — {row['created_at']}[/dim]")
    if row.get("topic"):
        console.print(f"[dim]Topic: {row['topic']}[/dim]")
    if row.get("video_title"):
        console.print(f"[dim]Source: {row['video_title']}[/dim]")
    if row.get("source_videos"):
        console.print(f"[dim]Sources: {row['source_videos']}[/dim]")
    console.print()
    console.print(row["content"])
    console.print()


# ── Feedback Command ──────────────────────────────────────────────────


@cli.command()
@click.argument("generated_file")
@click.argument("posted_text_or_file")
@click.option("--style", "-s", "style_name", required=True, help="Style this was for")
@click.option("--type", "-T", "content_type", default="insights",
              type=click.Choice(["insights", "essays", "transcripts", "quote-tweets"]))
def feedback(generated_file, posted_text_or_file, style_name, content_type):
    """Teach the system by showing what you actually posted vs what it generated.

    \b
    GENERATED_FILE: path to the .txt file that was generated
    POSTED_TEXT_OR_FILE: either a file path or the actual posted text in quotes
    """
    from pathlib import Path as P

    from .knowledge_base import save_feedback

    # Read generated
    gen_path = P(generated_file)
    if not gen_path.exists():
        console.print(f"[red]File not found: {generated_file}[/red]")
        return
    generated_text = gen_path.read_text()

    # Read posted — could be a file or raw text
    posted_path = P(posted_text_or_file)
    if posted_path.exists():
        posted_text = posted_path.read_text()
    else:
        posted_text = posted_text_or_file

    save_feedback(style_name, content_type, generated_text, posted_text)
    console.print(f"[green]Feedback saved. The system will learn from your edits.[/green]")
    console.print(f"[dim]You now have more training data for '{style_name}' / {content_type}.[/dim]")


def main():
    cli()


if __name__ == "__main__":
    main()
