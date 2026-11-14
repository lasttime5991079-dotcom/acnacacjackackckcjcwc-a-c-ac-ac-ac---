#!/usr/bin/env python3
"""
Open a web page in Chromium (inside a virtual display) and broadcast it to ok.ru
over RTMP using ffmpeg.

Use only with pages/content you own or have the right to rebroadcast.
DRM-protected (Widevine) content will not play in this setup and is not supported.

Usage:
    python3 stream.py --url https://example.com/my-page --key 1.2
    python3 stream.py --url https://example.com/my-page --raw-key AAAA_BBBB_cccc

Config (environment variables):
    OK_RTMP_BASE   RTMP ingest base URL (default rtmp://vsu.mycdn.me/input/)
    KEYS_FILE      JSON file mapping key names to stream keys (default keys.json)
    WIDTH, HEIGHT, FPS, VIDEO_BITRATE, AUDIO_BITRATE
"""
import argparse
import json
import os
import shutil
import signal
import subprocess
import sys
import time

DISPLAY = os.environ.get("DISPLAY_NUM", ":99")
WIDTH = int(os.environ.get("WIDTH", "1280"))
HEIGHT = int(os.environ.get("HEIGHT", "720"))
FPS = int(os.environ.get("FPS", "30"))
VIDEO_BITRATE = os.environ.get("VIDEO_BITRATE", "2500k")
AUDIO_BITRATE = os.environ.get("AUDIO_BITRATE", "128k")
RTMP_BASE = os.environ.get("OK_RTMP_BASE", "rtmp://vsu.mycdn.me/input/")
KEYS_FILE = os.environ.get("KEYS_FILE", "keys.json")
SINK = "vsink"

procs = []  # every child process we start, so we can clean up
stopping = False


def log(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def need(binary):
    if not shutil.which(binary):
        sys.exit(f"Missing required program: {binary}")


def find_chromium():
    for name in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable"):
        if shutil.which(name):
            return name
    sys.exit("Chromium/Chrome not found")


def start(cmd, **kw):
    p = subprocess.Popen(cmd, **kw)
    procs.append(p)
    return p


def load_key(args):
    if args.raw_key:
        return args.raw_key.strip()
    key_name = args.key or os.environ.get("STREAM_KEY_NAME")
    if not key_name:
        sys.exit("Give --key <name> (from keys.json) or --raw-key <key>")
    if not os.path.exists(KEYS_FILE):
        sys.exit(f"{KEYS_FILE} not found. Copy keys.example.json to keys.json and fill it in.")
    with open(KEYS_FILE, encoding="utf-8") as f:
        keys = json.load(f)
    if key_name not in keys:
        sys.exit(f"Key '{key_name}' not in {KEYS_FILE}. Available: {', '.join(keys)}")
    return keys[key_name].strip()


def start_display_and_audio():
    start(["Xvfb", DISPLAY, "-screen", "0", f"{WIDTH}x{HEIGHT}x24", "-nolisten", "tcp"],
          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1.5)
    os.environ["DISPLAY"] = DISPLAY

    subprocess.run(["pulseaudio", "--start", "--exit-idle-time=-1"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(1)
    subprocess.run(["pactl", "load-module", "module-null-sink", f"sink_name={SINK}"],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(["pactl", "set-default-sink", SINK],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_browser(url):
    profile = "/tmp/chrome-profile"
    shutil.rmtree(profile, ignore_errors=True)
    cmd = [
        find_chromium(),
        "--no-sandbox",
        "--kiosk",
        f"--window-size={WIDTH},{HEIGHT}",
        "--window-position=0,0",
        f"--user-data-dir={profile}",
        "--autoplay-policy=no-user-gesture-required",
        "--disable-infobars",
        "--disable-session-crashed-bubble",
        "--no-first-run",
        "--disable-features=Translate",
        url,
    ]
    return start(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def start_ffmpeg(rtmp_url):
    gop = FPS * 2
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-f", "x11grab", "-framerate", str(FPS), "-video_size", f"{WIDTH}x{HEIGHT}",
        "-i", f"{DISPLAY}.0",
        "-f", "pulse", "-i", f"{SINK}.monitor",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-b:v", VIDEO_BITRATE, "-maxrate", VIDEO_BITRATE, "-bufsize", "5000k",
        "-g", str(gop), "-keyint_min", str(gop),
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "44100", "-ac", "2",
        "-f", "flv", rtmp_url,
    ]
    return start(cmd)


def cleanup(*_):
    global stopping
    stopping = True
    for p in reversed(procs):
        if p.poll() is None:
            p.terminate()
    for p in procs:
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", required=True, help="Page to open and broadcast")
    ap.add_argument("--key", help="Key name from keys.json (e.g. 1.2, s2.5)")
    ap.add_argument("--raw-key", help="Stream key passed directly (visible in shell history, prefer --key)")
    ap.add_argument("--retries", type=int, default=0, help="Max reconnects (0 = unlimited)")
    ap.add_argument("--dry-run", action="store_true", help="Print the ffmpeg command (key hidden) and exit")
    args = ap.parse_args()

    if not args.url.startswith(("http://", "https://")):
        sys.exit("--url must start with http:// or https://")

    for b in ("Xvfb", "ffmpeg", "pulseaudio", "pactl"):
        need(b)
    find_chromium()

    key = load_key(args)
    rtmp_url = RTMP_BASE.rstrip("/") + "/" + key

    if args.dry_run:
        print("ffmpeg ... -f flv", RTMP_BASE.rstrip("/") + "/****")
        return

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    start_display_and_audio()
    start_browser(args.url)
    log(f"Browser opened: {args.url}")
    time.sleep(6)  # let the page load

    attempt = 0
    while not stopping:
        attempt += 1
        log(f"Starting ffmpeg (attempt {attempt})")
        ff = start_ffmpeg(rtmp_url)
        ff.wait()
        if stopping:
            break
        log(f"ffmpeg exited with code {ff.returncode}")
        if args.retries and attempt >= args.retries:
            log("Retry limit reached, stopping.")
            break
        time.sleep(5)

    cleanup()


if __name__ == "__main__":
    main()
