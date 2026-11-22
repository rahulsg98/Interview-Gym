"""Paths and persisted settings."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = Path(os.environ.get("ALONGSIDE_DATA", Path.home() / ".local/share/alongside"))
MODELS_DIR = DATA_DIR / "models"
SESSIONS_DIR = DATA_DIR / "sessions"
TMP_DIR = DATA_DIR / "tmp"
SETTINGS_FILE = DATA_DIR / "settings.json"

for _d in (MODELS_DIR, SESSIONS_DIR, TMP_DIR):
    _d.mkdir(parents=True, exist_ok=True)


@dataclass
class Settings:
    claude_model: str = "sonnet"          # sonnet | opus | haiku
    whisper_model: str = "parakeet"       # speech-to-text: parakeet (best) | small.en | base.en | tiny.en
    voice: str = "kokoro:hm_psi"          # natural Indian male (Kokoro); classic Piper voices are also available
    voice_speaker: int | None = None
    speech_rate: float = 1.25             # voice speed setting (Kokoro 1.25 ≈ 15% faster than its default pace)
    speak_questions: bool = True
    use_camera: bool = True
    hands_free: bool = True
    headphones: bool = False
    code_language: str = "Java"
    mic: str = ""                         # PipeWire mic node; "" = Auto (default mic, skipping silent ones)
    answer_pause: float = 3.0             # seconds of silence before Arjun treats your turn as finished
    profiles: dict = field(default_factory=dict)  # name -> {role, resume, jd, focus}

    @classmethod
    def load(cls) -> "Settings":
        if SETTINGS_FILE.exists():
            try:
                raw = json.loads(SETTINGS_FILE.read_text())
                return cls(**{k: v for k, v in raw.items() if k in cls.__dataclass_fields__})
            except Exception:
                pass
        return cls()

    def save(self) -> None:
        SETTINGS_FILE.write_text(json.dumps(asdict(self), indent=2))
