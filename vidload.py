#!/usr/bin/env python3
"""
vidload - TUI video downloader
Supports YouTube/Vimeo/etc via yt-dlp and Spotify via spotdl
"""

import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from datetime import datetime

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, ScrollableContainer
from textual.widgets import (
    Header, Footer, Input, Button, Label,
    Select, DataTable, ProgressBar, Log,
    SelectionList, Static, LoadingIndicator,
)
from textual.widgets.selection_list import Selection
from textual import on, work
from rich.text import Text

try:
    import yt_dlp
except ImportError:
    raise SystemExit("yt-dlp not found. Install it: pip install yt-dlp")

# ─────────────────────────── constants ───────────────────────────

DOWNLOAD_DIR = Path.home() / "Downloads" / "vidload"
DOWNLOAD_DIR.mkdir(parents=True, exist_ok=True)

QUALITY_OPTIONS = [
    ("Best quality",  "bestvideo+bestaudio/best"),
    ("1080p",         "bestvideo[height<=1080]+bestaudio/best[height<=1080]"),
    ("720p",          "bestvideo[height<=720]+bestaudio/best[height<=720]"),
    ("480p",          "bestvideo[height<=480]+bestaudio/best[height<=480]"),
    ("360p",          "bestvideo[height<=360]+bestaudio/best[height<=360]"),
    ("Audio — MP3",   "bestaudio/best"),
    ("Audio — M4A",   "bestaudio[ext=m4a]/bestaudio"),
]

STATUS_STYLE = {
    "queued":      "dim",
    "downloading": "bold yellow",
    "paused":      "bold magenta",
    "merging":     "bold cyan",
    "done":        "bold green",
    "error":       "bold red",
}

SPOTIFY_RE = re.compile(r"https?://open\.spotify\.com/")


# ─────────────────────────── utilities ───────────────────────────

def fmt_size(n: int) -> str:
    """Format byte count as human-readable string."""
    if n <= 0:        return "—"
    if n >= 1 << 30:  return f"{n/(1<<30):.2f} GB"
    if n >= 1 << 20:  return f"{n/(1<<20):.1f} MB"
    if n >= 1 << 10:  return f"{n/(1<<10):.0f} KB"
    return f"{n} B"

def spotdl_available() -> bool:
    try:
        subprocess.run(["spotdl", "--version"], capture_output=True, timeout=3)
        return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


# ─────────────────────────── data classes ────────────────────────

class MediaInfo:
    """Unified metadata container for both yt-dlp and Spotify sources."""

    # ── from yt-dlp ─────────────────────────────────────────────
    @classmethod
    def from_ytdlp(cls, raw: dict) -> "MediaInfo":
        self = cls.__new__(cls)
        self.is_spotify  = False
        entries          = raw.get("entries")
        self.is_playlist = entries is not None
        if self.is_playlist:
            self.title        = raw.get("title", "Unknown playlist")
            self.uploader     = raw.get("uploader") or raw.get("channel") or "—"
            self.entries      = [e for e in list(entries) if e]
            self.count        = len(self.entries)
            self.duration_str = f"{self.count} videos"
            self.views        = "—"
            self.upload_date  = "—"
            self.description  = raw.get("description", "")[:200]
        else:
            self.title       = raw.get("title", "Unknown")
            self.uploader    = raw.get("uploader") or raw.get("channel") or "—"
            self.description = (raw.get("description") or "")[:280]
            secs             = raw.get("duration") or 0
            self.duration_str = (
                f"{secs//3600:02d}:{(secs%3600)//60:02d}:{secs%60:02d}" if secs else "—"
            )
            views            = raw.get("view_count")
            self.views       = f"{views:,}" if views else "—"
            rd               = raw.get("upload_date", "")
            self.upload_date = f"{rd[:4]}-{rd[4:6]}-{rd[6:]}" if len(rd) == 8 else "—"
            self.entries     = []
            self.count       = 1
        return self

    # ── from spotdl save JSON ────────────────────────────────────
    @classmethod
    def from_spotify(cls, songs: list, playlist_name: str = "") -> "MediaInfo":
        self = cls.__new__(cls)
        self.is_spotify  = True
        self.is_playlist = len(songs) > 1 or bool(playlist_name)
        self.entries     = songs   # list of spotdl song dicts
        self.count       = len(songs)
        self.views       = "—"
        self.upload_date = "—"
        if self.is_playlist:
            self.title        = playlist_name or f"{self.count} tracks"
            first             = songs[0] if songs else {}
            self.uploader     = first.get("artist", "—")
            self.description  = ""
            self.duration_str = f"{self.count} tracks"
        else:
            s                 = songs[0] if songs else {}
            self.title        = s.get("name", "Unknown")
            self.uploader     = s.get("artist", "—")
            album             = s.get("album_name", "")
            self.description  = f"Album: {album}" if album else ""
            secs              = int(s.get("duration", 0))
            self.duration_str = f"{secs//60}:{secs%60:02d}" if secs else "—"
        return self


class DownloadTask:
    def __init__(self, url: str, quality: str, title: str = "",
                 is_spotify: bool = False,
                 total_tracks: int = 1):
        self.url             = url
        self.quality         = quality
        self.title           = title or "Fetching…"
        self.status          = "queued"
        self.progress        = 0.0
        self.speed           = ""
        self.eta             = ""
        self.error           = ""
        self.added           = datetime.now().strftime("%H:%M:%S")
        # size tracking
        self.downloaded_bytes = 0
        self.total_bytes      = 0
        # spotify specifics
        self.is_spotify      = is_spotify
        self.total_tracks    = total_tracks   # >1 for spotify playlist tasks
        self.done_tracks     = 0

    @property
    def size_str(self) -> str:
        if self.is_spotify:
            if self.total_tracks > 1:
                return f"{self.done_tracks}/{self.total_tracks} tracks"
            return "—"
        if self.total_bytes > 0:
            dl  = fmt_size(self.downloaded_bytes)
            tot = fmt_size(self.total_bytes)
            return f"{dl} / {tot}"
        if self.downloaded_bytes > 0:
            return fmt_size(self.downloaded_bytes)
        return "—"


# ─────────────────────────── preview panel ───────────────────────

class PreviewPanel(Vertical):
    DEFAULT_CSS = """
    PreviewPanel {
        width: 44;
        border-right: solid $primary-darken-2;
        padding: 1 2;
        background: $panel;
    }
    #preview-heading { height: 2; color: $text-muted; text-style: bold; }
    #preview-spinner { height: 3; display: none; }
    #preview-body    { height: 1fr; }
    #preview-empty   {
        height: 6; color: $text-muted;
        content-align: center middle; text-align: center;
    }
    #preview-meta { height: auto; margin-bottom: 1; }
    #preview-playlist-heading {
        height: 2; margin-top: 1;
        color: $text-muted; text-style: bold; display: none;
    }
    #preview-playlist { height: 1fr; border: solid $primary-darken-2; display: none; }
    #preview-pl-btns  { height: 3; margin-top: 1; display: none; }
    #btn-sel-all  { width: 1fr; margin-right: 1; }
    #btn-sel-none { width: 1fr; }
    """

    def compose(self) -> ComposeResult:
        yield Label("━━  Preview", id="preview-heading")
        yield LoadingIndicator(id="preview-spinner")
        with ScrollableContainer(id="preview-body"):
            yield Static(
                "Paste a URL and press\n[bold]Ctrl+P[/bold] or [bold]🔍 Preview[/bold].",
                id="preview-empty",
            )
            yield Static("", id="preview-meta")
            yield Label("━━  Select tracks to download", id="preview-playlist-heading")
            yield SelectionList(id="preview-playlist")
            with Horizontal(id="preview-pl-btns"):
                yield Button("✓ All",  id="btn-sel-all",  variant="default")
                yield Button("✗ None", id="btn-sel-none", variant="default")

    def reset(self):
        self.query_one("#preview-empty").display            = True
        self.query_one("#preview-meta").display             = False
        self.query_one("#preview-playlist-heading").display = False
        self.query_one("#preview-playlist").display         = False
        self.query_one("#preview-pl-btns").display          = False

    def set_loading(self, state: bool):
        self.query_one("#preview-spinner").display = state

    def show(self, info: MediaInfo):
        self.set_loading(False)
        self.query_one("#preview-empty").display = False

        src_tag = "[green] ♪ Spotify[/green]" if info.is_spotify else ""
        ch_label = "Artist  :" if info.is_spotify else "Channel :"

        lines = [
            f"[bold]{info.title}[/bold]{src_tag}",
            f"[dim]{'─' * 38}[/dim]",
            f"[yellow]{ch_label}[/yellow]  {info.uploader}",
            f"[yellow]Duration:[/yellow]  {info.duration_str}",
        ]
        if not info.is_playlist:
            if not info.is_spotify:
                lines += [
                    f"[yellow]Views   :[/yellow]  {info.views}",
                    f"[yellow]Date    :[/yellow]  {info.upload_date}",
                ]
            if info.description:
                desc = info.description.replace("\n", " ")
                lines += ["", f"[dim]{desc[:240]}{'…' if len(desc)>240 else ''}[/dim]"]

        self.query_one("#preview-meta", Static).update("\n".join(lines))
        self.query_one("#preview-meta").display = True

        # Populate track list for playlists/albums
        if info.entries and (info.is_playlist or len(info.entries) > 1):
            sel: SelectionList = self.query_one("#preview-playlist", SelectionList)
            sel.clear_options()
            for i, entry in enumerate(info.entries):
                if info.is_spotify:
                    artist = entry.get("artist") or ""
                    name   = entry.get("name") or f"Track {i+1}"
                    label  = f"{i+1:>3}. {name[:36]}" + (f"  [{artist[:16]}]" if artist else "")
                else:
                    name  = entry.get("title") or entry.get("id") or f"Video {i+1}"
                    label = f"{i+1:>3}. {name[:48]}"
                sel.add_option(Selection(label, i, initial_state=True))
            self.query_one("#preview-playlist-heading").display = True
            sel.display = True
            self.query_one("#preview-pl-btns").display = True

    def selected_indices(self) -> list[int]:
        return list(self.query_one("#preview-playlist", SelectionList).selected)

    @on(Button.Pressed, "#btn-sel-all")
    def _all(self):  self.query_one("#preview-playlist", SelectionList).select_all()

    @on(Button.Pressed, "#btn-sel-none")
    def _none(self): self.query_one("#preview-playlist", SelectionList).deselect_all()


# ─────────────────────────── main app ────────────────────────────

class VidLoad(App):
    TITLE = "vidload"
    CSS = """
    Screen { background: $surface; }

    #top-panel {
        height: auto; padding: 1 2;
        background: $panel; border-bottom: solid $primary;
    }
    #url-row        { height: 3; margin-bottom: 1; }
    #url-input      { width: 1fr; margin-right: 1; }
    #quality-select { width: 20;  margin-right: 1; }
    #btn-paste      { width: 10;  margin-right: 1; }
    #btn-preview    { width: 13;  margin-right: 1; }
    #btn-download   { width: 14; }

    /* progress row */
    #progress-row { height: 3; align: left middle; }
    #prog-label   { width: 22; color: $text-muted; }
    #prog-bar     { width: 1fr; }
    #prog-size    { width: 20; text-align: center; color: $primary; }
    #prog-speed   { width: 22; text-align: right; color: $accent; }
    #btn-pause    { width: 12; margin-left: 1; display: none; }

    #main-split  { height: 1fr; }
    #queue-panel { height: 1fr; padding: 0 2; }
    #queue-header { height: 2; padding-top: 1; align: left middle; }
    #queue-title  { color: $text-muted; text-style: bold; width: auto; margin-right: 2; }
    #queue-hint   { color: $text-muted; width: 1fr; text-align: right; }
    DataTable    { height: 1fr; }

    #log-panel { height: 9; border-top: solid $primary; padding: 0 2; background: $panel; }
    #log-title { height: 2; padding-top: 1; color: $text-muted; text-style: bold; }
    Log        { height: 1fr; }
    """

    BINDINGS = [
        Binding("ctrl+p",  "preview",       "Preview"),
        Binding("ctrl+v",  "paste_clip",    "Paste"),
        Binding("space",   "pause",         "Pause/Resume", show=False),
        Binding("ctrl+d",  "clear_done",    "Clear done"),
        Binding("delete",  "delete_item",   "Delete row"),
        Binding("ctrl+l",  "toggle_log",    "Toggle log"),
        Binding("ctrl+q",  "quit",          "Quit"),
        Binding("escape",  "clear_all",     "Clear"),
    ]

    def __init__(self):
        super().__init__()
        self.tasks: list[DownloadTask] = []
        self._active: DownloadTask | None = None
        self._current_info: MediaInfo | None = None
        self._pause_event  = threading.Event()
        self._pause_event.set()
        self._cancel_event = threading.Event()   # set → abort current download
        self._spotdl_proc: subprocess.Popen | None = None

    # ── layout ───────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)

        with Vertical(id="top-panel"):
            with Horizontal(id="url-row"):
                yield Input(
                    placeholder="Paste URL  (YouTube, Vimeo, SoundCloud, Spotify…)",
                    id="url-input",
                )
                yield Select(
                    options=[(lbl, val) for lbl, val in QUALITY_OPTIONS],
                    value=QUALITY_OPTIONS[0][1],
                    id="quality-select",
                )
                yield Button("📋 Paste",    id="btn-paste",    variant="default")
                yield Button("🔍 Preview",  id="btn-preview",  variant="warning")
                yield Button("⬇ Download",  id="btn-download", variant="success")

            with Horizontal(id="progress-row"):
                yield Label("Idle", id="prog-label")
                yield ProgressBar(total=100, show_eta=False, id="prog-bar")
                yield Label("",     id="prog-size")
                yield Label("",     id="prog-speed")
                yield Button("⏸ Pause", id="btn-pause", variant="warning")

        with Horizontal(id="main-split"):
            yield PreviewPanel(id="preview-panel")
            with Vertical(id="queue-panel"):
                with Horizontal(id="queue-header"):
                    yield Label("━━  Download Queue", id="queue-title")
                    yield Label("[dim]↑↓ navigate   [bold]Del[/bold] remove[/dim]", id="queue-hint")
                yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)

        with Vertical(id="log-panel"):
            yield Label("━━  Log", id="log-title")
            yield Log(id="log-output", auto_scroll=True)

        yield Footer()

    def on_mount(self):
        t = self.query_one("#queue-table", DataTable)
        t.add_columns("  #", "Title", "Source / Quality", "Status", "Progress", "Size", "Added")
        self.query_one("#prog-bar", ProgressBar).update(progress=0)
        self._log("Ready — paste a URL, preview it, then hit Download.")

    # ── helpers ──────────────────────────────────────────────────

    def _log(self, msg: str):
        self.query_one("#log-output", Log).write_line(
            f"[{datetime.now().strftime('%H:%M:%S')}] {msg}"
        )

    def _source_label(self, task: DownloadTask) -> str:
        if task.is_spotify:
            return "Spotify ♪"
        return next((lbl for lbl, v in QUALITY_OPTIONS if v == task.quality), task.quality[:16])

    def _refresh_table(self):
        t = self.query_one("#queue-table", DataTable)
        t.clear()
        for i, task in enumerate(self.tasks, 1):
            sty  = STATUS_STYLE.get(task.status, "")
            if task.status in ("downloading", "paused", "merging"):
                prog = f"{task.progress:.1f}%"
            elif task.status == "done":
                prog = "100%"
            else:
                prog = "—"
            title = task.title[:48] + "…" if len(task.title) > 51 else task.title
            t.add_row(
                Text(f" {i}",                  style=sty),
                Text(title,                     style=sty),
                Text(self._source_label(task),  style="green" if task.is_spotify else sty),
                Text(task.status.upper(),        style=sty),
                Text(prog,                       style=sty),
                Text(task.size_str,              style="cyan" if task.total_bytes > 0 else "dim"),
                Text(task.added,                 style="dim"),
            )

    def _read_clipboard(self) -> str:
        for cmd in (
            ["wl-paste", "--no-newline"],
            ["xclip", "-selection", "clipboard", "-o"],
            ["xsel", "--clipboard", "--output"],
        ):
            try:
                r = subprocess.run(cmd, capture_output=True, text=True, timeout=2)
                if r.returncode == 0:
                    return r.stdout.strip()
            except (FileNotFoundError, subprocess.TimeoutExpired):
                pass
        return ""

    def _set_pause_btn(self, paused: bool):
        btn = self.query_one("#btn-pause", Button)
        btn.label   = "▶ Resume" if paused else "⏸ Pause"
        btn.variant = "success"  if paused else "warning"

    # ── actions ──────────────────────────────────────────────────

    def action_paste_clip(self):
        text = self._read_clipboard()
        if text and re.match(r"https?://", text):
            self.query_one("#url-input", Input).value = text
            self._log(f"Pasted: {text[:70]}")
        else:
            self._log("⚠  Clipboard doesn't contain a valid URL.")

    def action_preview(self): self._do_preview()
    def action_pause(self):   self._toggle_pause()

    def action_clear_done(self):
        self.tasks = [t for t in self.tasks if t.status not in ("done", "error")]
        self._refresh_table()
        self._log("Cleared finished tasks.")

    def action_delete_item(self):
        """Remove the highlighted queue row; cancels it if currently downloading."""
        table = self.query_one("#queue-table", DataTable)
        row   = table.cursor_row          # 0-based index of highlighted row
        if row < 0 or row >= len(self.tasks):
            return
        task = self.tasks[row]

        if task is self._active:
            # Signal the worker to abort, then reset progress UI
            self._cancel_event.set()
            self._pause_event.set()       # unblock if paused so the thread can see cancel
            if self._spotdl_proc and self._spotdl_proc.poll() is None:
                self._spotdl_proc.terminate()
            self._log(f"✗ Cancelled: {task.title[:60]}")
            self._active = None
            self._cancel_event.clear()
            self.query_one("#btn-pause",  Button).display = False
            self._set_pause_btn(False)
            self.query_one("#prog-label", Label).update("Idle")
            self.query_one("#prog-bar",   ProgressBar).update(progress=0)
            self.query_one("#prog-size",  Label).update("")
            self.query_one("#prog-speed", Label).update("")
        else:
            self._log(f"✗ Removed: {task.title[:60]}")

        self.tasks.pop(row)
        self._refresh_table()
        # keep cursor in bounds after deletion
        new_count = len(self.tasks)
        if new_count > 0:
            table.move_cursor(row=min(row, new_count - 1))
        # start next queued item if we just killed the active one
        self._process_queue()

    def action_toggle_log(self):
        self.query_one("#log-panel").display ^= True

    def action_clear_all(self):
        self.query_one("#url-input", Input).value = ""
        self._current_info = None
        self.query_one(PreviewPanel).reset()

    # ── pause / resume ───────────────────────────────────────────

    def _toggle_pause(self):
        if self._active is None:
            return
        if self._pause_event.is_set():
            self._pause_event.clear()
            self._active.status = "paused"
            self._set_pause_btn(True)
            short = self._active.title[:22] + "…" if len(self._active.title) > 22 else self._active.title
            self.query_one("#prog-label", Label).update(f"⏸ {short}")
            self.query_one("#prog-speed", Label).update("")
            self._log(f"⏸ Paused: {self._active.title[:50]}")
        else:
            self._pause_event.set()
            self._active.status = "downloading"
            self._set_pause_btn(False)
            self._log(f"▶ Resumed: {self._active.title[:50]}")
        self._refresh_table()

    # ── button events ─────────────────────────────────────────────

    @on(Button.Pressed, "#btn-paste")
    def _btn_paste(self):    self.action_paste_clip()

    @on(Button.Pressed, "#btn-preview")
    def _btn_preview(self):  self._do_preview()

    @on(Button.Pressed, "#btn-download")
    def _btn_download(self): self._queue_download()

    @on(Button.Pressed, "#btn-pause")
    def _btn_pause(self):    self._toggle_pause()

    @on(Input.Submitted, "#url-input")
    def _input_submit(self): self._do_preview()

    # ── preview ──────────────────────────────────────────────────

    def _do_preview(self):
        url = self.query_one("#url-input", Input).value.strip()
        if not url:
            self._log("⚠  No URL entered."); return
        if not re.match(r"https?://", url):
            self._log("⚠  URL must begin with http:// or https://"); return

        panel = self.query_one(PreviewPanel)
        panel.reset()
        panel.set_loading(True)
        self._log(f"Fetching info: {url[:70]}")

        if SPOTIFY_RE.match(url):
            self._fetch_spotify_info(url)
        else:
            self._fetch_ytdlp_info(url)

    # ── yt-dlp preview ────────────────────────────────────────────

    @work(thread=True)
    def _fetch_ytdlp_info(self, url: str):
        try:
            with yt_dlp.YoutubeDL({
                "quiet": True, "no_warnings": True,
                "extract_flat": "in_playlist", "skip_download": True,
            }) as ydl:
                raw = ydl.extract_info(url, download=False)
            self.call_from_thread(self._on_info_ready, MediaInfo.from_ytdlp(raw))
        except Exception as e:
            self.call_from_thread(self._on_info_error, str(e))

    # ── Spotify preview ───────────────────────────────────────────

    @work(thread=True)
    def _fetch_spotify_info(self, url: str):
        if not spotdl_available():
            self.call_from_thread(
                self._on_info_error,
                "spotdl not installed. Run: pip install spotdl --break-system-packages"
            )
            return
        tmp = tempfile.mktemp(suffix=".spotdl")
        try:
            r = subprocess.run(
                ["spotdl", "save", url, "--save-file", tmp],
                capture_output=True, text=True, timeout=60,
            )
            if not os.path.exists(tmp):
                raise RuntimeError(r.stderr.strip() or "spotdl returned no data")
            with open(tmp) as f:
                songs = json.load(f)
            os.unlink(tmp)
            if not songs:
                raise RuntimeError("No tracks found at that Spotify URL")

            # Try to get playlist name from stderr/stdout
            playlist_name = ""
            for line in (r.stdout + r.stderr).splitlines():
                m = re.search(r'playlist[:\s"]+([^"]+)"?', line, re.I)
                if m:
                    playlist_name = m.group(1).strip()
                    break

            info = MediaInfo.from_spotify(songs, playlist_name)
            self.call_from_thread(self._on_info_ready, info)
        except Exception as e:
            if os.path.exists(tmp):
                os.unlink(tmp)
            self.call_from_thread(self._on_info_error, str(e))

    def _on_info_ready(self, info: MediaInfo):
        self._current_info = info
        self.query_one(PreviewPanel).show(info)
        src  = "Spotify" if info.is_spotify else ("playlist" if info.is_playlist else "video")
        self._log(f"Preview ready ({src}): {info.title[:60]}")

    def _on_info_error(self, err: str):
        p = self.query_one(PreviewPanel)
        p.set_loading(False)
        p.reset()
        self._log(f"✗ Preview failed: {err[:140]}")

    # ── download queuing ──────────────────────────────────────────

    def _queue_download(self):
        url     = self.query_one("#url-input", Input).value.strip()
        quality = self.query_one("#quality-select", Select).value
        info    = self._current_info

        if not url or not re.match(r"https?://", url):
            self._log("⚠  Enter and preview a URL first."); return

        added = 0

        if info and info.is_spotify:
            selected = self.query_one(PreviewPanel).selected_indices()
            if not selected:
                self._log("⚠  No tracks selected."); return

            sel_songs = [info.entries[i] for i in selected if i < len(info.entries)]

            if len(sel_songs) == 1:
                s    = sel_songs[0]
                surl = s.get("url") or url
                self._add_task(surl, quality,
                               title=f"{s.get('name','')} — {s.get('artist','')}",
                               is_spotify=True, total_tracks=1,
                               spotify_songs=sel_songs)
            else:
                # Queue as one grouped Spotify task so the playlist downloads in sequence
                self._add_task(url, quality,
                               title=info.title,
                               is_spotify=True, total_tracks=len(sel_songs),
                               spotify_songs=sel_songs)
            added = len(sel_songs)
            self._log(f"Queued {added} Spotify track(s).")

        elif info and info.is_playlist and info.entries:
            selected = self.query_one(PreviewPanel).selected_indices()
            if not selected:
                self._log("⚠  No items selected."); return
            for idx in selected:
                entry = info.entries[idx]
                eurl  = entry.get("url") or entry.get("webpage_url") or entry.get("id", "")
                if eurl and not eurl.startswith("http"):
                    eurl = f"https://www.youtube.com/watch?v={eurl}"
                if eurl:
                    self._add_task(eurl, quality, title=entry.get("title") or f"Video {idx+1}")
                    added += 1
            self._log(f"Queued {added} video(s) from '{info.title}'.")

        else:
            title = info.title if info else ""
            self._add_task(url, quality, title=title)
            self._log(f"Queued: {title or url[:60]}")

        self.query_one("#url-input", Input).value = ""
        self._current_info = None
        self.query_one(PreviewPanel).reset()
        self._process_queue()

    def _add_task(self, url: str, quality: str, title: str = "",
                  is_spotify: bool = False, total_tracks: int = 1,
                  spotify_songs: list | None = None):
        task = DownloadTask(url=url, quality=quality, title=title,
                            is_spotify=is_spotify, total_tracks=total_tracks)
        task._spotify_songs = spotify_songs or []
        self.tasks.append(task)
        self._refresh_table()

    def _process_queue(self):
        if self._active is not None:
            return
        nxt = next((t for t in self.tasks if t.status == "queued"), None)
        if nxt:
            self._active = nxt
            self.query_one("#btn-pause", Button).display = True
            self._pause_event.set()
            self._cancel_event.clear()   # fresh start for new task
            if nxt.is_spotify:
                self._run_spotify_download(nxt)
            else:
                self._run_ytdlp_download(nxt)

    # ── yt-dlp download worker ────────────────────────────────────

    @work(thread=True)
    def _run_ytdlp_download(self, task: DownloadTask):
        is_audio = "bestaudio" in task.quality and "bestvideo" not in task.quality
        postprocessors = []
        if is_audio and "mp3" in task.quality:
            postprocessors.append({
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3", "preferredquality": "192",
            })
        elif not is_audio:
            postprocessors.append({"key": "FFmpegVideoConvertor", "preferedformat": "mp4"})

        def hook(d):
            self._pause_event.wait()   # blocks while paused
            if self._cancel_event.is_set():
                raise yt_dlp.utils.DownloadCancelled("Cancelled by user")

            if d["status"] == "downloading":
                task.status = "downloading"

                dl    = d.get("downloaded_bytes") or 0
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                task.downloaded_bytes = dl
                task.total_bytes      = total

                if total > 0:
                    task.progress = min((dl / total) * 100, 100.0)
                else:
                    pct = d.get("_percent_str", "").strip().replace("%","").replace("~","")
                    try:    task.progress = float(pct)
                    except: pass

                # speed
                speed = d.get("_speed_str", "").strip()
                if not speed:
                    bps = d.get("speed") or 0
                    if bps:
                        speed = (f"{bps/1e6:.1f} MB/s" if bps >= 1e6
                                 else f"{bps/1e3:.0f} KB/s")
                # eta
                eta = d.get("_eta_str", "").strip()
                if not eta:
                    s = d.get("eta") or 0
                    if s: eta = f"{s//60}:{s%60:02d}"

                task.speed = speed
                task.eta   = eta
                self.call_from_thread(self._on_progress, task)

            elif d["status"] == "finished":
                task.status   = "merging"
                task.progress = 100.0
                self.call_from_thread(self._on_progress, task)

        opts = {
            "format":              task.quality,
            "outtmpl":             str(DOWNLOAD_DIR / "%(title)s.%(ext)s"),
            "progress_hooks":      [hook],
            "postprocessors":      postprocessors,
            "quiet":               True,
            "no_warnings":         True,
            "merge_output_format": "mp4",
        }

        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                if task.title in ("Fetching…", ""):
                    raw = ydl.extract_info(task.url, download=False)
                    task.title = raw.get("title", task.url)[:80]
                ydl.download([task.url])
            task.status   = "done"
            task.progress = 100.0
        except yt_dlp.utils.DownloadCancelled:
            return   # task already removed from list by action_delete_item
        except Exception as e:
            task.status = "error"
            task.error  = str(e)
            self.call_from_thread(self._log, f"✗ {task.title[:50]}: {str(e)[:80]}")

        self.call_from_thread(self._on_done, task)

    # ── Spotify download worker ───────────────────────────────────

    @work(thread=True)
    def _run_spotify_download(self, task: DownloadTask):
        songs = task._spotify_songs
        total = len(songs)
        task.status      = "downloading"
        task.done_tracks = 0

        self.call_from_thread(self._on_progress, task)

        for i, song in enumerate(songs):
            # pause between tracks
            if not self._pause_event.is_set():
                task.status = "paused"
                self.call_from_thread(self._refresh_table)
                self._pause_event.wait()
                task.status = "downloading"

            song_url = song.get("url") or song.get("download_url", "")
            name     = f"{song.get('name','')} — {song.get('artist','')}"
            short    = name[:22] + "…" if len(name) > 22 else name

            # update label to show current track
            self.call_from_thread(
                self.query_one("#prog-label", Label).update, f"⬇  {short}"
            )

            try:
                # spotdl takes the spotify URL for each song
                proc = subprocess.Popen(
                    ["spotdl", "download", song_url,
                     "--output", str(DOWNLOAD_DIR),
                     "--print-errors"],
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                )
                self._spotdl_proc = proc
                for line in proc.stdout:
                    if self._cancel_event.is_set():
                        proc.terminate()
                        return
                    line = line.strip()
                    if line:
                        self.call_from_thread(self._log, f"[spotify] {line[:100]}")
                proc.wait()
                self._spotdl_proc = None
            except Exception as e:
                self.call_from_thread(self._log, f"✗ {name[:40]}: {str(e)[:60]}")

            task.done_tracks = i + 1
            task.progress    = (task.done_tracks / total) * 100
            self.call_from_thread(self._on_progress, task)

        task.status   = "done"
        task.progress = 100.0
        self.call_from_thread(self._on_done, task)

    # ── shared progress/done callbacks ───────────────────────────

    def _on_progress(self, task: DownloadTask):
        if not self._pause_event.is_set():
            return
        short = task.title[:22] + "…" if len(task.title) > 22 else task.title
        self.query_one("#prog-label", Label).update(
            "⟳ Merging…" if task.status == "merging" else f"⬇  {short}"
        )
        self.query_one("#prog-bar",   ProgressBar).update(progress=task.progress)
        self.query_one("#prog-size",  Label).update(task.size_str)
        self.query_one("#prog-speed", Label).update(
            f"{task.speed}  ETA {task.eta}" if task.speed else ""
        )
        self._refresh_table()

    def _on_done(self, task: DownloadTask):
        self._active = None
        self._pause_event.set()
        self.query_one("#btn-pause", Button).display = False
        self._set_pause_btn(False)
        if task.status == "done":
            self._log(f"✓ Saved: {task.title}  →  {DOWNLOAD_DIR}")
        self.query_one("#prog-label", Label).update("Idle")
        self.query_one("#prog-bar",   ProgressBar).update(progress=0)
        self.query_one("#prog-size",  Label).update("")
        self.query_one("#prog-speed", Label).update("")
        self._refresh_table()
        self._process_queue()


if __name__ == "__main__":
    VidLoad().run()
