"""Hands-free, real-interviewer conversation loop for the Interview tab.

The interviewer:
- speaks every question and every reaction (TTS), muting the mic while talking unless you use headphones;
- listens all the time and waits until you have finished speaking before reacting ("hear everything first");
- if you keep talking while it is thinking, throws that reply away and reacts to everything you said;
- stays quiet while you code, peeks at the pad when you pause typing, checks in after long silences;
- says short acknowledgements ("Mm-hmm.", "Go on.") so you know it's listening;
- moves on when you say you're done ("that's my answer", "I'm done", "next question") or it judges the answer complete.
"""
from __future__ import annotations

import random
import re
import threading
import time
import traceback

from PySide6.QtCore import QObject, QTimer, Signal

DONE_RE = re.compile(r"\b((i'?m|i am) done with (my|the|this) (answer|solution|code)|i'?m done|i am done|that'?s (it|all|my answer)|that is (it|all|my answer)|done with (my|the|this) "
                     r"(answer|solution|code)|next question|move on|let'?s move on|i'?m finished|finished)\b", re.I)
BACKCHANNELS = ["Mm-hmm.", "Okay.", "Go on.", "Right.", "Hmm, okay."]


class LiveConversation(QObject):
    user_text = Signal(str, object)     # transcribed utterance, audio stats
    interviewer = Signal(str, str)      # text said, kind
    next_requested = Signal(str)        # reason
    state = Signal(str)                 # "listening" | "you" | "thinking" | "speaking" | "paused"
    _reaction = Signal(int, object)
    _utt = Signal(str, object)

    CODE_IDLE_SEC = 25      # typing paused this long -> may look at the pad
    MIN_GAP_SEC = 25        # min gap between unsolicited reactions
    SILENCE_THEORY = 30     # silent this long on a theory question -> check in
    SILENCE_CODE = 100      # silent and not typing this long while coding -> check in

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
        self.last_reaction = self.last_activity = self.last_edit = self.last_backchannel = time.time()
        self.question_spoken_at = time.time()
        self.code_seen = ""
        self._reaction.connect(self._on_reaction)
        self._utt.connect(self._on_utterance)
        self.tick = QTimer(self, interval=1000, timeout=self._tick)
        self.tts_watch = QTimer(self, interval=150, timeout=self._watch_tts)

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        from .stt import Listener
        tr = self.host.transcriber

        def on_utt(audio):
            def work():
                try:
                    from .soft import audio_stats
                    text = tr.transcribe(audio)
                    if text:
                        self._utt.emit(text, audio_stats(audio))
                except Exception:  # noqa: BLE001
                    traceback.print_exc()
            threading.Thread(target=work, daemon=True).start()

        self.listener = Listener(on_utt, silence_sec=self.patience)
        self.listener.start()
        self.active = True
        self.tick.start()
        self.state.emit("listening")

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
        self.state.emit("hold")
        if random.random() < 0.6:
            sp = self.host.speaker
            if sp and self.host.speak.isChecked():
                if self.listener and not self.headphones:
                    self.listener.muted = True
                sp.say(random.choice(["Okay.", "Alright.", "Noted.", "Okay, let's continue."]))
                self.tts_watch.start()

    def set_paused(self, paused: bool):
        self.paused = paused
        if self.listener:
            self.listener.muted = paused
        self.state.emit("paused" if paused else "listening")

    @property
    def level(self) -> float:
        return self.listener.level if self.listener else 0.0

    # ------------------------------------------------------------------ speaking
    def say(self, text: str, kind: str = "say"):
        """Interviewer speaks (and the UI shows it)."""
        if not text:
            return
        self.interviewer.emit(text, kind)
        sp = self.host.speaker
        if sp and self.host.speak.isChecked():
            if self.listener and not self.headphones:
                self.listener.muted = True  # don't transcribe our own voice from the speakers
            sp.say(text)
            self.state.emit("speaking")
            self.tts_watch.start()
        elif self.next_after_speech:
            self._fire_next("interviewer")

    def new_question(self, text: str):
        """Called when a new question is shown: speak it and reset the turn state."""
        self.holding = False
        self.gen += 1
        self.reacting = False
        self.pending = None
        self.next_after_speech = False
        now = time.time()
        self.last_reaction = self.last_activity = self.question_spoken_at = now
        self.code_seen = self.get_code()
        sp = self.host.speaker
        if sp:
            sp.stop()
        if self.listener and not self.headphones and sp and self.host.speak.isChecked():
            self.listener.muted = True
        if sp and self.host.speak.isChecked():
            sp.say(text)
            self.state.emit("speaking")
            self.tts_watch.start()

    def _watch_tts(self):
        sp = self.host.speaker
        if self.headphones and self.listener and self.listener.in_speech and sp and sp.busy:
            sp.stop()  # barge-in: you started talking over the interviewer
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
            self.state.emit("listening")

    # ------------------------------------------------------------------ hearing
    def _on_utterance(self, text: str, stats):
        if not self.active or self.holding:
            return
        self.last_activity = time.time()
        self.user_text.emit(text, stats)
        if DONE_RE.search(text) and len(text.split()) <= 14:
            self._fire_next("candidate")
            return
        self._request("utterance")

    def note_edit(self):
        self.last_edit = self.last_activity = time.time()

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
        self.state.emit("thinking")

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
        speaking_now = self.listener and self.listener.in_speech
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
        if (data.get("_event") == "utterance" and now - self.last_backchannel > 20 and random.random() < 0.45
                and not self.is_code_question()):
            self.last_backchannel = now
            self.say(random.choice(BACKCHANNELS), "ack")
        else:
            self.state.emit("listening")

    def _tick(self):
        if not self.active or self.paused or self.reacting or self.holding:
            return
        sp = self.host.speaker
        if (self.listener and self.listener.in_speech) or (sp and sp.busy):
            if self.listener and self.listener.in_speech:
                self.state.emit("you")
            return
        now = time.time()
        code = self.get_code()
        coding = self.is_code_question()
        since_q = now - self.question_spoken_at
        if (code != self.code_seen and now - self.last_edit >= self.CODE_IDLE_SEC
                and now - self.last_reaction >= self.MIN_GAP_SEC):
            self._request("code")
        elif since_q > 8 and now - self.last_activity >= (self.SILENCE_CODE if coding else self.SILENCE_THEORY) \
                and now - self.last_reaction >= (self.SILENCE_CODE if coding else self.SILENCE_THEORY):
            self._request("silence")
