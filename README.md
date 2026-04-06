# XContent — Content System for Found Remote

Your style is the template. YouTube channels are the raw material. AI does the assembly.

Go from idea to finished post in minutes instead of an hour of back-and-forth.

## How It Works

### 1. Style In
Paste 3-5 example posts that represent your writing style. Hooks, tone, structure — everything gets saved permanently.

```bash
xcontent style add linkedin-style
# Paste your examples interactively

# Or load from files:
xcontent style add linkedin-style -f example1.txt -f example2.txt -f example3.txt
```

### 2. Sources In
Add YouTube channels. Search their entire catalog from one place.

```bash
xcontent source add @FoundersPodcast
xcontent source add "https://youtube.com/@DavidSenra"
xcontent source list
```

### 3. Content Out
Search a topic, pick a video, and generate content in your style.

```bash
# Search across all your channels
xcontent search "Bezos customer obsession"

# Fetch a transcript
xcontent transcript VIDEO_ID

# Generate a post
xcontent write --style linkedin-style --video VIDEO_ID --topic "Bezos on customer obsession"

# Be specific about what to focus on
xcontent write --style linkedin-style --video VIDEO_ID --focus "the near-death moment in 2001"

# Different content types
xcontent write --style linkedin-style --video VIDEO_ID --type twitter
xcontent write --style linkedin-style --video VIDEO_ID --type thread
xcontent write --style linkedin-style --video VIDEO_ID --type newsletter

# Use a local transcript file instead of YouTube
xcontent write --style linkedin-style --transcript-file episode.txt --topic "lessons from Sam Walton"
```

## Setup

### 1. Install
```bash
pip install -e .
```

### 2. API Keys
Copy `.env.example` to `.env` and add your keys:

```bash
cp .env.example .env
```

You need:
- **YouTube Data API v3 key** — [Get one here](https://console.cloud.google.com/apis/credentials) (enable "YouTube Data API v3")
- **Anthropic API key** — [Get one here](https://console.anthropic.com/settings/keys)

### 3. Verify
```bash
xcontent style list
xcontent source list
```

## Commands Reference

| Command | What it does |
|---|---|
| `xcontent style add <name>` | Save a writing style from example posts |
| `xcontent style list` | List all saved styles |
| `xcontent style show <name>` | View a style's examples |
| `xcontent style remove <name>` | Delete a style |
| `xcontent source add <channel>` | Add a YouTube channel |
| `xcontent source list` | List saved channels |
| `xcontent source remove <id>` | Remove a channel |
| `xcontent search <query>` | Search videos across channels |
| `xcontent transcript <video_id>` | Fetch a video transcript |
| `xcontent write --style <s>` | Generate content |
| `xcontent history` | View previously generated content |

## Content Types

- `linkedin` — Single LinkedIn post (default)
- `twitter` — Single tweet (280 chars)
- `thread` — Twitter/X thread (5-12 tweets)
- `newsletter` — Long-form essay (500-1500 words)
