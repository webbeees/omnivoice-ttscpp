"""Build-time voice transcription: generates prompt_text for all voice profiles."""
import os
import time
import numpy as np
import soundfile as sf

start = time.time()
from faster_whisper import WhisperModel

print("Loading Whisper medium model for voice transcription...")
model = WhisperModel("medium", device="cpu", compute_type="int8")
print(f"Model loaded in {time.time()-start:.1f}s")

profiles_dir = "/root/.local/share/omnivoice/profiles"
voice_dir = "/opt/voices"
prompt_lines = []
errors = []

voices = sorted(os.listdir(profiles_dir))
total = len(voices)

for i, name in enumerate(voices):
    wav_path = os.path.join(profiles_dir, name, "ref_audio.wav")
    if not os.path.exists(wav_path):
        errors.append(name)
        continue
    try:
        audio, sr = sf.read(wav_path, dtype="float32")
        if len(audio.shape) > 1:
            audio = audio.mean(axis=1)
        if sr != 16000:
            import subprocess
            tmp = f"/tmp/{name}_16k.wav"
            subprocess.run(
                ["ffmpeg", "-y", "-i", wav_path, "-ar", "16000", "-ac", "1", tmp],
                capture_output=True, check=True,
            )
            audio, sr = sf.read(tmp, dtype="float32")
            os.unlink(tmp)
        segments, info = model.transcribe(audio, beam_size=5, language="en")
        text = " ".join(s.text.strip() for s in segments).strip()
        if text:
            prompt_lines.append(f"{name}|{text}")
        else:
            prompt_lines.append(f"{name}|Voice reference audio.")
    except Exception as e:
        errors.append(f"{name}: {e}")

    if (i + 1) % 30 == 0:
        print(f"  [{i+1}/{total}] transcribed...")

with open(os.path.join(voice_dir, "prompt_text"), "w") as f:
    f.write("\n".join(prompt_lines) + "\n")

elapsed = time.time() - start
print(f"Done: {len(prompt_lines)} voices transcribed in {elapsed:.1f}s ({len(errors)} errors)")
if errors:
    print(f"Errors: {errors[:5]}")
