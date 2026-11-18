# ============================================================================
# audio.cpp OmniVoice TTS Server — production image
# Includes: audio.cpp v0.9.5 (CUDA 12.8), OmniVoice f16 GGUF,
#           179 voice profiles, MP3 proxy, auto-restart watchdog.
#
# Build:  docker build -t ghcr.io/webbeees/omnivoice-ttscpp .
# Run:    docker run --gpus all -p 8000:8000 ghcr.io/webbeees/omnivoice-ttscpp
# ============================================================================
FROM nvidia/cuda:12.8.0-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# ── System packages ──────────────────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.12 python3.12-venv python3.12-dev \
        ffmpeg curl wget procps \
    && rm -rf /var/lib/apt/lists/*

# Bootstrap pip for Python 3.12
RUN python3.12 -m ensurepip --upgrade \
    && python3.12 -m pip install --no-cache-dir --upgrade pip

# ── Python deps for MP3 proxy ───────────────────────────────────────────
RUN python3.12 -m pip install --no-cache-dir aiohttp

# ── audio.cpp binary (v0.9.5, CUDA 12.8) ────────────────────────────────
RUN mkdir -p /opt/audiocpp && cd /opt/audiocpp \
    && wget -q -O audio.tar.gz \
       "https://github.com/0xShug0/audio.cpp/releases/download/v0.9.5/audio-v0.9.5-bin-ubuntu-x64-cuda12.8-colab.tar.gz" \
    && tar xzf audio.tar.gz \
    && rm audio.tar.gz \
    && chmod +x audiocpp_server

# ── OmniVoice GGUF model (f16, ~1.64GB) ─────────────────────────────────
RUN mkdir -p /opt/models/OmniVoice-GGUF && cd /opt/models/OmniVoice-GGUF \
    && wget -q --show-progress -O omnivoice-f16.gguf \
       "https://huggingface.co/audio-cpp/audio.cpp-gguf/resolve/main/OmniVoice-GGUF/omnivoice-f16.gguf"

# ── Voice profiles (179 voices, ~23MB compressed) ───────────────────────
COPY voice_profiles.tar.gz /tmp/voice_profiles.tar.gz
RUN mkdir -p /opt/voices /root/.local/share/omnivoice/profiles \
    && tar xzf /tmp/voice_profiles.tar.gz -C /root/.local/share/omnivoice/profiles \
    && rm /tmp/voice_profiles.tar.gz

# ── Build voice_dir (symlinks ref_audio.wav -> {name}.wav) ──────────────
RUN for d in /root/.local/share/omnivoice/profiles/*/; do \
        name=$(basename "$d"); \
        ln -sf "$d/ref_audio.wav" "/opt/voices/${name}.wav"; \
    done \
    && touch /opt/voices/prompt_text

# ── Transcribe voice references at build time (Whisper medium) ──────────
RUN python3.12 -m pip install --no-cache-dir faster-whisper soundfile numpy
COPY transcribe_voices.py /tmp/transcribe_voices.py
RUN python3.12 /tmp/transcribe_voices.py && rm /tmp/transcribe_voices.py
# Uninstall Whisper after use (saves ~1.5GB in final image)
RUN python3.12 -m pip uninstall -y faster-whisper ctranslate2 onnxruntime \
    && rm -rf /root/.cache/huggingface

# ── Server config ────────────────────────────────────────────────────────
COPY server.json /opt/audiocpp/server.json

# ── MP3 proxy ────────────────────────────────────────────────────────────
COPY mp3_proxy.py /opt/audiocpp/mp3_proxy.py

# ── Watchdog ─────────────────────────────────────────────────────────────
COPY watchdog_ttscpp.py /usr/local/bin/watchdog_ttscpp.py
RUN chmod +x /usr/local/bin/watchdog_ttscpp.py

# ── Entrypoint ───────────────────────────────────────────────────────────
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh

EXPOSE 8000

CMD ["/usr/local/bin/entrypoint.sh"]
