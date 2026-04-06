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

import sys

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
@click.option("--video", "-v", "video_id", default=None, help="YouTube video ID to use as source")
@click.option("--topic", "-t", default="", help="What the post should be about")
@click.option("--focus", "-f", default="", help="Specific angle or moment to focus on")
@click.option("--type", "-T", "content_type", default="insights",
              type=click.Choice(["insights", "essays", "transcripts", "quote-tweets"]),
              help="Content format")
@click.option("--instructions", "-i", default="", help="Additional instructions")
@click.option("--transcript-file", default=None, help="Path to a transcript file (instead of --video)")
@click.option("--model", "-m", default=None, help="Claude model to use")
@click.option("--no-save", is_flag=True, help="Don't save the output to a file")
def write(style_name, video_id, topic, focus, content_type, instructions, transcript_file, model, no_save):
    """Generate content in your style from a source transcript."""
    from .content_generator import generate, generate_and_save
    from .source_manager import get_transcript, get_video_details

    # Get transcript
    if transcript_file:
        with open(transcript_file) as f:
            transcript_text = f.read()
        video_title = transcript_file
    elif video_id:
        try:
            with console.status("Fetching video info and transcript..."):
                details = get_video_details(video_id)
                video_title = details["title"]
                transcript_text = get_transcript(video_id)
            console.print(f"[green]Source:[/green] {video_title}")
            console.print(f"[dim]Transcript: {len(transcript_text)} characters[/dim]")
            if len(transcript_text) > 15_000:
                console.print(f"[dim]Will extract key material first to save costs[/dim]\n")
            else:
                console.print()
        except Exception as e:
            console.print(f"[red]Error: {e}[/red]")
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

    console.print(Panel(content, title=f"{content_type.upper()} Post", border_style="green"))

    if path:
        console.print(f"\n[dim]Saved to: {path}[/dim]")


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
        meta = data.get("metadata", {})
        table.add_row(
            meta.get("generated_at", "")[:16],
            meta.get("style", "?"),
            meta.get("content_type", "?"),
            meta.get("topic", meta.get("video_title", ""))[:40],
            f.name,
        )

    console.print(table)


def main():
    cli()


if __name__ == "__main__":
    main()
