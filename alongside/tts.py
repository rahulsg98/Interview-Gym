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
    """Speaks text sentence by sentence. One thread synthesises ahead while another plays, so there are no
    gaps between sentences. say(text, on_start) calls on_start() (from a worker thread) the moment the first
    sentence actually starts playing, so callers can show the text in sync with the voice. stop() interrupts."""

    def __init__(self, voice: str, speaker: int | None, rate: float = 1.0, progress=None):
        from piper import PiperVoice, SynthesisConfig

        repo_path, _, _ = VOICES.get(voice_key(voice, speaker), VOICES["en_US-l2arctic-medium#10"])
        self.voice = PiperVoice.load(ensure_voice(repo_path, progress))
        self.cfg = SynthesisConfig(speaker_id=speaker, length_scale=rate)
        self.rate = self.voice.config.sample_rate
        self.last_error = ""
        self._text_q: queue.Queue = queue.Queue()   # (gen, sentence, on_start)
        self._play_q: queue.Queue = queue.Queue(maxsize=2)  # (gen, pcm, on_start)
        self._proc: subprocess.Popen | None = None
        self._gen = 0
        self._inflight = 0  # sentences queued, being synthesised or playing
        self._lock = threading.Lock()
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()

    @staticmethod
    def clean(text: str) -> str:
        text = re.sub(r"```.*?```", " (see the code on screen) ", text, flags=re.S)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"[*_#>|]+", " ", text)
        text = re.sub(r"https?://\S+", "", text)
        return re.sub(r"\s+", " ", text).strip()

    def say(self, text: str, on_start=None) -> None:
        sentences = [x for x in re.split(r"(?<=[.!?])\s+", self.clean(text)) if x.strip()]
        if not sentences:
            if on_start:
                on_start()
            return
        with self._lock:
            gen = self._gen
            self._inflight += len(sentences)
        for i, sentence in enumerate(sentences):
            self._text_q.put((gen, sentence, on_start if i == 0 else None))

    def stop(self) -> None:
        with self._lock:
            self._gen += 1
            if self._proc and self._proc.poll() is None:
                self._proc.kill()

    @property
    def busy(self) -> bool:
        return self._inflight > 0

    def _done(self) -> None:
        with self._lock:
            self._inflight = max(0, self._inflight - 1)

    @staticmethod
    def _fire(cb) -> None:
        if cb:
            try:
                cb()
            except Exception:  # noqa: BLE001
                import logging
                logging.exception("on_start callback failed")

    def _synth_loop(self) -> None:
        while True:
            gen, sentence, cb = self._text_q.get()
            if gen != self._gen:
                self._fire(cb)  # interrupted before it was spoken: still let the caller show the text
                self._done()
                continue
            try:
                pcm = b"".join(c.audio_int16_bytes for c in self.voice.synthesize(sentence, self.cfg))
            except Exception as e:  # noqa: BLE001
                import logging
                logging.exception("TTS failed")
                self.last_error = str(e)
                self._fire(cb)
                self._done()
                continue
            self._play_q.put((gen, pcm, cb))

    def _play_loop(self) -> None:
        import logging
        while True:
            gen, pcm, cb = self._play_q.get()
            try:
                if gen != self._gen:
                    self._fire(cb)
                    continue
                with self._lock:
                    if gen != self._gen:
                        self._fire(cb)
                        continue
                    self._proc = subprocess.Popen(_player(), stdin=subprocess.PIPE,
                                                  stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
                proc = self._proc
                self._fire(cb)
                try:
                    proc.stdin.write(_wav(pcm, self.rate))
                    proc.stdin.close()
                except (BrokenPipeError, ValueError):
                    pass
                proc.wait()
                if proc.returncode not in (0, -9, -15) and gen == self._gen:
                    err = proc.stderr.read().decode(errors="ignore").strip() if proc.stderr else ""
                    logging.error("Audio playback failed (%s): %s", proc.returncode, err)
                    self.last_error = err or f"player exit code {proc.returncode}"
            except Exception as e:  # noqa: BLE001
                logging.exception("Audio playback failed")
                self.last_error = str(e)
            finally:
                self._done()
