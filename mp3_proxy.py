"""Lightweight proxy: sits on port 8000, forwards to audio.cpp on 8080.
Converts WAV responses to MP3 when response_format=mp3 is requested."""

import asyncio
import json
import subprocess
import tempfile
import os
import time
from aiohttp import web, ClientSession, ClientTimeout

BACKEND = "http://127.0.0.1:8080"
PROXY_PORT = 8000

async def proxy_speech(request):
    body = await request.read()
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return web.Response(status=400, text="Invalid JSON")

    want_mp3 = data.get("response_format") == "mp3"
    fwd_data = dict(data)
    fwd_data.pop("response_format", None)

    # Map num_step -> num_inference_steps (PHP compat)
    if "num_step" in fwd_data:
        steps = fwd_data.pop("num_step")
        fwd_data.setdefault("options", {})["num_inference_steps"] = steps

    # Move denoise/position_temperature into options if at top level
    for key in ("denoise", "position_temperature"):
        if key in fwd_data:
            val = fwd_data.pop(key)
            fwd_data.setdefault("options", {})[key] = val

    async with request.app["session"].post(
        f"{BACKEND}/v1/audio/speech",
        json=fwd_data,
        timeout=ClientTimeout(total=60),
    ) as resp:
        if resp.status != 200:
            err_body = await resp.read()
            return web.Response(status=resp.status, body=err_body,
                              content_type=resp.content_type)
        wav_bytes = await resp.read()

    if not want_mp3:
        return web.Response(body=wav_bytes, content_type="audio/wav")

    # Convert WAV -> MP3 via ffmpeg (fast, ~5ms for typical TTS output)
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wf:
        wf.write(wav_bytes)
        wav_path = wf.name
    mp3_path = wav_path.replace(".wav", ".mp3")
    try:
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", wav_path, "-codec:a", "libmp3lame",
             "-b:a", "128k", "-f", "mp3", mp3_path],
            capture_output=True, timeout=10,
        )
        if proc.returncode != 0:
            return web.Response(body=wav_bytes, content_type="audio/wav")
        with open(mp3_path, "rb") as f:
            mp3_bytes = f.read()
        return web.Response(body=mp3_bytes, content_type="audio/mpeg")
    finally:
        for p in (wav_path, mp3_path):
            try:
                os.unlink(p)
            except OSError:
                pass

async def proxy_passthrough(request):
    """Pass through all other endpoints unchanged."""
    path = request.path
    if request.query_string:
        path += f"?{request.query_string}"
    method = request.method.lower()
    kwargs = {}
    if method in ("post", "put", "patch"):
        kwargs["data"] = await request.read()

    async with getattr(request.app["session"], method)(
        f"{BACKEND}{path}",
        timeout=ClientTimeout(total=30),
        **kwargs,
    ) as resp:
        body = await resp.read()
        return web.Response(
            status=resp.status,
            body=body,
            content_type=resp.content_type,
        )

async def on_startup(app):
    app["session"] = ClientSession()

async def on_cleanup(app):
    await app["session"].close()

app = web.Application()
app.on_startup.append(on_startup)
app.on_cleanup.append(on_cleanup)
app.router.add_post("/v1/audio/speech", proxy_speech)
app.router.add_route("*", "/{path:.*}", proxy_passthrough)

if __name__ == "__main__":
    print(f"MP3 proxy listening on :{PROXY_PORT}, forwarding to {BACKEND}")
    web.run_app(app, host="0.0.0.0", port=PROXY_PORT, print=print)
