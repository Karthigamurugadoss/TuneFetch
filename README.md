<h1 align="center">TuneFetch</h1>

<p align="center">
  <strong>Download Spotify songs, albums and playlists as fully tagged audio files.</strong><br>
  Self-hosted web app built with Python Flask, yt-dlp and ffmpeg.
</p>

<p align="center">
  <a href="https://python.org"><img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white" alt="Python"></a>
  <a href="https://flask.palletsprojects.com"><img src="https://img.shields.io/badge/Flask-Web_Framework-000000?logo=flask&logoColor=white" alt="Flask"></a>
  <a href="https://github.com/yt-dlp/yt-dlp"><img src="https://img.shields.io/badge/yt--dlp-Media_Engine-FF0000?logo=youtube&logoColor=white" alt="yt-dlp"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-green.svg" alt="License"></a>
</p>

---

TuneFetch takes a Spotify link (track, album or playlist), reads its metadata, finds the best matching audio on YouTube Music, converts it with ffmpeg and writes proper tags and cover art into every file.

> **Disclaimer:** Only download content you own or have permission to use. Respect Spotify's and YouTube's terms of service and copyright law. This project is for personal and educational use.

## How it works

```
Spotify link ─► metadata (title, artist, album, year, cover)
             ─► YouTube Music search (best match by title + duration)
             ─► yt-dlp download ─► ffmpeg conversion ─► mutagen tagging
```

## Features

- **Tracks, albums and playlists** — paste any Spotify URL
- **Formats** — MP3, M4A, FLAC and WAV
- **Bitrate choice** — 128 / 192 / 256 / 320 kbps for MP3 and M4A
- **Tagged files** — title, artist, track number and embedded cover art in every format; album name for album links, and release year when Spotify provides it (single tracks)
- **Smart matching** — picks the closest YouTube Music result by title and duration
- **Live progress** — per-track status, cancel and retry
- **ZIP download** — grab a whole album or playlist in one archive
- **Automatic cleanup** — download folders older than 24 hours are deleted on startup and whenever a new download starts

## Getting started

### Requirements

- Python 3.10+
- [ffmpeg](https://ffmpeg.org/) available on your `PATH`

Install ffmpeg on Windows with:

```bash
winget install Gyan.FFmpeg
```

### Install and run

```bash
git clone https://github.com/Karthigamurugadoss/TuneFetch.git
cd TuneFetch
pip install -r requirements.txt
python app.py
```

Then open <http://127.0.0.1:5000> in your browser.

## Usage

1. Paste a Spotify track, album or playlist link.
2. Click **Preview** to see the tracks and untick any you don't want.
3. Choose a format and bitrate.
4. Start the download, then save files individually or as a ZIP.

## Project structure

```
TuneFetch/
├── app.py              # Flask backend: metadata, matching, download, tagging
├── requirements.txt    # Python dependencies
├── templates/
│   └── index.html      # Web UI
└── static/
    ├── css/style.css
    └── js/app.js
```

## Tech stack

[Flask](https://flask.palletsprojects.com) · [yt-dlp](https://github.com/yt-dlp/yt-dlp) · [ytmusicapi](https://github.com/sigma67/ytmusicapi) · [mutagen](https://github.com/quodlibet/mutagen) · [ffmpeg](https://ffmpeg.org/)

## Contributing

Issues and pull requests are welcome. Fork the repo, create a branch, and open a PR.

## License

Released under the [MIT License](LICENSE).
