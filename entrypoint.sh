#!/bin/bash
set -e

echo "=== audio.cpp OmniVoice TTS Server ==="
echo "  audio.cpp v0.9.5 | OmniVoice f16 | flash_attention"
echo "  Voices: $(ls /opt/voices/*.wav 2>/dev/null | wc -l)"
echo "  Port 8000 (proxy+MP3) -> 8080 (audio.cpp)"
echo "Starting watchdog..."

# Clear old logs
> /tmp/ttscpp_watchdog.log
> /tmp/audiocpp_server.log
> /tmp/mp3_proxy.log

exec python3.12 /usr/local/bin/watchdog_ttscpp.py
