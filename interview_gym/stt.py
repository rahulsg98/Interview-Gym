"""Microphone recording (arecord / PipeWire) and offline speech-to-text with faster-whisper on CPU."""
from __future__ import annotations

import logging
import subprocess
import threading

import numpy as np

from .config import MODELS_DIR

RATE = 16000

# Words Whisper should spell right in IT interviews.
TECH_PROMPT = (
    "Umm, so, uh, I think, like, you know, basically... "
    "Technical interview about software engineering: Kubernetes, Docker, CI/CD, Jenkins, Terraform, AWS, "
    "React, Next.js, TypeScript, JavaScript, Node.js, Spring Boot, Java, Python, Django, FastAPI, REST, GraphQL, "
    "gRPC, Kafka, Redis, PostgreSQL, MongoDB, SQL, NoSQL, microservices, load balancer, CAP theorem, sharding, "
    "LLD, HLD, SOLID, design patterns, O(n log n), hashmap, linked list, binary tree, dynamic programming."
)


# ---------------------------------------------------------------- microphone selection
# PipeWire node name of the mic to record from ("" = system default). Set via set_mic() / choose_mic().
MIC_NODE = ""


def list_mics() -> list[tuple[str, str]]:
    """[(node_name, description)] of real capture devices, from PipeWire."""
    import json
    try:
        out = subprocess.run(["pw-dump"], capture_output=True, text=True, timeout=5).stdout
        objs = json.loads(out)
    except Exception:  # noqa: BLE001
        return []
    mics = []
    for o in objs:
        props = (o.get("info") or {}).get("props") or {}
        if props.get("media.class") == "Audio/Source" and props.get("node.name"):
            mics.append((props["node.name"], props.get("node.description") or props["node.name"]))
    return mics


def set_mic(node: str) -> None:
    global MIC_NODE
    MIC_NODE = node or ""


def _arecord(node: str | None = None) -> subprocess.Popen:
    import os
    env = dict(os.environ)
    node = MIC_NODE if node is None else node
    if node:
        env["PIPEWIRE_NODE"] = node  # the ALSA→PipeWire bridge records from this device
    return subprocess.Popen(["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env=env)


def probe_mic(node: str = "", seconds: float = 1.2) -> float:
    """Loudest RMS heard from a mic in `seconds`. ~0 means it sends pure silence (muted, unplugged, or
    Bluetooth earbuds in music mode, which have no working microphone)."""
    import time
    proc = _arecord(node)
    levels: list[float] = []
    t0 = time.time()
    try:
        while time.time() - t0 < seconds:
            raw = proc.stdout.read(960)
            if len(raw) < 960:
                break
            f = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            levels.append(float(np.sqrt(np.mean(f ** 2))))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=2)
        except Exception:  # noqa: BLE001
            pass
    # 90th percentile, so a few stray blips from a dead mic don't count as "hearing something"
    return float(np.percentile(levels, 90)) if levels else 0.0


SILENT = 0.002  # a real mic's room noise is ~0.005-0.03; a dead or "music mode" one stays far below this


def choose_mic(preferred: str = "") -> tuple[str, str]:
    """Pick the mic to use and return (node, note). `preferred` = a node name, or "" for Auto:
    the system default if it actually hears something, otherwise the first device that does."""
    mics = list_mics()
    names = dict(mics)
    if preferred and preferred in names:
        if probe_mic(preferred) >= SILENT:
            set_mic(preferred)
            return preferred, ""
        note = f"'{names[preferred]}' is sending silence."
    else:
        if probe_mic("") >= SILENT:
            set_mic("")
            return "", ""
        note = "Your default microphone is sending silence (Bluetooth earbuds in music mode have no mic)."
    for node, desc in sorted(mics, key=lambda m: ("bluez" in m[0], "Headset" in m[0])):
        if node != preferred and probe_mic(node) >= SILENT:
            set_mic(node)
            return node, f"{note} Using '{desc}' instead."
    set_mic(preferred)
    return preferred, note + " No working microphone found: check the mic is on and not muted."


class Recorder:
    """Push-to-talk recorder. start() then stop() -> float32 mono 16 kHz audio."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None
        self._buf = bytearray()
        self._thread: threading.Thread | None = None
        self.level = 0.0

    @property
    def recording(self) -> bool:
        return self._proc is not None

    def start(self) -> None:
        self._buf = bytearray()
        self._proc = _arecord()
        self._thread = threading.Thread(target=self._read, daemon=True)
        self._thread.start()

    def _read(self) -> None:
        assert self._proc and self._proc.stdout
        while True:
            chunk = self._proc.stdout.read(3200)  # 100 ms
            if not chunk:
                break
            self._buf.extend(chunk)
            samples = np.frombuffer(chunk[: len(chunk) // 2 * 2], dtype=np.int16)
            if samples.size:
                self.level = float(min(1.0, np.sqrt(np.mean((samples / 32768.0) ** 2)) * 8))

    def stop(self) -> np.ndarray:
        if not self._proc:
            return np.zeros(0, dtype=np.float32)
        self._proc.terminate()
        self._proc.wait()
        if self._thread:
            self._thread.join(timeout=2)
        self._proc = None
        self.level = 0.0
        data = bytes(self._buf[: len(self._buf) // 2 * 2])
        return np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0


class Transcriber:
    """Speech to text, fully offline.
    "parakeet" (default): NVIDIA Parakeet TDT 0.6B v2 via ONNX (CC-BY-4.0). On this laptop it was the most accurate
    model tested on accented, noisy technical speech (9.2% word errors vs 9.8% for Whisper small.en) and ~8x faster.
    Whisper models (faster-whisper) remain available as alternatives."""

    PARAKEET = "nemo-parakeet-tdt-0.6b-v2"

    def __init__(self, model: str = "parakeet"):
        self._lock = threading.Lock()  # one transcription at a time: parallel runs just fight for the CPU
        self.engine = "parakeet" if model.startswith("parakeet") else "whisper"
        if self.engine == "parakeet":
            import onnx_asr
            import onnxruntime as ort
            so = ort.SessionOptions()
            so.intra_op_num_threads = 4
            so.log_severity_level = 3
            self.model = onnx_asr.load_model(self.PARAKEET, MODELS_DIR / "parakeet-tdt-0.6b-v2",
                                             quantization="int8", sess_options=so)
        else:
            from faster_whisper import WhisperModel
            self.model = WhisperModel(model, device="cpu", compute_type="int8",
                                      download_root=str(MODELS_DIR / "whisper"))

    def transcribe(self, audio: np.ndarray, context: str = "") -> str:
        if audio.size < RATE // 3:
            return ""
        with self._lock:
            if self.engine == "parakeet":
                return str(self.model.recognize(audio.astype(np.float32), sample_rate=RATE)).strip()
            prompt = TECH_PROMPT + (" " + context[-200:] if context else "")
            segments, _ = self.model.transcribe(
                audio, language="en", beam_size=1, vad_filter=True,
                initial_prompt=prompt, condition_on_previous_text=False,
            )
            return " ".join(s.text.strip() for s in segments).strip()


class SpeechDetector:
    """Silero neural voice-activity detector (bundled with faster-whisper), run live on 32 ms chunks.
    Returns the probability that a chunk contains human speech, so fans, typing, traffic and other
    background noise don't count as you talking."""

    CHUNK = 512  # 32 ms at 16 kHz

    def __init__(self):
        from faster_whisper.vad import get_vad_model
        self.session = get_vad_model().session
        self.reset()

    def reset(self) -> None:
        self.h = np.zeros((1, 1, 128), dtype=np.float32)
        self.c = np.zeros((1, 1, 128), dtype=np.float32)
        self.ctx = np.zeros(64, dtype=np.float32)

    def __call__(self, chunk: np.ndarray) -> float:
        x = np.concatenate([self.ctx, chunk.astype(np.float32)])[None, :]
        out, self.h, self.c = self.session.run(None, {"input": x, "h": self.h, "c": self.c})
        self.ctx = chunk[-64:].astype(np.float32)
        return float(np.asarray(out).reshape(-1)[0])


class Listener:
    """Hands-free, always-on mic.

    Speech is detected with a neural voice detector (Silero), so background noise doesn't count as talking.
    While you talk it hands finished pieces of speech (cut at short natural pauses) to on_segment(audio, False)
    so they're transcribed *while you are still speaking*. After silence_sec without speech it sends the rest
    with final=True: your turn is over. `in_speech` is True while you talk."""

    FRAME = SpeechDetector.CHUNK  # 32 ms
    SEC = FRAME / RATE
    START_PROB = 0.5     # clearly speech
    KEEP_PROB = 0.3      # once talking, lower bar so soft words don't end your turn
    WEAK_PROB = 0.25     # "maybe speech": counts only if it's also clearly louder than the room's noise
    MIN_STRONG = 4       # a turn needs at least this many clearly-speech frames, or it was just noise
    MIN_SHARE = 0.08     # ...and at least this share of its frames clearly speech (flukes in noise are rarer)
    PRE_ROLL = 32        # ~1 s of audio kept from before speech is detected, so first words are never lost
    PAUSE_SEC = 0.4      # at a short pause, hand over what you said so far (transcribed while you go on)
    MIN_PIECE_SEC = 1.0  # shortest piece worth transcribing on its own (earlier text is passed as context)
    MAX_PIECE_SEC = 20.0 # force a cut if you talk this long without pausing

    def __init__(self, on_segment, silence_sec: float = 1.5, min_speech_sec: float = 0.4):
        self.on_segment = on_segment
        self.silence_sec = silence_sec
        self.min_speech_sec = min_speech_sec
        self.muted = False
        self.in_speech = False
        self.level = 0.0
        self.prob = 0.0          # latest speech probability (0..1)
        self.last_voice = 0.0
        self.silent = False      # True when the mic has sent pure silence for a few seconds (wrong/dead mic)
        self.threshold = 0.0
        self.floor = 0.01        # room noise level (rms), learned from frames that aren't speech
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        from collections import deque
        self._quiet: deque = deque(maxlen=48)   # ~1.5 s: adapts quickly when the noise level changes
        self.strong = 0      # clearly-speech frames in the current turn
        try:
            self.vad = SpeechDetector()
        except Exception:  # noqa: BLE001
            self.vad = None      # fall back to loudness only

    def start(self) -> None:
        self._stop.clear()
        self._proc = _arecord()
        threading.Thread(target=self._run, args=(self._proc,), daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2)
            except Exception:  # noqa: BLE001
                pass
            self._proc = None
        self.in_speech = False
        self.level = 0.0

    @property
    def running(self) -> bool:
        return self._proc is not None

    def _is_voice(self, frame: np.ndarray, rms: float, noise_thr: float) -> bool:
        if self.vad is None:
            return rms > noise_thr
        p = self.prob = self.vad(frame)
        if p < 0.1:  # learn the noise floor from frames that clearly aren't speech
            self._quiet.append(rms)
            if len(self._quiet) % 8 == 0:
                self.floor = max(0.002, float(np.percentile(self._quiet, 75)))
        if p >= self.START_PROB:
            self.strong += 1
        if rms < 0.003:
            return False
        if p >= (self.KEEP_PROB if self.in_speech else self.START_PROB):
            return True
        # Speech under background noise often scores only 0.2-0.5: accept it if it's also clearly louder than the
        # room. Noise alone scores ~0 (and isn't louder than itself), so it never counts.
        return p >= self.WEAK_PROB and rms > self.floor * (1.6 if self.in_speech else 2.2)

    def _run(self, proc) -> None:
        import time
        from collections import deque
        assert proc and proc.stdout
        nbytes = self.FRAME * 2
        fps = 1 / self.SEC
        noise: deque = deque(maxlen=100)  # quiet frames -> noise floor (only used without the neural detector)
        recent: deque = deque(maxlen=100)  # last ~3 s of levels, to spot a dead mic
        thr = 0.015
        pre_roll: list[np.ndarray] = []
        speech: list[np.ndarray] = []
        sent = 0                 # frames of `speech` already handed over as pieces
        voiced_total = 0         # voiced frames in this utterance
        voiced_frames = silent_frames = 0
        silence_limit = max(1, int(self.silence_sec * fps))
        pause_limit = int(self.PAUSE_SEC * fps)
        min_piece, max_piece = int(self.MIN_PIECE_SEC * fps), int(self.MAX_PIECE_SEC * fps)

        def finish(upto: int) -> None:
            nonlocal speech, pre_roll, sent, voiced_total, voiced_frames, silent_frames
            frames = max(1, len(speech) - silent_frames)
            share = self.strong / frames
            real = self.vad is None or (self.strong >= self.MIN_STRONG and share >= self.MIN_SHARE)
            logging.info("mic: turn %.1fs, clear-speech frames %d (%.0f%%) -> %s", frames * self.SEC, self.strong,
                         100 * share, "speech" if real else "ignored (noise)")
            if real and (sent > 0 or voiced_total * self.SEC >= self.min_speech_sec):
                rest = speech[sent:upto]
                self.on_segment(np.concatenate(rest) if rest else np.zeros(0, np.float32), True)
            speech, pre_roll, sent, voiced_total, voiced_frames, silent_frames = [], [], 0, 0, 0, 0
            self.in_speech = False  # only after the final piece is queued, so callers never see a gap

        while not self._stop.is_set():
            raw = proc.stdout.read(nbytes)
            if not raw or len(raw) < nbytes:
                break
            frame = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(frame ** 2)))
            self.level = min(1.0, rms * 8)
            recent.append(rms)
            if len(recent) == recent.maxlen:
                self.silent = sorted(recent)[89] < SILENT
            if self.muted:
                if self.in_speech:
                    finish(len(speech))  # keep what you already said
                pre_roll.clear(); voiced_frames = 0
                if self.vad is not None:
                    self.vad.reset()
                continue
            if self.vad is None and not self.in_speech:
                if rms < thr * 1.5 or len(noise) < 33:
                    noise.append(rms)
                    if len(noise) >= 33 and len(noise) % 11 == 0:
                        thr = min(0.06, max(0.012, float(np.median(noise)) * 2.5))
                        self.threshold = thr
                if len(noise) < 33:
                    continue
            voice = self._is_voice(frame, rms, thr)
            if not self.in_speech:
                pre_roll.append(frame)
                pre_roll = pre_roll[-self.PRE_ROLL:]
                voiced_frames = voiced_frames + 1 if voice else 0
                if voiced_frames >= 3:  # ~0.1 s of clear speech starts your turn
                    self.strong = 0 if self.prob < self.START_PROB else 1
                    speech = list(pre_roll)
                    sent, voiced_total, silent_frames = 0, voiced_frames, 0
                    self.last_voice = time.time()
                    self.in_speech = True
                continue
            speech.append(frame)
            if voice:
                silent_frames = 0
                voiced_total += 1
                self.last_voice = time.time()
            else:
                silent_frames += 1
            if silent_frames >= silence_limit:
                finish(len(speech) - silent_frames + 5)
                continue
            piece = len(speech) - sent
            if (silent_frames == pause_limit and piece >= min_piece) or piece >= max_piece:
                self.on_segment(np.concatenate(speech[sent:]), False)
                sent = len(speech)


class LiveMic:
    """Listener + one background transcriber that keeps up while you speak.

    on_text(text, audio) fires once per finished utterance (full text, full audio);
    on_partial(text_so_far) fires as pieces are transcribed. Both run on a worker thread.
    `busy` is True from the moment you start talking until the final text has been delivered,
    so nobody mistakes "still transcribing" for "the candidate is silent"."""

    def __init__(self, transcriber: Transcriber, on_text, on_partial=None, silence_sec: float = 1.5,
                 on_turn_end=None):
        import queue
        self.transcriber = transcriber
        self.on_text = on_text
        self.on_partial = on_partial
        self.on_turn_end = on_turn_end  # called the instant your turn ends (before transcription finishes)
        self.listener = Listener(self._segment, silence_sec=silence_sec)
        self._q: queue.Queue = queue.Queue()
        self._pending = 0
        self._lock = threading.Lock()
        self._alive = False

    # pass-throughs so callers can use this like a Listener
    @property
    def muted(self) -> bool:
        return self.listener.muted

    @muted.setter
    def muted(self, value: bool) -> None:
        self.listener.muted = value

    @property
    def in_speech(self) -> bool:
        return self.listener.in_speech

    @property
    def level(self) -> float:
        return self.listener.level

    @property
    def silent(self) -> bool:
        return self.listener.silent

    @property
    def transcribing(self) -> bool:
        return self._pending > 0

    @property
    def busy(self) -> bool:
        return self.listener.in_speech or self._pending > 0

    def start(self) -> None:
        self._alive = True
        threading.Thread(target=self._work, daemon=True).start()
        self.listener.start()

    def stop(self) -> None:
        self._alive = False
        self.listener.stop()
        self._q.put(None)

    def _segment(self, audio: np.ndarray, final: bool) -> None:
        with self._lock:
            self._pending += 1
        self._q.put((audio, final))
        if final and self.on_turn_end:
            try:
                self.on_turn_end()
            except Exception:  # noqa: BLE001
                pass

    def _work(self) -> None:
        import logging
        texts: list[str] = []
        audios: list[np.ndarray] = []
        while True:
            item = self._q.get()
            if item is None:
                return
            audio, final = item
            try:
                if not self._alive:
                    continue
                text = self.transcriber.transcribe(audio, context=" ".join(texts)) if audio.size else ""
                if text:
                    texts.append(text)
                if audio.size:
                    audios.append(audio)
                if not final:
                    logging.info("mic: piece %.1fs -> %r", audio.size / RATE, text[:60])
                    if text and self.on_partial:
                        self.on_partial(" ".join(texts))
                    continue
                full = " ".join(texts).strip()
                whole = np.concatenate(audios) if audios else np.zeros(0, np.float32)
                logging.info("mic: turn ended, %.1fs of audio -> %d words", whole.size / RATE, len(full.split()))
                texts, audios = [], []
                if full and self._alive:
                    self.on_text(full, whole)
            except Exception:  # noqa: BLE001
                logging.exception("Transcription failed")
                if final:
                    texts, audios = [], []
            finally:
                with self._lock:
                    self._pending -= 1
