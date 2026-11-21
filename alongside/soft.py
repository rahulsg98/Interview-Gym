"""Soft skills: speech delivery metrics (pace, fillers, pauses, hedging) and a webcam confidence tracker.

Everything here runs locally. Only occasional camera snapshots are sent to Claude (if the camera is on), so it can
comment on posture, expression and visible nervousness, things simple metrics can't see.
"""
from __future__ import annotations

import re
import threading
import time
import urllib.request
from pathlib import Path

import numpy as np

from .config import MODELS_DIR, TMP_DIR

SOFT_SKILLS = ["Clarity", "Structure", "Conciseness", "Confidence", "Presence", "Listening", "Thinking aloud"]
SOFT_HELP = {
    "Clarity": "easy to follow, precise words, explains jargon, no rambling",
    "Structure": "top-down answers: headline first, then reasons/steps; STAR for behavioral",
    "Conciseness": "right length for the question, gets to the point",
    "Confidence": "steady voice, few fillers/hedges, owns decisions, composed under pressure",
    "Presence": "eye contact with camera, upright posture, engaged expression, not fidgety",
    "Listening": "answers what was asked, asks clarifying questions, handles follow-ups/hints well",
    "Thinking aloud": "narrates approach while coding/designing, checks in with interviewer",
}

FILLERS = [r"\bum+\b", r"\buh+\b", r"\berm+\b", r"\bhmm+\b", r"\bah+\b", r"\blike\b(?=,)", r"\bbasically\b",
           r"\bactually\b", r"\byou know\b", r"\bi mean\b", r"\bso yeah\b", r"\bkind of\b", r"\bsort of\b",
           r"\bright\?", r"\bokay so\b"]
HEDGES = [r"\bi think\b", r"\bmaybe\b", r"\bprobably\b", r"\bi guess\b", r"\bnot sure\b", r"\bi'm not sure\b",
          r"\bmight be\b", r"\bperhaps\b", r"\bi don't know\b", r"\bi believe\b"]


# ------------------------------------------------------------------------------------ speech metrics

def audio_stats(audio: np.ndarray, rate: int = 16000) -> dict:
    """Voiced time and pauses inside one recording."""
    if audio.size < rate // 4:
        return {"audio_sec": 0.0, "speech_sec": 0.0, "pauses": 0, "longest_pause": 0.0, "pause_sec": 0.0}
    frame = int(rate * 0.03)
    n = audio.size // frame
    rms = np.sqrt(np.mean(audio[: n * frame].reshape(n, frame) ** 2, axis=1))
    thr = max(0.01, float(np.percentile(rms, 20)) * 2.5)
    voiced = rms > thr
    idx = np.flatnonzero(voiced)
    if idx.size == 0:
        return {"audio_sec": audio.size / rate, "speech_sec": 0.0, "pauses": 0, "longest_pause": 0.0,
                "pause_sec": 0.0}
    v = voiced[idx[0]: idx[-1] + 1]  # trim leading/trailing silence
    pauses, run, longest, total = 0, 0, 0, 0
    for x in v:
        if not x:
            run += 1
        else:
            if run * 0.03 >= 0.8:
                pauses += 1; total += run
                longest = max(longest, run)
            run = 0
    return {"audio_sec": round(audio.size / rate, 1), "speech_sec": round(v.size * 0.03, 1), "pauses": pauses,
            "longest_pause": round(longest * 0.03, 1), "pause_sec": round(total * 0.03, 1)}


def merge_audio_stats(a: dict, b: dict) -> dict:
    if not b or "audio_sec" not in b:
        return dict(a or {})
    if not a or "audio_sec" not in a:
        return dict(b)
    return {"audio_sec": a["audio_sec"] + b["audio_sec"], "speech_sec": a["speech_sec"] + b["speech_sec"],
            "pauses": a["pauses"] + b["pauses"], "longest_pause": max(a["longest_pause"], b["longest_pause"]),
            "pause_sec": a["pause_sec"] + b["pause_sec"]}


def text_metrics(text: str) -> dict:
    low = text.lower()
    words = re.findall(r"[a-zA-Z']+", low)
    n = len(words)
    fillers = sum(len(re.findall(p, low)) for p in FILLERS)
    hedges = sum(len(re.findall(p, low)) for p in HEDGES)
    return {"words": n, "fillers": fillers, "hedges": hedges,
            "filler_rate": round(100 * fillers / n, 1) if n else 0.0,
            "hedge_rate": round(100 * hedges / n, 1) if n else 0.0}


def delivery(text: str, audio: dict | None) -> dict:
    """Combine transcript + audio stats into delivery metrics."""
    m = text_metrics(text)
    if audio and audio.get("speech_sec", 0) > 2:
        m.update(audio)
        m["wpm"] = round(m["words"] / (audio["speech_sec"] / 60))
        m["spoken"] = True
    else:
        m["spoken"] = False
    return m


def delivery_flags(m: dict) -> list[str]:
    """Rule-based observations a coach would point out."""
    out = []
    if not m.get("spoken"):
        return out
    wpm = m.get("wpm", 0)
    if wpm > 175:
        out.append(f"Speaking fast ({wpm} wpm). Aim for 130-160 so the interviewer can follow.")
    elif 0 < wpm < 105:
        out.append(f"Speaking slowly ({wpm} wpm). Sounds unsure; aim for 130-160.")
    if m.get("filler_rate", 0) >= 4:
        out.append(f"{m['filler_rate']} filler words per 100 words ({m['fillers']} total). Pause silently instead.")
    if m.get("hedge_rate", 0) >= 3:
        out.append(f"Lots of hedging ('I think', 'maybe'): {m['hedges']} times. State answers with conviction.")
    if m.get("longest_pause", 0) >= 5:
        out.append(f"A {m['longest_pause']}s silent gap. Narrate your thinking instead of going quiet.")
    return out


# ------------------------------------------------------------------------------------ camera

YUNET_URL = ("https://github.com/opencv/opencv_zoo/raw/main/models/face_detection_yunet/"
             "face_detection_yunet_2023mar.onnx")


def ensure_face_model() -> Path:
    p = MODELS_DIR / "face_detection_yunet_2023mar.onnx"
    if not p.exists() or p.stat().st_size < 100_000:
        urllib.request.urlretrieve(YUNET_URL, p)
    return p


def _enhance(bgr):
    import cv2
    y, cr, cb = cv2.split(cv2.cvtColor(bgr, cv2.COLOR_BGR2YCrCb))
    y = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(4, 4)).apply(y)
    return cv2.cvtColor(cv2.merge([y, cr, cb]), cv2.COLOR_YCrCb2BGR)


class CameraTracker:
    """Reads the webcam on a background thread and measures presence, eye contact and fidgeting.

    Eye contact is estimated from head pose: the nose should sit between the eyes (yaw) and between the eye line
    and mouth (pitch). It's an approximation of 'looking at the camera/screen', good enough to spot looking away
    or down a lot.
    """

    def __init__(self, device: int = 0, fps: float = 8.0):
        self.device = device
        self.fps = fps
        self._stop = threading.Event()
        self._lock = threading.Lock()
        self.frame = None            # latest BGR frame
        self.annotated = None        # latest frame with overlay (for preview)
        self.error = ""
        self._samples: list[tuple] = []  # ts, face, contact, move, brightness, backlit
        self._last_center = None
        self.running = False
        self.hint = ""                # live advice when the face can't be seen

    def start(self) -> None:
        if self.running:
            return
        self._stop.clear()
        self.running = True
        threading.Thread(target=self._run, daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        self.running = False

    def _run(self) -> None:
        import cv2
        try:
            det = cv2.FaceDetectorYN.create(str(ensure_face_model()), "", (320, 240), 0.7)
            cap = cv2.VideoCapture(self.device, cv2.CAP_V4L2)
            if not cap.isOpened():
                raise RuntimeError("Could not open the webcam (/dev/video0).")
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
        except Exception as e:  # noqa: BLE001
            self.error = str(e)
            self.running = False
            return
        period = 1.0 / self.fps
        while not self._stop.is_set():
            t0 = time.time()
            ok, frame = cap.read()
            if not ok:
                time.sleep(0.2)
                continue
            frame = cv2.flip(frame, 1)
            small = cv2.resize(frame, (320, 240))
            n, faces = det.detect(small)
            if faces is None or len(faces) == 0:
                n, faces = det.detect(_enhance(small))  # retry with shadows lifted (dim or backlit rooms)
            face = faces is not None and len(faces) > 0
            gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            backlit = float((gray > 245).mean()) > 0.02 and float(gray[60:180, 100:220].mean()) < 140
            contact, move = False, 0.0
            bright = float(small.mean())
            view = frame.copy()
            if face:
                f = max(faces, key=lambda x: x[2] * x[3])
                x, y, w, h = f[:4]
                re_, le = f[4:6], f[6:8]
                nose, rm, lm = f[8:10], f[10:12], f[12:14]
                eye_mid = (re_ + le) / 2
                eye_dist = max(np.linalg.norm(le - re_), 1)
                yaw = (nose[0] - eye_mid[0]) / eye_dist
                mouth_mid = (rm + lm) / 2
                span = max(mouth_mid[1] - eye_mid[1], 1)
                pitch = (nose[1] - eye_mid[1]) / span  # ~0.5-0.6 when frontal
                contact = abs(yaw) < 0.22 and 0.3 < pitch < 0.8
                center = np.array([x + w / 2, y + h / 2])
                if self._last_center is not None:
                    move = float(np.linalg.norm(center - self._last_center) / max(w, 1))
                self._last_center = center
                sx = frame.shape[1] / 320
                color = (99, 157, 31) if contact else (27, 138, 201)
                cv2.rectangle(view, (int(x * sx), int(y * sx)), (int((x + w) * sx), int((y + h) * sx)), color, 2)
            else:
                self._last_center = None
            if face:
                self.hint = "" if contact else "Look at the camera"
            elif backlit:
                self.hint = "Face not visible: bright light behind you. Face the light instead."
            elif bright < 60:
                self.hint = "Face not visible: room too dark"
            else:
                self.hint = "Face not visible: centre your whole face in frame"
            if self.hint:
                cv2.rectangle(view, (0, view.shape[0] - 34), (view.shape[1], view.shape[0]), (20, 20, 20), -1)
                cv2.putText(view, self.hint[:48], (8, view.shape[0] - 11), cv2.FONT_HERSHEY_SIMPLEX, 0.55,
                            (90, 200, 245), 1, cv2.LINE_AA)
            with self._lock:
                self.frame, self.annotated = frame, view
                self._samples.append((time.time(), face, contact, move, bright, backlit))
                if len(self._samples) > 20000:
                    self._samples = self._samples[-10000:]
            time.sleep(max(0.0, period - (time.time() - t0)))
        cap.release()

    def stats(self, since: float, until: float | None = None) -> dict:
        until = until or time.time()
        with self._lock:
            s = [x for x in self._samples if since <= x[0] <= until]
        if len(s) < 5:
            return {}
        face = [x for x in s if x[1]]
        moves = [x[3] for x in face if x[3] > 0]
        return {
            "camera_sec": round(s[-1][0] - s[0][0]),
            "presence": round(100 * len(face) / len(s)),
            "eye_contact": round(100 * sum(1 for x in face if x[2]) / max(len(face), 1)),
            "fidget": round(float(np.mean(moves)) * 100, 1) if moves else 0.0,  # % of face width per frame
            "brightness": round(float(np.mean([x[4] for x in s]))),
            "backlit": round(100 * sum(1 for x in s if x[5]) / len(s)),
        }

    def snapshot(self) -> Path | None:
        import cv2
        with self._lock:
            frame = None if self.frame is None else self.frame.copy()
        if frame is None:
            return None
        p = TMP_DIR / f"cam_{int(time.time() * 1000)}.jpg"
        cv2.imwrite(str(p), cv2.resize(frame, (480, 360)), [cv2.IMWRITE_JPEG_QUALITY, 80])
        return p

    def preview_rgb(self):
        """Latest annotated frame as (rgb bytes, w, h) for a Qt preview."""
        import cv2
        with self._lock:
            v = None if self.annotated is None else self.annotated
        if v is None:
            return None
        small = cv2.resize(v, (240, 180))
        rgb = cv2.cvtColor(small, cv2.COLOR_BGR2RGB)
        return rgb.tobytes(), 240, 180


def camera_flags(c: dict) -> list[str]:
    out = []
    if not c:
        return out
    if c.get("presence", 100) < 85:
        out.append(f"Out of frame {100 - c['presence']}% of the time. Stay centred in the camera.")
    if c.get("presence", 0) >= 30 and c.get("eye_contact", 100) < 60:
        out.append(f"Eye contact only {c['eye_contact']}% of the time. Look at the camera when making key points.")
    if c.get("fidget", 0) > 3:
        out.append(f"Lots of head movement (fidget score {c['fidget']}). Settle your posture.")
    if c.get("backlit", 0) > 30:
        out.append("Strong light behind you hides your face. Sit facing a window or lamp instead.")
    if c.get("brightness", 128) < 60:
        out.append("Your video is dark. Add light in front of you; it reads as more confident and engaged.")
    return out


def cleanup_snapshots(keep: int = 30) -> None:
    for p in sorted(TMP_DIR.glob("cam_*.jpg"))[:-keep]:
        p.unlink(missing_ok=True)


def soft_prompt_block(metrics: dict, camera: dict, n_screens: int, n_cams: int) -> str:
    """Text block appended to evaluation prompts so Claude can judge delivery, not only content."""
    lines = ["Delivery data measured locally (use it, but judge holistically):"]
    if metrics.get("spoken"):
        lines.append(f"- Spoken answer: {metrics['words']} words, {metrics.get('wpm')} wpm, "
                     f"{metrics['fillers']} fillers ({metrics['filler_rate']}/100 words), {metrics['hedges']} hedges, "
                     f"{metrics.get('pauses', 0)} pauses ≥0.8s, longest pause {metrics.get('longest_pause', 0)}s.")
    else:
        lines.append(f"- Answer was typed, not spoken ({metrics.get('words', 0)} words). Judge spoken skills as null.")
    if camera and camera.get("presence", 0) < 30:
        lines.append("- Webcam on but the face was mostly not visible (lighting/framing), so set Presence to null "
                     "and only mention the setup problem.")
    elif camera:
        lines.append(f"- Webcam: in frame {camera['presence']}%, looking at camera {camera['eye_contact']}%, "
                     f"fidget score {camera['fidget']} (0-1 calm, >3 restless), brightness {camera['brightness']}/255.")
    else:
        lines.append("- Webcam was off: set Presence to null.")
    if n_cams:
        lines.append(f"- The last {n_cams} image(s) are webcam snapshots of the candidate"
                     + (f" (the first {n_screens} image(s) are screenshots)." if n_screens else ".")
                     + " Comment on posture, expression and visible nervousness.")
    return "\n".join(lines)


SOFT_JSON = ('"soft_skills": {' + ", ".join(f'"{k}": <0-10 or null>' for k in SOFT_SKILLS) +
             ', "lacking": ["specific communication/confidence problems in THIS answer"], '
             '"good": ["what was good about delivery"]}')
SOFT_RUBRIC = "Soft-skill dimensions: " + "; ".join(f"{k} = {v}" for k, v in SOFT_HELP.items())
