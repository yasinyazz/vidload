# vidload

A terminal UI video downloader built with [Textual](https://github.com/Textualize/textual). Supports YouTube, Vimeo, SoundCloud, and 1000+ other sites via [yt-dlp](https://github.com/yt-dlp/yt-dlp), plus Spotify tracks, albums, and playlists via [spotdl](https://github.com/spotDL/spotify-downloader).

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ vidload                                                          12:34:56   │
├─────────────────────────────────────────────────────────────────────────────┤
│ [ Paste URL here (YouTube, Vimeo, SoundCloud, Spotify…) ] [Quality▾][Paste]│
│ ⬇ Rick Astley — Never Gonna ████████████░░░  12.3 MB / 45.1 MB  3.2 MB/s  │
├──────────────────────┬──────────────────────────────────────────────────────┤
│ ━━  Preview          │ ━━  Download Queue        ↑↓ navigate  Del remove   │
│                      │  #  Title           Quality  Status   Progress  Size │
│ Never Gonna Give … │  1  Never Gonna…    720p     DONE     100%     44MB  │
│ ─────────────────    │  2  Lo-fi playlist  Best     QUEUED   —         —   │
│ Channel: RickAstley  │  3  My Playlist ♪  Spotify  QUEUED   —         —   │
│ Duration: 03:32      │                                                      │
│ Views: 1,432,198,004 │                                                      │
│ Date: 1987-07-27     │                                                      │
├──────────────────────┴──────────────────────────────────────────────────────┤
│ ━━  Log                                                                     │
│ [12:34:12] Preview ready (video): Never Gonna Give You Up                  │
│ [12:34:15] ✓ Saved: Never Gonna Give You Up  →  ~/Downloads/vidload        │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Features

- **Preview before downloading** — fetch title, channel, duration, view count, upload date, and description before a single byte is downloaded
- **Playlist & album support** — YouTube playlists and Spotify albums/playlists expand into a selectable track list; pick exactly which items you want
- **Spotify support** — paste any `open.spotify.com` track, album, or playlist URL; routes through spotdl and matches each song from YouTube Music with full ID3 tags and album art
- **Download queue** — queue up as many URLs as you want; they download one by one automatically
- **Pause / Resume** — suspend and resume the active download mid-stream with a button or `Space`
- **Delete from queue** — navigate with arrow keys and press `Delete` to remove any item, including the one currently downloading (cancels it cleanly and starts the next)
- **Live progress** — real-time progress bar, downloaded / total file size, speed, and ETA
- **Quality selector** — Best, 1080p, 720p, 480p, 360p, Audio MP3, Audio M4A
- **Clipboard paste** — `Ctrl+V` reads from your Wayland or X11 clipboard automatically
- **Toggleable log panel** — detailed per-event log at the bottom, hideable with `Ctrl+L`
- **Clear done** — one keystroke to sweep finished and errored items out of the queue

## Requirements

- Python 3.10+
- ffmpeg (for merging video+audio streams and audio extraction)

```bash
# Arch Linux
sudo pacman -S ffmpeg python

# Debian / Ubuntu
sudo apt install ffmpeg python3
```

## Installation

### Quick start (no install)

```bash
pip install yt-dlp textual --break-system-packages
python vidload.py
```

### System-wide via PKGBUILD (Arch Linux)

```bash
git clone https://github.com/yasinyazz/vidload
cd vidload
makepkg -si
```

After installing, run `vidload` from anywhere or launch it from your application menu.

### Spotify support (optional)

Spotify downloads require `spotdl` and a free Spotify Developer app:

```bash
pip install spotdl --break-system-packages
```

Then authenticate once:

1. Go to [developer.spotify.com/dashboard](https://developer.spotify.com/dashboard) and create a free app
2. Copy your **Client ID** and **Client Secret**
3. Run:

```bash
spotdl --client-id YOUR_CLIENT_ID --client-secret YOUR_CLIENT_SECRET save
```

After that, Spotify URLs just work — no extra steps per session.

## Usage

```bash
python vidload.py
# or, after system install:
vidload
```

1. Paste a URL into the input bar (or press `Ctrl+V` to paste from clipboard)
2. Press `Ctrl+P` or click **🔍 Preview** to fetch metadata
3. For playlists/albums, tick the tracks you want in the preview panel
4. Select a quality from the dropdown
5. Click **⬇ Download** to add to the queue

Downloads are saved to `~/Downloads/vidload/`.

## Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+P` | Preview the URL in the input bar |
| `Ctrl+V` | Paste URL from clipboard |
| `Enter` | Preview (when focused on the URL bar) |
| `Space` | Pause / Resume active download |
| `↑` / `↓` | Navigate the download queue |
| `Delete` | Remove highlighted queue item (cancels if active) |
| `Ctrl+D` | Clear all finished / errored items |
| `Ctrl+L` | Toggle the log panel |
| `Escape` | Clear the URL input and preview panel |
| `Ctrl+Q` | Quit |

## Supported sites

Any site supported by yt-dlp works, including YouTube, YouTube Music, Vimeo, SoundCloud, Twitter/X, Reddit, TikTok, Twitch clips, and [thousands more](https://github.com/yt-dlp/yt-dlp/blob/master/supportedsites.md).

Spotify tracks, albums, and playlists are handled separately via spotdl (requires setup above).

## Dependencies

| Package | Purpose |
|---------|---------|
| [yt-dlp](https://github.com/yt-dlp/yt-dlp) | Downloading from YouTube and 1000+ sites |
| [textual](https://github.com/Textualize/textual) | Terminal UI framework |
| [spotdl](https://github.com/spotDL/spotify-downloader) | Spotify support (optional) |
| ffmpeg | Merging video+audio, audio extraction |

## License

MIT
