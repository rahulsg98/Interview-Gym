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
    whisper_model: str = "small.en"       # tiny.en | base.en | small.en
    voice: str = "en_US-l2arctic-medium"
    voice_speaker: int | None = 10        # 10 = ASI (Indian English, male)
    speech_rate: float = 1.0              # >1 slower, <1 faster (piper length_scale)
    speak_questions: bool = True
    use_camera: bool = True
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
