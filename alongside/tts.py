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

# Natural voices: Kokoro-82M (Apache-2.0), local on the CPU. "kokoro:<voice>" or a blend "kokoro:a*0.6+b".
# hm_* are Kokoro's Hindi male voices; reading English they keep an Indian accent.
KOKORO_FILES = ("kokoro-v1.0.int8.onnx", "voices-v1.0.bin")
KOKORO_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/"

# name -> (path in repo, default speaker id, label)
VOICES = {
    "kokoro:hm_psi#": ("kokoro:hm_psi", None, "Natural · Indian male (Psi)"),
    "kokoro:hm_omega#": ("kokoro:hm_omega", None, "Natural · Indian male (Omega)"),
    "kokoro:hm_psi*0.6+am_michael#": ("kokoro:hm_psi*0.6+am_michael", None, "Natural · Indian-neutral male (blend)"),
    "kokoro:am_michael#": ("kokoro:am_michael", None, "Natural · US male (Michael)"),
    "kokoro:am_adam#": ("kokoro:am_adam", None, "Natural · US male (Adam)"),
    "kokoro:bm_george#": ("kokoro:bm_george", None, "Natural · British male (George)"),
    "en_US-l2arctic-medium#10": ("en/en_US/l2arctic/medium/en_US-l2arctic-medium", 10, "Classic (fast, robotic) · Indian English male (ASI)"),
    "en_US-l2arctic-medium#19": ("en/en_US/l2arctic/medium/en_US-l2arctic-medium", 19, "Classic (fast, robotic) · Indian English male (RRBI)"),
    "en_US-kusal-medium#": ("en/en_US/kusal/medium/en_US-kusal-medium", None, "Classic (fast, robotic) · Kusal (South Asian English male)"),
    "en_US-ryan-high#": ("en/en_US/ryan/high/en_US-ryan-high", None, "Classic (fast, robotic) · US English male (Ryan)"),
    "en_GB-alan-medium#": ("en/en_GB/alan/medium/en_GB-alan-medium", None, "Classic (fast, robotic) · British English male (Alan)"),
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


_KOKORO = None
_KOKORO_LOCK = threading.Lock()
_KOKORO_RUN = threading.Lock()


def kokoro_engine(progress=None):
    """Load Kokoro once (downloads ~120 MB the first time)."""
    global _KOKORO
    with _KOKORO_LOCK:
        if _KOKORO is None:
            import onnxruntime as ort
            from kokoro_onnx import Kokoro
            d = MODELS_DIR / "kokoro"
            d.mkdir(parents=True, exist_ok=True)
            for f in KOKORO_FILES:
                dest = d / f
                if not (dest.exists() and dest.stat().st_size > 0):
                    if progress:
                        progress(f"Downloading natural voice model {f} (first time only)…")
                    tmp = dest.with_suffix(dest.suffix + ".part")
                    urllib.request.urlretrieve(KOKORO_URL + f, tmp)
                    tmp.rename(dest)
            so = ort.SessionOptions()
            so.intra_op_num_threads = 4  # measured fastest on a 4-core/8-thread laptop CPU
            so.inter_op_num_threads = 1
            sess = ort.InferenceSession(str(d / KOKORO_FILES[0]), so, providers=["CPUExecutionProvider"])
            _KOKORO = Kokoro.from_session(sess, str(d / KOKORO_FILES[1]))
        return _KOKORO


def _kokoro_style(k, spec: str):
    """'hm_psi' or a blend like 'hm_psi*0.6+am_michael' -> voice name or blended style vector."""
    if "+" not in spec and "*" not in spec:
        return spec
    parts, total, style = [], 0.0, None
    for part in spec.split("+"):
        name, _, w = part.partition("*")
        parts.append((name.strip(), float(w) if w else None))
    given = sum(w for _, w in parts if w is not None)
    rest = [n for n, w in parts if w is None]
    for name, w in parts:
        w = w if w is not None else max(0.0, 1 - given) / max(1, len(rest))
        v = k.get_voice_style(name) * w
        style = v if style is None else style + v
        total += w
    return style / (total or 1)


def brighten(audio, sr: int = 24000):
    """Headset-mic style EQ: trims boomy bass (the Kokoro male voices are bass-heavy), lifts presence (2-5 kHz)
    for clarity, and normalises loudness. FFT-domain, so it's fast on short clauses."""
    import numpy as np
    a = np.asarray(audio, dtype=np.float32)
    if a.size < 256:
        return a
    n = 1 << int(np.ceil(np.log2(a.size + 512)))
    spec = np.fft.rfft(np.pad(a, (0, n - a.size)))
    f = np.fft.rfftfreq(n, 1 / sr)
    gain = np.ones_like(f)
    gain *= 1 / np.sqrt(1 + (120 / np.maximum(f, 1)) ** 4)          # 2nd-order high-pass at 120 Hz
    gain *= 1 - 0.45 * np.exp(-((f - 220) / 120) ** 2)               # -5 dB around 220 Hz (boom/mud)
    gain *= 1 + 0.6 * np.exp(-((f - 3200) / 1400) ** 2)              # +4 dB presence around 3.2 kHz
    out = np.fft.irfft(spec * gain, n)[: a.size]
    peak = float(np.max(np.abs(out))) or 1.0
    return (out * min(0.9 / peak, 4.0)).astype(np.float32)


def trim_pause(audio, sr: int, text: str):
    """Cut the silence the model pads around each clip and add a natural pause instead:
    short after a comma, longer after a full stop or question. Phrases spoken separately then flow like speech."""
    import numpy as np
    a = np.asarray(audio, dtype=np.float32)
    if a.size == 0:
        return a
    env = np.abs(a)
    thr = max(0.01, float(env.max()) * 0.02)
    idx = np.nonzero(env > thr)[0]
    if idx.size:
        a = a[max(0, idx[0] - int(0.02 * sr)): idx[-1] + int(0.04 * sr)]
    end = text.rstrip()[-1:] if text.strip() else ""
    gap = 0.05 if end == "," else 0.12 if end in ".!?" else 0.03
    return np.concatenate([a, np.zeros(int(gap * sr), np.float32)])


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
        repo_path, _, _ = VOICES.get(voice_key(voice, speaker), VOICES["en_US-l2arctic-medium#10"])
        self.natural = repo_path.startswith("kokoro:")
        if self.natural:
            k = kokoro_engine(progress)
            spec = repo_path.split(":", 1)[1]
            style = _kokoro_style(k, spec)
            lang = "en-gb" if spec.startswith("bm_") else "en-us"
            speed = rate or 1.0

            def synth(text: str) -> bytes:
                import numpy as np
                with _KOKORO_RUN:  # one generation at a time: the live voice never waits behind a second job
                    audio, _sr = k.create(text, voice=style, speed=speed, lang=lang)
                audio = trim_pause(brighten(audio, _sr), _sr, text)
                return (np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes()
            self.rate = 24000
        else:
            from piper import PiperVoice, SynthesisConfig
            pv = PiperVoice.load(ensure_voice(repo_path, progress))
            cfg = SynthesisConfig(speaker_id=speaker, length_scale=1.0 / (rate or 1.0))

            def synth(text: str) -> bytes:
                return b"".join(c.audio_int16_bytes for c in pv.synthesize(text, cfg))
            self.rate = pv.config.sample_rate
        self._synth = synth
        self._cache: dict[str, bytes] = {}
        self.last_error = ""
        self._text_q: queue.Queue = queue.Queue()   # (gen, sentence, on_start)
        self._play_q: queue.Queue = queue.Queue(maxsize=4)  # (gen, pcm, on_start)
        self._proc: subprocess.Popen | None = None
        self._gen = 0
        self._inflight = 0  # sentences queued, being synthesised or playing
        self._lock = threading.Lock()
        threading.Thread(target=self._synth_loop, daemon=True).start()
        threading.Thread(target=self._play_loop, daemon=True).start()
        if self.natural:  # after everything is set up
            threading.Thread(target=self._warm_cache, daemon=True).start()

    @staticmethod
    def clean(text: str) -> str:
        text = re.sub(r"```.*?```", " (see the code on screen) ", text, flags=re.S)
        text = re.sub(r"`([^`]*)`", r"\1", text)
        text = re.sub(r"[*_#>|]+", " ", text)
        text = re.sub(r"https?://\S+", "", text)
        text = re.sub(r"\b[Oo]kay\b", "Ok", text)  # "Ok" sounds more natural than "Okay" in this voice
        return re.sub(r"\s+", " ", text).strip()

    def say(self, text: str, on_start=None) -> None:
        sentences = [x for x in re.split(r"(?<=[.!?])\s+", self.clean(text)) if x.strip()]
        if self.natural:
            sentences = self._clauses(sentences)
        if not sentences:
            if on_start:
                on_start()
            return
        with self._lock:
            gen = self._gen
            self._inflight += len(sentences)
        for i, sentence in enumerate(sentences):
            self._text_q.put((gen, sentence, on_start if i == 0 else None))

    # Said often; generated once in the background so they play instantly with the natural voice.
    COMMON = ["Ok.", "Go on.", "Right.", "I see.", "Got it.", "Alright.", "Noted.", "Sure.", "Ok, go on.",
              "Ok, let's continue.", "Ok,", "Right,", "Alright,", "Sure,", "Good,", "So,", "Interesting,",
              "I see,", "Are you sure?",
              "Why?", "Go on, I'm listening.", "That's time. Thanks, we'll stop here.",
              "Ok, next question.", "Alright, moving on.", "Right, next one.", "Ok, let's go deeper."]
    LEAD_INS = {"question": ["Ok, next question.", "Alright, moving on.", "Right, next one."],
                "followup": ["Ok, let's go deeper.", "Ok,", "Right,"]}

    JOINERS = {"that", "which", "who", "where", "when", "while", "because", "so", "but", "and", "or", "if",
               "for", "with", "without", "using", "to", "in", "on", "at", "from", "into", "across", "between"}

    @staticmethod
    def _clauses(sentences: list[str]) -> list[str]:
        """Natural voice takes ~0.7 s + 0.6x the audio length to generate, so the first sentence is broken at
        commas (playback starts on a short phrase) and very long sentences are too. Commas are natural pauses."""
        out = []
        for i, sent in enumerate(sentences):
            if (i == 0 or len(sent.split()) > 14) and ", " in sent:
                parts = [x for x in re.split(r"(?<=,)\s+", sent) if x]
                merged: list[str] = []
                for part in parts:  # avoid fragments of 1-2 words, except leading fillers like "Ok,"
                    if merged and len(merged[-1].split()) < 3 and not (len(merged) == 1 and i == 0
                                                                      and merged[0] in Speaker.COMMON):
                        merged[-1] += " " + part
                    else:
                        merged.append(part)
                out += merged
            else:
                out.append(sent)
        if out:  # a long opening clause without commas: break it before a joining word so speech starts sooner
            first = out[0].split()
            if len(first) > 9:
                for j in range(4, len(first) - 3):
                    if first[j].lower() in Speaker.JOINERS:
                        out[0:1] = [" ".join(first[:j]), " ".join(first[j:])]
                        break
        return out

    def _warm_cache(self) -> None:
        import time
        for text in self.COMMON:
            while self._inflight > 0:  # live speech first; continue when Arjun is quiet
                time.sleep(0.2)
            try:
                self._cache[text] = self._synth(text)
            except Exception:  # noqa: BLE001
                return

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
                pcm = self._cache.get(sentence) or self._synth(sentence)
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
            merged = 0
            try:
                if gen != self._gen:
                    self._fire(cb)
                    continue
                # Phrases already generated play as one clip: no start-up gap between them.
                cbs = [cb]
                while True:
                    try:
                        g2, p2, cb2 = self._play_q.get_nowait()
                    except queue.Empty:
                        break
                    merged += 1
                    cbs.append(cb2)
                    if g2 == gen:
                        pcm += p2
                cb = (lambda fns=cbs: [self._fire(f) for f in fns]) if len(cbs) > 1 else cb
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
                for _ in range(merged + 1):
                    self._done()
