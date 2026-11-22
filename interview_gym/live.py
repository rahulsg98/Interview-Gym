"""Hands-free, real-interviewer conversation loop for the Interview tab.

The interviewer:
- speaks every question and every reaction (TTS), muting the mic while talking unless you use headphones;
- listens all the time, transcribes while you talk, and waits until you have finished speaking *and* your words
  are written down before reacting ("hear everything first"); transcribing never counts as silence;
- shows what it says at the moment the voice starts, not before;
- if you keep talking while it is thinking, throws that reply away and reacts to everything you said;
- stays quiet while you code, peeks at the pad when you pause typing, checks in after long silences;
- says short acknowledgements ("Ok.", "Go on.", "I see.") so you know it's listening;
- moves on when you say you're done ("that's my answer", "I'm done", "next question") or it judges the answer complete.
"""
from __future__ import annotations

import logging
import random
import re
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer, Signal

DONE_RE = re.compile(r"\b((i'?m|i am) done with (my|the|this) (answer|solution|code)|i'?m done|i am done|that'?s (it|all|my answer)|that is (it|all|my answer)|done with (my|the|this) "
                     r"(answer|solution|code)|next question|move on|let'?s move on|i'?m finished|finished)\b", re.I)
BACKCHANNELS = ["Ok.", "Right.", "Alright.", "Got it.", "I see.", "Go on.", "Ok, go on.", "Right, go on."]
HOLD_ACKS = ["Ok.", "Right.", "Alright.", "Got it.", "Noted.", "Ok, let's continue.", "Alright, let's continue."]
_last_pick: dict[str, str] = {}


OKAY_RE = re.compile(r"\b(okay|OKAY|Okay)\b")
OKAY_SUBS = ["Ok", "Got it", "Alright", "Right"]


def no_okay(text: str) -> str:
    """Arjun never says "Okay" (it sounds odd in the voice): use Ok / Got it / Alright / Right, varied,
    in both the text on screen and the speech."""
    def sub(m):
        w = pick("okay", OKAY_SUBS)
        return w if m.group(0)[0].isupper() else w.lower()
    return OKAY_RE.sub(sub, text or "")


def pick(name: str, options: list[str]) -> str:
    """Random phrase, never the same one twice in a row, so acknowledgements sound varied."""
    choice = random.choice([o for o in options if o != _last_pick.get(name)] or options)
    _last_pick[name] = choice
    return choice


class LiveConversation(QObject):
    user_text = Signal(str, object)     # transcribed utterance, audio stats
    interviewer = Signal(str, str)      # text said, kind
    next_requested = Signal(str)        # reason
    partial = Signal(str)               # words recognised so far while you are still talking
    state = Signal(str)                 # "listening" | "you" | "transcribing" | "thinking" | "speaking" | "paused" | "hold"
    _reaction = Signal(int, object)
    _utt = Signal(str, object)
    _main = Signal(object)              # run a callable on the GUI thread
    _turn_end = Signal()                # you just finished speaking (text still being transcribed)

    CODE_IDLE_SEC = 25      # typing paused this long -> may look at the pad
    MIN_GAP_SEC = 25        # min gap between unsolicited reactions
    SILENCE_THEORY = 5      # no speech at all (noise doesn't count) this long -> "take your time"
    SILENCE_CODE = 25       # no speech and no typing this long while coding -> check in
    NUDGE_BACKOFF = (1, 3, 6)  # 2nd nudge waits 3x as long, later ones 6x (5 s, 15 s, 30 s for theory)

    def __init__(self, host, react_fn, get_code, is_code_question, patience: float = 2.0, headphones: bool = False):
        """react_fn(event:str) -> dict runs on a worker thread and returns
        {"action": "listen"|"speak"|"next", "say": str, "kind": str}."""
        super().__init__()
        self.host = host
        self.react_fn = react_fn
        self.get_code = get_code
        self.is_code_question = is_code_question
        self.patience = patience
        self.headphones = headphones
        self.listener = None
        self.active = False
        self.holding = False
        self.paused = False
        self.reacting = False
        self.gen = 0
        self.pending: str | None = None
        self.next_after_speech = False
        self.last_reaction = self.last_activity = self.last_edit = time.time()
        self.last_backchannel = 0.0
        self.nudges = 0          # silence nudges since you last spoke
        self.question_spoken_at = time.time()
        self.code_seen = ""
        self._reaction.connect(self._on_reaction)
        self._utt.connect(self._on_utterance)
        self._main.connect(lambda fn: fn())
        self._turn_end.connect(self._on_turn_end)
        self._last_state = ""
        self.tick = QTimer(self, interval=1000, timeout=self._tick)
        self.tts_watch = QTimer(self, interval=150, timeout=self._watch_tts)

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        from .soft import audio_stats
        from .stt import LiveMic

        def on_text(text, audio):
            try:
                self._utt.emit(text, audio_stats(audio))
            except Exception:  # noqa: BLE001
                traceback.print_exc()

        self.listener = LiveMic(self.host.transcriber, on_text, on_partial=self.partial.emit,
                                silence_sec=self.patience, on_turn_end=self._turn_end.emit)
        self.listener.start()
        self.active = True
        self.tick.start()
        self._set_state("listening")

    def _set_state(self, st: str):
        if st != self._last_state:
            self._last_state = st
            self.state.emit(st)

    @property
    def mic_busy(self) -> bool:
        """You're talking, or what you said is still being written down."""
        return bool(self.listener and self.listener.busy)

    def stop(self):
        self.active = False
        self.tick.stop(); self.tts_watch.stop()
        self.gen += 1
        if self.listener:
            self.listener.stop()
            self.listener = None

    def hold(self):
        """Answer submitted: stop reacting until the next question arrives."""
        self.holding = True
        self.gen += 1
        self.reacting = False
        self.pending = None
        self.next_after_speech = False
        self._set_state("hold")
        if random.random() < 0.6:
            self._speak(pick("hold", HOLD_ACKS))
            self._set_state("hold")

    def set_paused(self, paused: bool):
        self.paused = paused
        if self.listener:
            self.listener.muted = paused
        self._set_state("paused" if paused else "listening")

    @property
    def level(self) -> float:
        return self.listener.level if self.listener else 0.0

    # ------------------------------------------------------------------ speaking
    def _speak(self, text: str, on_start=None) -> bool:
        """Speak text; on_start runs on the GUI thread when the voice actually starts. False if voice is off."""
        sp = self.host.speaker
        if not (sp and self.host.speak.isChecked()):
            return False
        if self.listener and not self.headphones:
            self.listener.muted = True  # don't transcribe our own voice from the speakers
        sp.say(text, on_start=(lambda: self._main.emit(on_start)) if on_start else None)
        self._set_state("speaking")
        self.tts_watch.start()
        return True

    def say(self, text: str, kind: str = "say"):
        """Interviewer speaks; the UI shows the text when the voice starts (immediately if voice is off)."""
        text = no_okay(text)
        if not text:
            return
        if not self._speak(text, lambda: self.interviewer.emit(text, kind)):
            self.interviewer.emit(text, kind)
            if self.next_after_speech:
                self._fire_next("interviewer")

    def new_question(self, text: str, on_start=None, kind: str = "question", first: bool = False):
        """Called for a new question: speak it, reset the turn state. on_start() runs (GUI thread) when the voice
        starts, or right away if voice is off, so the question appears in writing as Arjun starts asking it."""
        self.holding = False
        self.gen += 1
        self.reacting = False
        self.pending = None
        self.next_after_speech = False
        now = time.time()
        self.last_reaction = self.last_activity = self.question_spoken_at = now
        self.nudges = 0
        self.code_seen = self.get_code()
        sp = self.host.speaker
        if sp:
            sp.stop()
        spoken = text
        if sp and getattr(sp, "natural", False) and not first and kind in sp.LEAD_INS:
            # Natural voice needs ~2 s to generate a long question: open with an instant, natural lead-in.
            spoken = pick("lead-" + kind, sp.LEAD_INS[kind]) + " " + text
        if not self._speak(spoken, on_start) and on_start:
            on_start()

    def _watch_tts(self):
        sp = self.host.speaker
        # Arjun always finishes what he's saying (no barge-in): with headphones the mic keeps listening, so
        # anything you say meanwhile is still heard and answered afterwards.
        if sp and sp.busy:
            return
        self.tts_watch.stop()
        now = time.time()  # silence is counted from when the interviewer stops talking
        self.question_spoken_at = now
        self.last_activity = max(self.last_activity, now)
        if self.listener and self.active and not self.paused:
            QTimer.singleShot(350, lambda: self.listener and setattr(self.listener, "muted", self.paused))
        if self.next_after_speech:
            self._fire_next("interviewer")
        elif self.active and not self.holding:
            self._set_state("listening")

    # ------------------------------------------------------------------ hearing
    def _on_utterance(self, text: str, stats):
        logging.info("live: heard %d words: %s", len(text.split()), text[:120])
        if not self.active or self.holding:
            logging.info("live: ignored (active=%s holding=%s)", self.active, self.holding)
            return
        self.last_activity = time.time()
        self.nudges = 0
        self.user_text.emit(text, stats)
        if DONE_RE.search(text) and len(text.split()) <= 14:
            self._fire_next("candidate")
            return
        self._request("utterance")

    def _on_turn_end(self):
        if self.active and not self.holding and not self.paused:
            self._set_state("transcribing")
            self._quick_ack()

    def _quick_ack(self):
        """A short "Ok." / "I see." right after you pause, so you know Arjun is with you while he thinks.
        Only with headphones (on speakers it would mute the mic and could clip your next words)."""
        now = time.time()
        sp = self.host.speaker
        if (self.headphones and sp and self.host.speak.isChecked() and not sp.busy and not self.is_code_question()
                and now - self.last_backchannel > 6 and random.random() < 0.8):
            self.last_backchannel = now
            sp.say(pick("ack", BACKCHANNELS))

    def note_edit(self):
        self.last_edit = self.last_activity = time.time()
        self.nudges = 0

    def typed_message(self):
        self.last_activity = time.time()
        self._request("typed")

    def _fire_next(self, reason: str):
        self.next_after_speech = False
        self.gen += 1
        self.reacting = False
        self.pending = None
        self.next_requested.emit(reason)

    # ------------------------------------------------------------------ deciding
    def _request(self, event: str):
        if not self.active or self.paused or self.holding:
            return
        if self.listener and (self.listener.in_speech or (event != "utterance" and self.listener.transcribing)):
            # You're still talking (or it's still being written down): react once everything is in.
            self.pending = event if event != "silence" else self.pending
            return
        if self.reacting:
            # More came in while we were thinking: discard that reply and rethink with everything.
            self.gen += 1
            self.pending = event
            return
        self.reacting = True
        self.gen += 1
        gen = self.gen
        self.last_reaction = time.time()
        self.code_seen = self.get_code()
        self._set_state("thinking")

        def work():
            try:
                data = self.react_fn(event)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                data = {"action": "listen", "_error": str(e)}
            data["_event"] = event
            self._reaction.emit(gen, data)
        threading.Thread(target=work, daemon=True).start()

    def _on_reaction(self, gen: int, data: dict):
        self.reacting = False
        if not self.active or self.holding:
            return
        speaking_now = self.mic_busy
        if gen != self.gen or speaking_now:
            ev, self.pending = (self.pending or "utterance"), None
            if self.active and not speaking_now:
                self._request(ev)
            elif self.active:
                self.pending = ev  # you're talking: hear you out first
            return
        if self.pending:
            ev, self.pending = self.pending, None
            self._request(ev)
            return
        action = data.get("action", "listen")
        say = (data.get("say") or "").strip()
        ev = data.get("_event")
        logging.info("live: %s -> %s %s %s", ev, action, data.get("kind", ""), say[:80])
        if ev == "utterance" and action == "speak" and (data.get("kind") == "nudge" or re.search(
                r"take your time|no rush|talk me through what you'?re thinking", say, re.I)):
            action, say = "listen", ""  # you just spoke: never answer that with "take your time"
        if ev == "silence" and action == "speak":
            self.nudges += 1
        if action == "next":
            if say:
                self.next_after_speech = True
                self.say(say, data.get("kind", "transition"))
            else:
                self._fire_next("interviewer")
            return
        if action == "speak" and say:
            self.say(say, data.get("kind", "probe"))
            return
        # listen: sometimes acknowledge so the candidate knows we're here
        now = time.time()
        if (data.get("_event") == "utterance" and now - self.last_backchannel > 8 and random.random() < 0.6
                and not self.is_code_question()):
            self.last_backchannel = now
            self.say(pick("ack", BACKCHANNELS), "ack")
        else:
            self._set_state("listening")

    def _tick(self):
        if not self.active or self.paused or self.reacting or self.holding:
            return
        sp = self.host.speaker
        now = time.time()
        if self.listener and self.listener.silent and not self.listener.muted:
            self._set_state("nomic")  # the mic delivers nothing: say so instead of looking "stuck"
        elif self._last_state == "nomic":
            self._set_state("listening")
        if self.mic_busy:
            # Talking or being transcribed is activity, never silence.
            self.last_activity = now
            self._set_state("you" if self.listener.in_speech else "transcribing")
            return
        if sp and sp.busy:
            return
        if self.pending:
            ev, self.pending = self.pending, None
            self._request(ev)
            return
        code = self.get_code()
        coding = self.is_code_question()
        since_q = now - self.question_spoken_at
        if (code != self.code_seen and now - self.last_edit >= self.CODE_IDLE_SEC
                and now - self.last_reaction >= self.MIN_GAP_SEC):
            self._request("code")
        else:
            base = self.SILENCE_CODE if coding else self.SILENCE_THEORY
            wait = base * self.NUDGE_BACKOFF[min(self.nudges, len(self.NUDGE_BACKOFF) - 1)]
            if (since_q >= base and now - self.last_activity >= wait and now - self.last_reaction >= wait
                    and not self.reacting):
                logging.info("live: %.0fs of silence -> check in (nudge #%d)", now - self.last_activity, self.nudges + 1)
                self._request("silence")
