"""Microphone recording (arecord / PipeWire) and offline speech-to-text with faster-whisper on CPU."""
from __future__ import annotations

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
        self._proc = subprocess.Popen(
            ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
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
    def __init__(self, model: str = "small.en"):
        from faster_whisper import WhisperModel

        self.model = WhisperModel(model, device="cpu", compute_type="int8",
                                  download_root=str(MODELS_DIR / "whisper"))

    def transcribe(self, audio: np.ndarray) -> str:
        if audio.size < RATE // 2:
            return ""
        segments, _ = self.model.transcribe(
            audio, language="en", beam_size=1, vad_filter=True,
            initial_prompt=TECH_PROMPT, condition_on_previous_text=False,
        )
        return " ".join(s.text.strip() for s in segments).strip()


class Listener:
    """Hands-free, always-on mic. Waits until you have finished speaking (silence_sec of quiet)
    and then hands the whole utterance to on_utterance(audio). `in_speech` is True while you talk,
    so callers can hold back the interviewer until you are done ("hear everything before speaking")."""

    FRAME = 480  # 30 ms at 16 kHz

    def __init__(self, on_utterance, silence_sec: float = 2.0, min_speech_sec: float = 0.5):
        self.on_utterance = on_utterance
        self.silence_sec = silence_sec
        self.min_speech_sec = min_speech_sec
        self.muted = False
        self.in_speech = False
        self.level = 0.0
        self.last_voice = 0.0
        self._proc: subprocess.Popen | None = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._stop.clear()
        self._proc = subprocess.Popen(
            ["arecord", "-q", "-f", "S16_LE", "-r", str(RATE), "-c", "1", "-t", "raw"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        if self._proc:
            self._proc.terminate()
            self._proc = None
        self.in_speech = False
        self.level = 0.0

    @property
    def running(self) -> bool:
        return self._proc is not None

    def _run(self) -> None:
        import time
        proc = self._proc
        assert proc and proc.stdout
        nbytes = self.FRAME * 2
        noise: list[float] = []
        thr = 0.015
        pre_roll: list[np.ndarray] = []
        speech: list[np.ndarray] = []
        voiced_frames = silent_frames = 0
        silence_limit = int(self.silence_sec / 0.03)
        while not self._stop.is_set():
            raw = proc.stdout.read(nbytes)
            if not raw or len(raw) < nbytes:
                break
            frame = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
            rms = float(np.sqrt(np.mean(frame ** 2)))
            self.level = min(1.0, rms * 8)
            if len(noise) < 33:  # ~1 s calibration of the room's noise floor
                noise.append(rms)
                if len(noise) == 33:
                    thr = max(0.012, float(np.median(noise)) * 3.0)
                continue
            if self.muted:
                pre_roll.clear(); speech.clear(); voiced_frames = silent_frames = 0
                self.in_speech = False
                continue
            loud = rms > thr
            if not self.in_speech:
                pre_roll.append(frame)
                pre_roll = pre_roll[-10:]
                voiced_frames = voiced_frames + 1 if loud else 0
                if voiced_frames >= 3:
                    self.in_speech = True
                    speech = list(pre_roll)
                    silent_frames = 0
                    self.last_voice = time.time()
                continue
            speech.append(frame)
            if loud:
                silent_frames = 0
                self.last_voice = time.time()
            else:
                silent_frames += 1
            if silent_frames >= silence_limit:
                self.in_speech = False
                voiced = len(speech) - silent_frames
                audio = np.concatenate(speech[: len(speech) - silent_frames + 5])
                speech, pre_roll, voiced_frames, silent_frames = [], [], 0, 0
                if voiced * 0.03 >= self.min_speech_sec:
                    self.on_utterance(audio)
