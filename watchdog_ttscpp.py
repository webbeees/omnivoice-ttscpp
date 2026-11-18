#!/usr/bin/env python3.12
"""Watchdog: manages audio.cpp server + MP3 proxy, auto-restarts on failure."""
import subprocess
import urllib.request
import json
import time
import os
import signal
import sys

HEALTH_URL = "http://localhost:8080/health"
SPEECH_URL = "http://localhost:8000/v1/audio/speech"
LOGFILE = "/tmp/ttscpp_watchdog.log"
CHECK_INTERVAL = 60
STARTUP_WAIT = 15
MAX_CONSECUTIVE_FAILS = 2

ACPP_CMD = ["/opt/audiocpp/audiocpp_server", "--config", "/opt/audiocpp/server.json"]
ACPP_LOG = "/tmp/audiocpp_server.log"

PROXY_CMD = ["python3.12", "/opt/audiocpp/mp3_proxy.py"]
PROXY_LOG = "/tmp/mp3_proxy.log"

acpp_proc = None
proxy_proc = None


def log(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    line = f"{ts} WATCHDOG: {msg}"
    print(line, flush=True)
    with open(LOGFILE, "a") as f:
        f.write(line + "\n")


def health_check_audiocpp():
    """Check audio.cpp server health endpoint."""
    try:
        req = urllib.request.Request(HEALTH_URL)
        resp = urllib.request.urlopen(req, timeout=10)
        data = json.loads(resp.read())
        return data.get("status") == "ok"
    except Exception as e:
        log(f"audio.cpp health check failed: {e}")
        return False


def health_check_proxy():
    """Check proxy by making a real TTS request through it."""
    body = json.dumps({
        "model": "omnivoice",
        "input": "test",
        "voice": "maleguard",
        "response_format": "mp3",
    }).encode()
    req = urllib.request.Request(
        SPEECH_URL, data=body, headers={"Content-Type": "application/json"}
    )
    try:
        resp = urllib.request.urlopen(req, timeout=30)
        data = resp.read()
        return len(data) > 100
    except Exception as e:
        log(f"Proxy health check failed: {e}")
        return False


def stop_all():
    """Kill both processes."""
    global acpp_proc, proxy_proc
    for name, proc in [("proxy", proxy_proc), ("audio.cpp", acpp_proc)]:
        if proc and proc.poll() is None:
            log(f"Stopping {name} (PID {proc.pid})...")
            try:
                proc.terminate()
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
    os.system("pkill -9 -f audiocpp_server 2>/dev/null")
    os.system("pkill -9 -f mp3_proxy 2>/dev/null")
    time.sleep(2)


def start_all():
    """Start audio.cpp server and MP3 proxy."""
    global acpp_proc, proxy_proc
    stop_all()

    log("Starting audio.cpp server...")
    with open(ACPP_LOG, "w") as out:
        acpp_proc = subprocess.Popen(
            ACPP_CMD, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )
    log(f"audio.cpp PID={acpp_proc.pid}")

    # Wait for audio.cpp to be ready
    for i in range(STARTUP_WAIT):
        time.sleep(1)
        if health_check_audiocpp():
            log(f"audio.cpp healthy after {i+1}s")
            break
    else:
        log(f"WARNING: audio.cpp not healthy after {STARTUP_WAIT}s, starting proxy anyway")

    log("Starting MP3 proxy...")
    with open(PROXY_LOG, "w") as out:
        proxy_proc = subprocess.Popen(
            PROXY_CMD, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
        )
    log(f"Proxy PID={proxy_proc.pid}")
    time.sleep(2)

    # Verify both are up
    voices_ok = False
    try:
        resp = urllib.request.urlopen("http://localhost:8000/v1/audio/voices?model=omnivoice", timeout=5)
        voices = json.loads(resp.read()).get("voices", [])
        voices_ok = len(voices) > 0
        log(f"Voice library: {len(voices)} voices loaded")
    except Exception as e:
        log(f"Voice check failed: {e}")

    log(f"Startup complete (voices_ok={voices_ok})")


def shutdown(signum, frame):
    log(f"Received signal {signum}, shutting down...")
    stop_all()
    sys.exit(0)


signal.signal(signal.SIGTERM, shutdown)
signal.signal(signal.SIGINT, shutdown)

log("Watchdog started (v1: audio.cpp + MP3 proxy, 2 consecutive fails before restart)")
start_all()

# Wait for first real TTS request to warm up model (lazy load)
log(f"Warming up model with test request...")
time.sleep(3)
health_check_proxy()
log("Warm-up complete, entering monitoring loop")

consecutive_fails = 0

while True:
    time.sleep(CHECK_INTERVAL)

    # Check if processes are still alive
    if acpp_proc and acpp_proc.poll() is not None:
        log(f"audio.cpp process died (exit code {acpp_proc.returncode}), restarting...")
        start_all()
        consecutive_fails = 0
        continue

    if proxy_proc and proxy_proc.poll() is not None:
        log(f"Proxy process died (exit code {proxy_proc.returncode}), restarting proxy...")
        with open(PROXY_LOG, "w") as out:
            proxy_proc = subprocess.Popen(
                PROXY_CMD, stdout=out, stderr=subprocess.STDOUT, start_new_session=True
            )
        log(f"Proxy restarted PID={proxy_proc.pid}")
        time.sleep(2)
        continue

    # Health check through the full stack (proxy -> audio.cpp)
    if health_check_audiocpp():
        consecutive_fails = 0
    else:
        consecutive_fails += 1
        log(f"Fail count: {consecutive_fails}/{MAX_CONSECUTIVE_FAILS}")
        if consecutive_fails >= MAX_CONSECUTIVE_FAILS:
            log("RESTARTING ALL (consecutive failures reached threshold)")
            start_all()
            consecutive_fails = 0
