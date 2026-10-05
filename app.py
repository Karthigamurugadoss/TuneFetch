"""TuneFetch - download Spotify songs, albums and playlists as tagged audio files.

Pipeline per track:
  Spotify embed page (metadata)  ->  YouTube Music search (best match by title + duration)
  ->  yt-dlp download  ->  ffmpeg conversion  ->  mutagen tagging (title, artist, year, cover)
"""
from flask import Flask, render_template, request, jsonify, send_file
from concurrent.futures import ThreadPoolExecutor
from difflib import SequenceMatcher
import glob
import json
import os
import re
import shutil
import tempfile
import threading
import time
import urllib.parse
import urllib.request
import uuid
import zipfile

import yt_dlp
from ytmusicapi import YTMusic
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TALB, TDRC, TIT2, TPE1, TRCK
from mutagen.mp4 import MP4, MP4Cover

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DOWNLOAD_DIR = os.path.join(BASE_DIR, "downloads")
os.makedirs(DOWNLOAD_DIR, exist_ok=True)

MAX_PARALLEL = 3
KEEP_HOURS = 24
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

# format key -> (yt-dlp codec, file extension, supports bitrate choice)
FORMATS = {
    "mp3": ("mp3", "mp3", True),
    "m4a": ("m4a", "m4a", True),
    "flac": ("flac", "flac", False),
    "wav": ("wav", "wav", False),
}
BITRATES = {"128", "192", "256", "320"}

jobs = {}
jobs_lock = threading.Lock()
_local = threading.local()


# ───────────────────────── helpers ─────────────────────────

def find_ffmpeg_dir():
    """Return the folder containing ffmpeg, or None. Falls back to the WinGet install location."""
    found = shutil.which("ffmpeg")
    if found:
        return os.path.dirname(found)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        hits = glob.glob(os.path.join(local, "Microsoft", "WinGet", "Packages", "*FFmpeg*", "**", "bin", "ffmpeg.exe"), recursive=True)
        if hits:
            return os.path.dirname(hits[0])
    return None


FFMPEG_DIR = find_ffmpeg_dir()


def get_spotify_type(url):
    m = re.search(r"spotify\.com/(?:intl-[a-z]{2}/)?(track|playlist|album)/([A-Za-z0-9]+)", url)
    if not m:
        return None, None
    kind = {"track": "song"}.get(m.group(1), m.group(1))
    return kind, m.group(2)


def embed_kind(kind):
    return "track" if kind == "song" else kind


def http_get(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def fetch_oembed(url):
    try:
        data = http_get("https://open.spotify.com/oembed?" + urllib.parse.urlencode({"url": url}))
        return json.loads(data.decode("utf-8"))
    except Exception:
        return None


def fetch_embed_entity(kind, spotify_id):
    """Read the public embed page - no API credentials needed, and it is fast."""
    html = http_get(f"https://open.spotify.com/embed/{embed_kind(kind)}/{spotify_id}").decode("utf-8", "replace")
    m = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.S)
    if not m:
        raise RuntimeError("Could not read Spotify page data.")
    return json.loads(m.group(1))["props"]["pageProps"]["state"]["data"]["entity"]


def resolve(url):
    """Turn a Spotify URL into {type, id, name, artist, cover, tracks:[...]}."""
    kind, spotify_id = get_spotify_type(url)
    if not kind:
        raise ValueError("Invalid Spotify URL.")

    ent = fetch_embed_entity(kind, spotify_id)
    oembed = fetch_oembed(url) or {}
    cover = oembed.get("thumbnail_url", "")
    tracks = []

    if kind == "song":
        artists = [a["name"] for a in ent.get("artists", [])] or ["Unknown Artist"]
        year = (ent.get("releaseDate") or {}).get("isoString", "")[:4]
        tracks.append({
            "id": spotify_id, "title": ent.get("name") or ent.get("title") or "Unknown",
            "artists": artists, "duration": (ent.get("duration") or 0) / 1000,
            "year": year, "cover": cover, "number": 1,
        })
        return {"type": kind, "id": spotify_id, "name": tracks[0]["title"],
                "artist": ", ".join(artists), "cover": cover, "tracks": tracks}

    for i, t in enumerate(ent.get("trackList", []), 1):
        if t.get("entityType") not in (None, "track"):
            continue
        tid = (t.get("uri") or "").split(":")[-1] or f"{spotify_id}-{i}"
        artists = [a.strip() for a in re.split(r",\s*", t.get("subtitle") or "") if a.strip()] or ["Unknown Artist"]
        tracks.append({
            "id": tid, "title": t.get("title") or "Unknown", "artists": artists,
            "duration": (t.get("duration") or 0) / 1000, "year": "", "cover": "", "number": i,
        })
    return {"type": kind, "id": spotify_id, "name": ent.get("name") or ent.get("title") or kind.title(),
            "artist": ent.get("subtitle") or "", "cover": cover, "tracks": tracks}


def safe_filename(text, limit=150):
    text = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip(" .")
    return text[:limit].rstrip(" .") or "track"


def track_filename(track):
    return safe_filename(f"{', '.join(track['artists'][:3])} - {track['title']}")


# ───────────────────────── matching ─────────────────────────

def ytm():
    if not hasattr(_local, "ytm"):
        _local.ytm = YTMusic()
    return _local.ytm


def norm(text):
    text = re.sub(r"[\(\[].*?[\)\]]", " ", text.lower())
    return re.sub(r"[^\w]+", " ", text).strip()


def score_candidate(track, title, duration):
    sim = SequenceMatcher(None, norm(track["title"]), norm(title)).ratio()
    penalty = 0
    if track["duration"] and duration:
        penalty = min(abs(track["duration"] - duration), 60) / 6
    return sim * 2 - penalty


def find_video(track):
    """Return (video_id, cover_url) for the best YouTube match."""
    query = f"{track['title']} {track['artists'][0]}"
    best = None  # (score, video_id, thumb)

    for flt in ("songs", "videos"):
        try:
            results = ytm().search(query, filter=flt, limit=8)
        except Exception:
            results = []
        for r in results:
            vid = r.get("videoId")
            if not vid:
                continue
            s = score_candidate(track, r.get("title", ""), r.get("duration_seconds"))
            if flt == "videos":
                s -= 0.5  # prefer official audio tracks
            thumbs = r.get("thumbnails") or []
            thumb = re.sub(r"=w\d+-h\d+.*$", "=w544-h544", thumbs[-1]["url"]) if thumbs else ""
            if best is None or s > best[0]:
                best = (s, vid, thumb)
        if best and best[0] > 0.8:
            break

    if best and best[0] > -1:
        return best[1], best[2]

    # Last resort: plain YouTube search
    with yt_dlp.YoutubeDL({"quiet": True, "extract_flat": True, "no_warnings": True}) as ydl:
        info = ydl.extract_info(f"ytsearch5:{query} audio", download=False)
    for e in (info or {}).get("entries", []):
        s = score_candidate(track, e.get("title", ""), e.get("duration"))
        if best is None or s > best[0]:
            best = (s, e["id"], "")
    if best:
        return best[1], best[2]
    raise LookupError("No matching audio found on YouTube.")


# ───────────────────────── tagging ─────────────────────────

def tag_file(path, track, cover_url, fmt):
    cover = None
    if cover_url:
        try:
            cover = http_get(cover_url, timeout=15)
        except Exception:
            cover = None
    artist = ", ".join(track["artists"])
    try:
        if fmt == "mp3":
            try:
                tags = ID3(path)
            except Exception:
                tags = ID3()
            tags.add(TIT2(encoding=3, text=track["title"]))
            tags.add(TPE1(encoding=3, text=artist))
            if track.get("album"):
                tags.add(TALB(encoding=3, text=track["album"]))
            if track.get("year"):
                tags.add(TDRC(encoding=3, text=str(track["year"])))
            tags.add(TRCK(encoding=3, text=str(track["number"])))
            if cover:
                tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="Cover", data=cover))
            tags.save(path, v2_version=3)
        elif fmt == "m4a":
            mp4 = MP4(path)
            mp4["\xa9nam"] = [track["title"]]
            mp4["\xa9ART"] = [artist]
            if track.get("album"):
                mp4["\xa9alb"] = [track["album"]]
            if track.get("year"):
                mp4["\xa9day"] = [str(track["year"])]
            if cover:
                mp4["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]
            mp4.save()
        elif fmt == "flac":
            audio = FLAC(path)
            audio["title"] = track["title"]
            audio["artist"] = artist
            if track.get("album"):
                audio["album"] = track["album"]
            if track.get("year"):
                audio["date"] = str(track["year"])
            if cover:
                pic = Picture()
                pic.type, pic.mime, pic.data = 3, "image/jpeg", cover
                audio.add_picture(pic)
            audio.save()
    except Exception:
        pass  # tagging is best-effort; the audio is still good


# ───────────────────────── download worker ─────────────────────────

class Cancelled(Exception):
    pass


def download_track(job, idx):
    track = job["tracks"][idx]
    state = job["states"][idx]
    fmt, quality = job["format"], job["bitrate"]
    codec, ext, has_bitrate = FORMATS[fmt]

    if job["cancel"].is_set():
        state["status"] = "cancelled"
        return

    try:
        state.update(status="searching", error=None, progress=2)
        video_id, thumb = find_video(track)
        if job["cancel"].is_set():
            raise Cancelled()

        def hook(d):
            if job["cancel"].is_set():
                raise Cancelled()
            if d["status"] == "downloading":
                total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
                if total:
                    state["progress"] = max(state["progress"], int(5 + d["downloaded_bytes"] / total * 80))
            elif d["status"] == "finished":
                state.update(status="converting", progress=88)

        state["status"] = "downloading"
        pp = {"key": "FFmpegExtractAudio", "preferredcodec": codec}
        if has_bitrate:
            pp["preferredquality"] = quality
        opts = {
            "format": "bestaudio/best",
            "outtmpl": os.path.join(job["dir"], f"_{idx}.%(ext)s"),
            "quiet": True, "no_warnings": True, "noprogress": True, "noplaylist": True,
            "retries": 5, "fragment_retries": 5, "concurrent_fragment_downloads": 4,
            "postprocessors": [pp], "progress_hooks": [hook],
        }
        if FFMPEG_DIR:
            opts["ffmpeg_location"] = FFMPEG_DIR
        with yt_dlp.YoutubeDL(opts) as ydl:
            ydl.download([f"https://www.youtube.com/watch?v={video_id}"])

        produced = os.path.join(job["dir"], f"_{idx}.{ext}")
        if not os.path.isfile(produced):
            raise RuntimeError("Conversion produced no file. Check that ffmpeg is installed.")

        state["status"] = "tagging"
        tag_file(produced, track, track.get("cover") or thumb, fmt)

        base = track_filename(track)
        final, n = os.path.join(job["dir"], f"{base}.{ext}"), 2
        while os.path.exists(final):
            final = os.path.join(job["dir"], f"{base} ({n}).{ext}")
            n += 1
        os.replace(produced, final)
        state.update(status="done", progress=100, file=os.path.basename(final))
    except Cancelled:
        state["status"] = "cancelled"
    except Exception as e:
        msg = str(e).replace("ERROR: ", "")
        state.update(status="failed", error=msg[:200] or "Unknown error")
    finally:
        for leftover in glob.glob(os.path.join(job["dir"], f"_{idx}.*")):
            try:
                os.remove(leftover)
            except OSError:
                pass


def run_job(job, indices):
    job["status"] = "downloading"
    with ThreadPoolExecutor(max_workers=MAX_PARALLEL) as pool:
        list(pool.map(lambda i: download_track(job, i), indices))
    finish_job(job)


def finish_job(job):
    states = job["states"]
    if job["cancel"].is_set():
        job["status"] = "cancelled"
    elif any(s["status"] == "done" for s in states):
        job["status"] = "done"
    else:
        job["status"] = "error"
        job["error"] = states[0]["error"] if states and states[0].get("error") else "All downloads failed."


def prepare_and_run(job, urls, selected):
    """Resolve Spotify metadata, then hand the tracks to the worker pool."""
    try:
        job["message"] = "Reading Spotify links..."
        tracks, names = [], []
        for url in urls:
            info = resolve(url)
            names.append(info["name"])
            chosen = info["tracks"]
            if selected and len(urls) == 1:
                chosen = [t for t in chosen if t["id"] in selected]
            for t in chosen:
                if info["type"] != "song":
                    t["album"] = info["name"] if info["type"] == "album" else ""
                tracks.append(t)
        if not tracks:
            raise RuntimeError("No tracks found. The link may be private or empty.")

        job["name"] = names[0] if len(names) == 1 else f"{len(names)} links"
        job["tracks"] = tracks
        job["states"] = [{"status": "queued", "progress": 0, "error": None, "file": None} for _ in tracks]
        job["message"] = f"Downloading {len(tracks)} track{'s' if len(tracks) != 1 else ''}..."
        run_job(job, list(range(len(tracks))))
    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e) or "Something went wrong."


def cleanup_old_jobs():
    cutoff = time.time() - KEEP_HOURS * 3600
    for name in os.listdir(DOWNLOAD_DIR):
        path = os.path.join(DOWNLOAD_DIR, name)
        try:
            if os.path.isdir(path) and os.path.getmtime(path) < cutoff:
                shutil.rmtree(path, ignore_errors=True)
        except OSError:
            pass


# ───────────────────────── routes ─────────────────────────

@app.route("/")
def home():
    return render_template("index.html")


@app.route("/api/health")
def health():
    return jsonify({"ffmpeg": FFMPEG_DIR is not None})


@app.route("/fetch-info", methods=["POST"])
def fetch_info():
    data = request.get_json(silent=True) or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"success": False, "message": "No URL provided."})
    if not get_spotify_type(url)[0]:
        return jsonify({"success": False, "message": "Invalid Spotify URL."})
    try:
        info = resolve(url)
    except Exception as e:
        return jsonify({"success": False, "message": f"Could not read that link: {e}"})

    kind = info["type"]
    return jsonify({
        "success": True, "type": kind, "id": info["id"],
        "title": info["name"], "artist": info["artist"], "thumbnail": info["cover"],
        "embed_url": f"https://open.spotify.com/embed/{embed_kind(kind)}/{info['id']}?utm_source=generator&theme=0",
        "tracks": [{"id": t["id"], "title": t["title"], "artist": ", ".join(t["artists"]),
                    "duration": t["duration"]} for t in info["tracks"]],
    })


@app.route("/start-download", methods=["POST"])
def start_download():
    data = request.get_json(silent=True) or {}
    urls = data.get("urls") or ([data["url"]] if data.get("url") else [])
    valid = []
    for u in urls:
        u = str(u).strip()
        if u and get_spotify_type(u)[0] and u not in valid:
            valid.append(u)
    if not valid:
        return jsonify({"success": False, "message": "No valid Spotify URLs provided."})

    fmt = data.get("format", "mp3")
    if fmt not in FORMATS:
        fmt = "mp3"
    bitrate = str(data.get("bitrate", "320"))
    if bitrate not in BITRATES:
        bitrate = "320"
    if not FFMPEG_DIR:
        return jsonify({"success": False, "message": "ffmpeg is not installed. Install it with: winget install Gyan.FFmpeg (then restart the app)."})

    job_id = uuid.uuid4().hex[:12]
    job_dir = os.path.join(DOWNLOAD_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)
    job = {
        "status": "resolving", "message": "Starting...", "error": None, "name": "",
        "tracks": [], "states": [], "dir": job_dir, "format": fmt, "bitrate": bitrate,
        "cancel": threading.Event(),
    }
    with jobs_lock:
        jobs[job_id] = job
    selected = set(data.get("selected") or [])
    threading.Thread(target=prepare_and_run, args=(job, valid, selected), daemon=True).start()
    return jsonify({"success": True, "job_id": job_id})


@app.route("/download-status/<job_id>")
def download_status(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"success": False, "message": "Job not found."})
    tracks = []
    for t, s in zip(job["tracks"], job["states"]):
        tracks.append({"title": t["title"], "artist": ", ".join(t["artists"]), **s})
    total = len(tracks)
    done = sum(1 for s in job["states"] if s["status"] == "done")
    failed = sum(1 for s in job["states"] if s["status"] == "failed")
    percent = int(sum(s["progress"] for s in job["states"]) / total) if total else 0
    return jsonify({
        "success": True, "status": job["status"], "message": job["message"], "error": job["error"],
        "name": job["name"], "tracks": tracks, "total": total, "done": done, "failed": failed,
        "percent": percent, "format": job["format"],
    })


@app.route("/cancel/<job_id>", methods=["POST"])
def cancel(job_id):
    job = jobs.get(job_id)
    if not job:
        return jsonify({"success": False})
    job["cancel"].set()
    return jsonify({"success": True})


@app.route("/retry/<job_id>", methods=["POST"])
def retry(job_id):
    job = jobs.get(job_id)
    if not job or job["status"] in ("downloading", "resolving"):
        return jsonify({"success": False, "message": "Nothing to retry."})
    indices = [i for i, s in enumerate(job["states"]) if s["status"] in ("failed", "cancelled")]
    if not indices:
        return jsonify({"success": False, "message": "No failed tracks."})
    job["cancel"] = threading.Event()
    job["error"] = None
    for i in indices:
        job["states"][i].update(status="queued", progress=0, error=None)
    threading.Thread(target=run_job, args=(job, indices), daemon=True).start()
    return jsonify({"success": True})


@app.route("/get-file/<job_id>/<path:filename>")
def get_file(job_id, filename):
    if not re.fullmatch(r"[0-9a-f]{12}", job_id):
        return "Not found", 404
    safe = os.path.basename(filename)
    path = os.path.join(DOWNLOAD_DIR, job_id, safe)
    if not os.path.isfile(path):
        return "File not found", 404
    return send_file(path, as_attachment=True, download_name=safe)


@app.route("/get-zip/<job_id>")
def get_zip(job_id):
    job = jobs.get(job_id)
    if not job:
        return "Job not found", 404
    files = [s["file"] for s in job["states"] if s["status"] == "done" and s["file"]]
    if not files:
        return "Nothing to zip", 404
    tmp = tempfile.NamedTemporaryFile(suffix=".zip", delete=False)
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_STORED) as zf:
        for f in files:
            zf.write(os.path.join(job["dir"], f), arcname=f)
    zip_name = safe_filename(job["name"] or "tunefetch") + ".zip"
    response = send_file(tmp.name, as_attachment=True, download_name=zip_name, mimetype="application/zip")
    response.call_on_close(lambda: os.path.exists(tmp.name) and os.remove(tmp.name))
    return response


if __name__ == "__main__":
    cleanup_old_jobs()
    print(" * TuneFetch running at http://127.0.0.1:5000")
    print(f" * ffmpeg: {FFMPEG_DIR or 'NOT FOUND - install it with: winget install Gyan.FFmpeg'}")
    app.run(debug=False, threaded=True)
