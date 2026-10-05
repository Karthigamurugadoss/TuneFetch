# Contributing to TuneFetch

Thanks for your interest in improving TuneFetch! Bug reports, ideas and pull requests are all welcome.

## Getting set up

1. Fork the repo and clone your fork.
2. Install Python 3.10+ and [ffmpeg](https://ffmpeg.org/).
3. Install dependencies and start the app:

   ```bash
   pip install -r requirements.txt
   python app.py
   ```

4. Open <http://127.0.0.1:5000>. Set the `PORT` environment variable to use another port.

## Making a change

- Create a branch from `main`: `git checkout -b my-change`.
- Keep changes focused. One fix or feature per pull request.
- Match the existing code style. The backend is a single `app.py`, and the UI lives in `templates/`, `static/css/` and `static/js/`.
- Try your change in the browser with a real Spotify link (a track, and an album or playlist if you touched that code).
- Open a pull request and describe what changed and why.

## Reporting bugs

Open an [issue](https://github.com/Karthigamurugadoss/TuneFetch/issues/new/choose) with the Spotify link type (track, album or playlist), the format you chose, your OS and Python version, and the error message shown in the app or terminal.

## A note on scope

TuneFetch is for personal use. Please don't submit changes aimed at bypassing DRM, scraping at scale, or hosting the app as a public service.
