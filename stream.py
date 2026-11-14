#!/usr/bin/env python3
"""
Open a web page in Chromium (inside a virtual display) and broadcast it to ok.ru
over RTMP using ffmpeg. One or more stream keys can be given, comma separated.

Use only with pages/content you own or have the right to rebroadcast.
DRM-protected (Widevine) content will not play in this setup and is not supported.

Usage:
    python3 stream.py --url https://example.com/page --key 1
    python3 stream.py --url https://example.com/page --key 1,1.1,1.2
"""
import argparse
import os
import shutil
import signal
import subprocess
import sys
import threading
import time

STREAM_KEYS = {
    "1": "15254238731883_15281627925099_najspfkgne",
    "1.1": "15254260751979_15281671637611_2plrcfqzze",
    "1.2": "15254285524587_15281717840491_7e6qdknzsu",
    "1.3": "16983200374379_18360218880619_efmw4fchxm",
    "1.4": "16983242579563_18360288741995_t2kh2jvcym",
    "1.5": "16983247822443_18360297982571_3zs5ml7gua",
    "1.6": "16983254834795_18360310237803_xrz3pf4uea",
    "1.7": "16983259553387_18360317971051_6khoe5efge",
    "1.8": "16983264468587_18360327342699_wsn7zgr7ee",
    "1.9": "16983269514859_18360335075947_363qzjlbte",
    "1.10": "16983277641323_18360347921003_rpf6hkqpdm",
    "1.11": "16983286554219_18360360503915_lrqraxbz3y",
    "2": "15254299352683_15281743071851_7dvz3h5d7q",
    "2.1": "15254308986475_15281761618539_3xca7oij3u",
    "2.2": "15254328122987_15281795566187_zjqa6bqzoq",
    "3": "15254341885547_15281821059691_hhlpb5vicy",
    "3.1": "15254357089899_15281848322667_sxeexgvzl4",
    "3.2": "15254367510123_15281868180075_pc4jrytfgm",
    "3.3": "17485986405995_19233134873195_iw63xjblny",
    "3.4": "17485996039787_19233150929515_d3yeoweuam",
    "3.5": "17486002789995_19233161611883_mbg22slybe",
    "3.6": "17486007770731_19233169934955_teme2zt4fm",
    "4": "15255022345835_15283095800427_vwrupxzstm",
    "4.1": "15255038074475_15283122080363_ai5qqp2we4",
    "4.2": "15255045480043_15283135842923_tldl4bhmii",
    "4.3": "15255208599147_15283449629291_abltofuc7m",
    "4.4": "15255217708651_15283466603115_bojrrqtlmu",
    "4.5": "15255227670123_15283486263915_jpntt54mve",
    "5": "17135767461483_18625099401835_4gpytlxk4a",
    "5.1": "15273713933931_15317494860395_avj47smmim",
    "5.2": "15273722257003_15317510195819_6edjluvdqi",
    "5.3": "15273739624043_15317541653099_ii4bxpvabe",
    "5.4": "15273750175339_15317561707115_csel26ku5a",
    "5.5": "15273760071275_15317579467371_cnewcj54me",
    "5.6": "15273767935595_15317595851371_3q43tk7tvm",
    "5.7": "15273778683499_15317616560747_4piekvs4wu",
    "s1.1": "14204232736303_14846150314543_37jq4ryehq",
    "s1.2": "14204288179759_14846247373359_tnsknmapva",
    "s1.3": "14204319768111_14846302489135_sr4ht4ccwq",
    "s1.4": "14204331957807_14846326147631_dji2acqcze",
    "s1.5": "14204346572335_14846351641135_7gvns4o5ue",
    "s1.6": "14204361252399_14846376479279_cjajhf4d3y",
    "s1.7": "14204370492975_14846393649711_6fduhdqite",
    "s1.8": "14204395527727_14846438017583_s2jlti7lsm",
    "s1.9": "14204411387439_14846464887343_f5lxgcqj5y",
    "s1.10": "14204424691247_14846487562799_xmbvntt6wa",
    "s2.1": "14204490948143_14846603495983_kzevn36tii",
    "s2.2": "14204506742319_14846634494511_ta2rxyg2oy",
    "s2.3": "14204523322927_14846661233199_foqb3q7zb4",
    "s2.4": "14204540034607_14846689085999_gjejdie4uy",
    "s2.5": "14204555304495_14846715497007_zdanghuxzu",
    "s2.6": "14204565200431_14846734371375_ap3bqpabpu",
    "s2.7": "14204577259055_14846756194863_3ecad2535u",
    "s2.8": "14204592528943_14846785227311_4hjl46y62e",
    "s2.9": "14204602621487_14846802594351_ilnp6lxekq",
    "s2.10": "14206184136239_14849618610735_ihnbx7hkoi",
}

DISPLAY = os.environ.get("DISPLAY_NUM", ":99")
WIDTH = int(os.environ.get("WIDTH", "1280"))
HEIGHT = int(os.environ.get("HEIGHT", "720"))
FPS = int(os.environ.get("FPS", "30"))
VIDEO_BITRATE = os.environ.get("VIDEO_BITRATE", "2500k")
AUDIO_BITRATE = os.environ.get("AUDIO_BITRATE", "128k")
RTMP_BASE = os.environ.get("OK_RTMP_BASE", "rtmp://vsu.mycdn.me/input/")
SINK = "vsink"

procs = []
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


def resolve_keys(args):
    """Return a de-duplicated list of (name, key) for the requested key names."""
    if args.raw_key:
        names = [k.strip() for k in args.raw_key.split(",") if k.strip()]
        return [(f"raw{i + 1}", k) for i, k in enumerate(names)]

    wanted = [k.strip() for k in (args.key or "").split(",") if k.strip()]
    if not wanted:
        sys.exit("Give --key 1 or --key 1,1.1,1.2 (names from STREAM_KEYS)")

    out, seen = [], set()
    for name in wanted:
        if name not in STREAM_KEYS:
            sys.exit(f"Unknown key name '{name}'. Available: {', '.join(STREAM_KEYS)}")
        if name not in seen:
            seen.add(name)
            out.append((name, STREAM_KEYS[name].strip()))
    return out


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


def click_play():
    x = int(os.environ.get("CLICK_X", WIDTH // 2))
    y = int(os.environ.get("CLICK_Y", HEIGHT // 2))
    subprocess.run(["xdotool", "mousemove", str(x), str(y)])
    time.sleep(0.5)
    subprocess.run(["xdotool", "click", "1"])
    log(f"Clicked at {x},{y}")


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


def pump(stream, secrets):
    """Print ffmpeg output with stream keys hidden."""
    for line in stream:
        for s in secrets:
            line = line.replace(s, "****")
        print(line.rstrip(), flush=True)


def build_output_args(rtmp_urls):
    if len(rtmp_urls) == 1:
        return ["-f", "flv", rtmp_urls[0]]
    # one encode, several RTMP outputs; a failing output does not stop the others
    tee = "|".join(f"[f=flv:onfail=ignore]{u}" for u in rtmp_urls)
    return ["-map", "0:v", "-map", "1:a", "-f", "tee", tee]


def start_ffmpeg(rtmp_urls, secrets):
    gop = FPS * 2
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "warning",
        "-f", "x11grab", "-draw_mouse", "0", "-framerate", str(FPS), "-video_size", f"{WIDTH}x{HEIGHT}",
        "-i", f"{DISPLAY}.0",
        "-f", "pulse", "-i", f"{SINK}.monitor",
        "-c:v", "libx264", "-preset", "veryfast", "-tune", "zerolatency",
        "-pix_fmt", "yuv420p",
        "-b:v", VIDEO_BITRATE, "-maxrate", VIDEO_BITRATE, "-bufsize", "5000k",
        "-g", str(gop), "-keyint_min", str(gop),
        "-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "44100", "-ac", "2",
    ] + build_output_args(rtmp_urls)
    p = start(cmd, stderr=subprocess.PIPE, text=True, bufsize=1)
    threading.Thread(target=pump, args=(p.stderr, secrets), daemon=True).start()
    return p


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
    ap.add_argument("--key", help="Key name(s) from STREAM_KEYS, comma separated (e.g. 1,1.1,1.2)")
    ap.add_argument("--raw-key", help="Raw stream key(s), comma separated")
    ap.add_argument("--retries", type=int, default=0, help="Max reconnects (0 = unlimited)")
    ap.add_argument("--dry-run", action="store_true", help="Check the key names and exit")
    ap.add_argument("--click", action="store_true", help="Click the page center after load (to press a Play button)")
    args = ap.parse_args()

    if not args.url.startswith(("http://", "https://")):
        sys.exit("--url must start with http:// or https://")

    keys = resolve_keys(args)
    names = ", ".join(n for n, _ in keys)
    rtmp_urls = [RTMP_BASE.rstrip("/") + "/" + k for _, k in keys]
    secrets = [k for _, k in keys]

    if args.dry_run:
        print(f"OK: {len(keys)} output(s): {names}")
        return

    for b in ("Xvfb", "ffmpeg", "pulseaudio", "pactl") + (("xdotool",) if args.click else ()):
        need(b)
    find_chromium()

    signal.signal(signal.SIGINT, cleanup)
    signal.signal(signal.SIGTERM, cleanup)

    start_display_and_audio()
    start_browser(args.url)
    log(f"Browser opened: {args.url}")
    log(f"Streaming to {len(keys)} output(s): {names}")
    time.sleep(6)  # let the page load
    if args.click:
        click_play()
        time.sleep(2)

    attempt = 0
    while not stopping:
        attempt += 1
        log(f"Starting ffmpeg (attempt {attempt})")
        ff = start_ffmpeg(rtmp_urls, secrets)
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
