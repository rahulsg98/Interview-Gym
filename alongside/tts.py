"""Offline text-to-speech with Piper. Default voice: L2-ARCTIC speaker ASI (Indian English, male)."""
from __future__ import annotations

import queue
import re
import shutil
import subprocess
import threading
import urllib.request
from pathlib import Path

from .config import MODELS_DIR

HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"

# name -> (path in repo, default speaker id, label)
VOICES = {
    "en_US-l2arctic-medium#10": ("en/en_US/l2arctic/medium/en_US-l2arctic-medium", 10, "Indian English male (ASI)"),
    "en_US-l2arctic-medium#19": ("en/en_US/l2arctic/medium/en_US-l2arctic-medium", 19, "Indian English male (RRBI)"),
    "en_US-kusal-medium#": ("en/en_US/kusal/medium/en_US-kusal-medium", None, "Kusal (South Asian English male)"),
    "en_US-ryan-high#": ("en/en_US/ryan/high/en_US-ryan-high", None, "US English male (Ryan)"),
    "en_GB-alan-medium#": ("en/en_GB/alan/medium/en_GB-alan-medium", None, "British English male (Alan)"),
}


def voice_key(voice: str, speaker: int | None) -> str:
    return f"{voice}#{'' if speaker is None else speaker}"


def ensure_voice(repo_path: str, progress=None) -> Path:
    name = repo_path.rsplit("/", 1)[-1]
    onnx = MODELS_DIR / f"{name}.onnx"
    for suffix in (".onnx.json", ".onnx"):
        dest = MODELS_DIR / f"{name}{suffix}"
        if dest.exists() and dest.stat().st_size > 0:
            continue
        if progress:
            progress(f"Downloading voice {name}{suffix} ...")
        tmp = dest.with_suffix(dest.suffix + ".part")
        urllib.request.urlretrieve(f"{HF_BASE}/{repo_path}{suffix}?download=true", tmp)
        tmp.rename(dest)
    return onnx


def _player() -> list[str]:
    """Command that plays a WAV stream from stdin."""
    if shutil.which("pw-play"):
        return ["pw-play", "-"]
    if shutil.which("paplay"):
        return ["paplay"]
    return ["aplay", "-q", "-"]


def _wav(pcm: bytes, rate: int) -> bytes:
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


class Speaker:
    """Speaks text sentence by sentence on a background thread. stop() interrupts."""

    def __init__(self, voice: str, speaker: int | None, rate: float = 1.0, progress=None):
        from piper import PiperVoice, SynthesisConfig

        repo_path, _, _ = VOICES.get(voice_key(voice, speaker), VOICES["en_US-l2arctic-medium#10"])
        self.voice = PiperVoice.load(ensure_voice(repo_path, progress))
        self.cfg = SynthesisConfig(speaker_id=speaker, length_scale=rate)
        self.rate = self.voice.config.sample_rate
        self.last_error = ""
        self._q: queue.Queue[str | None] = queue.Queue()
        self._proc: subprocess.Popen | None = None
        self._gen = 0
        self._active = False  # True from dequeue until playback of that sentence ends
        self._lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    @staticmethod
    def clean(text: str) -> str:
        text = re.sub(r"```.*?```", " (see the code on screen) ", text, flags=re.S)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"[*_#>|]+", " ", text)
        text = re.sub(r"https?://\S+", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def say(self, text: str) -> None:
        text = self.clean(text)
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            if sentence.strip():
                self._q.put(sentence)

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            while not self._q.empty():
                try:
                    self._q.get_nowait()
                except queue.Empty:
                    break
            if self._proc and self._proc.poll() is None:
                self._proc.kill()

    @property
    def busy(self) -> bool:
        return self._active or not self._q.empty() or (self._proc is not None and self._proc.poll() is None)

    def _loop(self) -> None:
        while True:
            sentence = self._q.get()
            if sentence is None:
                return
            self._active = True
            try:
                gen = self._gen
                pcm = b"".join(c.audio_int16_bytes for c in self.voice.synthesize(sentence, self.cfg))
                with self._lock:
                    if gen != self._gen:
                        continue
                    self._proc = subprocess.Popen(_player(), stdin=subprocess.PIPE,
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                proc = self._proc
                try:
                    proc.stdin.write(_wav(pcm, self.rate))
                    proc.stdin.close()
                except (BrokenPipeError, ValueError):
                    pass
                proc.wait()
                if proc.returncode not in (0, -9, -15) and gen == self._gen:
                    err = proc.stderr.read().decode(errors="ignore").strip() if proc.stderr else ""
                    import logging
                    logging.error("Audio playback failed (%s): %s", proc.returncode, err)
                    self.last_error = err or f"player exit code {proc.returncode}"
            except Exception as e:  # noqa: BLE001
                import logging
                logging.exception("TTS failed")
                self.last_error = str(e)
            finally:
                self._active = self._q.qsize() > 0
