"""Round Builder tab: research a company's loop, edit the rounds, and run a timed, hands-free mock loop."""
from __future__ import annotations

import html
import time
import traceback
import threading

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDoubleSpinBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
    QListWidget, QListWidgetItem, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSpinBox, QSplitter,
    QStackedWidget, QTableWidget, QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from . import loop as L
from . import screen, soft
from .interview import ROLES
from .knowledge import DIFFICULTIES
from .richview import RichView


def _font(size: int, bold: bool = False) -> QFont:
    f = QFont(); f.setPointSize(size); f.setBold(bold)
    return f


class LiveBridge(QObject):
    status = Signal(str)
    research_line = Signal(str)
    research_done = Signal(object)
    problem = Signal(int, object)
    utterance = Signal(str, object)
    reaction = Signal(int, object)
    round_done = Signal(int)
    report = Signal(str)
    error = Signal(str)
    screen_shot = Signal(object)
    saved = Signal(str)
    partial = Signal(str)
    main = Signal(object)    # run a callable on the GUI thread


class RoundBuilder(QWidget):
    # Tuning: how the interviewer decides to chime in.
    CODE_IDLE_SEC = 20       # typing paused this long -> interviewer may look at the code
    MIN_GAP_SEC = 30         # minimum gap between unsolicited reactions
    SILENCE_SEC = 120        # nothing from candidate this long -> nudge
    SCREEN_EVERY_SEC = 90

    def __init__(self, host):
        super().__init__()
        self.host = host
        self.b = LiveBridge()
        self.research: dict | None = None
        self.loop: L.Loop | None = None
        self.idx = -1
        self.listener = None
        self._heard = ""
        self.remaining = 0
        self.paused = False
        self.reacting = False
        self.react_gen = 0
        self.pending_event: str | None = None
        self.move_on_after_speech = False
        self.last_reaction = 0.0
        self.last_activity = time.time()
        self.last_edit = 0.0
        self.code_seen = ""
        self.last_screen = 0.0
        self.warned: set[int] = set()
        self.last_cam_shot = 0.0
        self.evaluating = 0
        self.loop_finished = False

        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.addWidget(self.stack)
        self.stack.addWidget(self._build_setup())
        self.stack.addWidget(self._build_live())
        self.stack.addWidget(self._build_debrief())

        b = self.b
        b.status.connect(lambda t: self.host.statusBar().showMessage(t))
        b.research_line.connect(self._on_research_line)
        b.research_done.connect(self._on_research_done)
        b.problem.connect(self._on_problem)
        b.utterance.connect(self._on_utterance)
        b.reaction.connect(self._on_reaction)
        b.partial.connect(self._on_partial)
        b.main.connect(lambda fn: fn())
        b.round_done.connect(self._on_round_done)
        b.report.connect(lambda t: self.report_view.setMarkdown(t))
        b.error.connect(self._on_error)
        b.saved.connect(self._on_saved)
        b.screen_shot.connect(lambda shot: self._request_reaction("screen", [shot]))

        self.clock = QTimer(self, interval=1000, timeout=self._tick)
        self.tts_watch = QTimer(self, interval=200, timeout=self._watch_tts)
        self.level_timer = QTimer(self, interval=100, timeout=self._update_level)
        self._load_cached()

    # =========================================================== setup page
    def _build_setup(self) -> QWidget:
        w = QWidget()
        split = QSplitter()
        QVBoxLayout(w).addWidget(split)

        left = QWidget(); lv = QVBoxLayout(left)
        t = QLabel("Round Builder"); t.setFont(_font(18, True)); lv.addWidget(t)
        lv.addWidget(QLabel("Research a company's real interview loop, then run it as a timed mock."))
        f = QFormLayout()
        self.company = QLineEdit(placeholderText="e.g. Flipkart, Razorpay, Atlassian, Google")
        self.company.returnPressed.connect(lambda: self.research_company(False))
        self.role = QComboBox(); self.role.addItems(ROLES); self.role.setEditable(True)
        self.diff = QComboBox()
        for d, desc in DIFFICULTIES.items():
            self.diff.addItem(f"{d}  ({desc.split(' (')[0]})", d)
        self.diff.setCurrentIndex(1)
        f.addRow("Company", self.company); f.addRow("Role", self.role); f.addRow("Difficulty", self.diff)
        lv.addLayout(f)
        rb = QHBoxLayout()
        self.research_btn = QPushButton("Research company", objectName="primary")
        self.research_btn.clicked.connect(lambda: self.research_company(False))
        self.reresearch_btn = QPushButton("Re-research")
        self.reresearch_btn.setToolTip("Ignore the cached research and search the web again")
        self.reresearch_btn.clicked.connect(lambda: self.research_company(True))
        self.clear_btn = QPushButton("🧹 Clear")
        self.clear_btn.setToolTip("Clear this screen, and optionally delete saved company research")
        self.clear_btn.clicked.connect(self.clear_setup)
        rb.addWidget(self.research_btn, 2); rb.addWidget(self.reresearch_btn, 1); rb.addWidget(self.clear_btn, 1)
        lv.addLayout(rb)
        self.research_log = QPlainTextEdit(readOnly=True)
        self.research_log.setMaximumHeight(130)
        self.research_log.setPlaceholderText("Research progress appears here (takes 1-4 minutes).")
        lv.addWidget(self.research_log)
        lv.addWidget(QLabel("Previously researched"))
        self.cached = QListWidget()
        self.cached.itemClicked.connect(self._open_cached)
        lv.addWidget(self.cached, 1)

        mid = QWidget(); mv = QVBoxLayout(mid)
        h = QLabel("Rounds (tick, reorder by editing, set minutes)"); h.setFont(_font(12, True)); mv.addWidget(h)
        self.rounds = QTableWidget(0, 4)
        self.rounds.setHorizontalHeaderLabels(["Use", "Round", "Type", "Minutes"])
        self.rounds.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.rounds.verticalHeader().hide()
        mv.addWidget(self.rounds, 1)
        rr = QHBoxLayout()
        add = QPushButton("+ Add round"); add.clicked.connect(lambda: self._add_round_row(
            {"name": "Extra round", "type": "DSA", "duration_min": 45}, True))
        rem = QPushButton("Remove selected"); rem.clicked.connect(
            lambda: self.rounds.removeRow(self.rounds.currentRow()) if self.rounds.currentRow() >= 0 else None)
        rr.addWidget(add); rr.addWidget(rem); rr.addStretch()
        mv.addLayout(rr)
        of = QFormLayout()
        self.patience = QDoubleSpinBox(minimum=1.5, maximum=10.0, singleStep=0.5,
                                       value=self.host.settings.answer_pause, suffix=" s")
        self.patience.setToolTip("How long you must be silent before the interviewer treats your turn as finished")
        self.time_scale = QDoubleSpinBox(minimum=0.25, maximum=1.5, singleStep=0.25, value=1.0, suffix="×")
        self.time_scale.setToolTip("Scale all round durations, e.g. 0.5× for a quick practice loop")
        self.watch_screen = QCheckBox("Also look at my whole screen every 90 s (for external IDE / whiteboard)")
        self.headphones = QCheckBox("I'm wearing headphones (let me interrupt the interviewer)")
        of.addRow("Wait after you stop talking", self.patience)
        of.addRow("Time scale", self.time_scale)
        mv.addLayout(of)
        mv.addWidget(self.watch_screen); mv.addWidget(self.headphones)
        self.start_btn = QPushButton("▶  Start timed loop", objectName="primary")
        self.start_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_loop)
        mv.addWidget(self.start_btn)

        self.research_view = RichView()
        self.research_view.setMarkdown("_Research results (rounds, reported questions, tips, sources) show here._")
        split.addWidget(left); split.addWidget(mid); split.addWidget(self.research_view)
        split.setSizes([330, 470, 520])
        return w

    def _add_round_row(self, r: dict, use: bool = True):
        row = self.rounds.rowCount()
        self.rounds.insertRow(row)
        chk = QTableWidgetItem(); chk.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled)
        chk.setCheckState(Qt.Checked if use else Qt.Unchecked)
        self.rounds.setItem(row, 0, chk)
        name = QTableWidgetItem(r.get("name", "Round"))
        name.setData(Qt.UserRole, r)
        name.setToolTip("\n".join(r.get("reported_questions", [])[:10]) or r.get("focus", ""))
        self.rounds.setItem(row, 1, name)
        typ = QComboBox(); typ.addItems(L.ROUND_TYPES); typ.setCurrentText(r.get("type", "DSA"))
        self.rounds.setCellWidget(row, 2, typ)
        mins = QSpinBox(minimum=5, maximum=180, value=int(r.get("duration_min", 45)), suffix=" min")
        self.rounds.setCellWidget(row, 3, mins)

    def clear_setup(self):
        if self.loop and not self.loop_finished:
            QMessageBox.information(self, "Interview Gym", "Finish or end the running loop first.")
            return
        box = QMessageBox(self)
        box.setWindowTitle("Clear Round Builder")
        box.setText("Clear the company, research findings and rounds from this screen?\n\n"
                    "'Also delete saved research' removes every cached company research, so the next search "
                    "starts fresh. Past interviews and your dashboard are kept.")
        screen_btn = box.addButton("Clear screen", QMessageBox.AcceptRole)
        all_btn = box.addButton("Also delete saved research", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (screen_btn, all_btn):
            return
        self.research = None
        self.company.clear()
        self.research_log.clear()
        self.rounds.setRowCount(0)
        self.start_btn.setEnabled(False)
        self.research_view.setMarkdown("_Research results (rounds, reported questions, tips, sources) show here._", "top")
        self._reset_live_page()
        self.stack.setCurrentIndex(0)
        if clicked is all_btn:
            n = 0
            for f in L.COMPANY_DIR.glob("*.json"):
                f.unlink(missing_ok=True); n += 1
            self._load_cached()
            self.b.status.emit(f"Round Builder cleared. Deleted {n} saved company research files.")
        else:
            self.b.status.emit("Round Builder cleared.")

    def _reset_live_page(self):
        """Loop over: wipe the live screen (everything is saved in Past Interviews)."""
        self.conv_view.clear(); self.editor.clear(); self.problem_view.clear()
        self._heard = ""

    def _load_cached(self):
        self.cached.clear()
        for c in L.cached_companies():
            it = QListWidgetItem(f"{c['company']} · {c['role']} · {c['difficulty']}  "
                                 f"({time.strftime('%d %b', time.localtime(c['researched']))})")
            it.setData(Qt.UserRole, str(c["path"]))
            self.cached.addItem(it)

    def _open_cached(self, item):
        import json
        from pathlib import Path
        d = json.loads(Path(item.data(Qt.UserRole)).read_text())
        self.company.setText(d.get("company", ""))
        self.role.setCurrentText(d.get("_role", self.role.currentText()))
        self.diff.setCurrentIndex(max(0, self.diff.findData(d.get("_difficulty", "Medium"))))
        self._on_research_done(d)

    def research_company(self, force: bool):
        company = self.company.text().strip()
        if not company:
            self.company.setFocus(); return
        self.research_btn.setEnabled(False); self.reresearch_btn.setEnabled(False)
        self.research_log.clear()
        self.research_log.appendPlainText(f"Researching {company} with web search…")
        role, diff, model = self.role.currentText(), self.diff.currentData(), self.host.model.currentText()

        def work():
            try:
                d = L.research_company(company, role, diff, model, on_status=self.b.research_line.emit, force=force)
                self.b.research_done.emit(d)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                self.b.error.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_research_line(self, line: str):
        self.research_log.appendPlainText(line)

    def _on_research_done(self, d: dict):
        self.research = d
        self.research_btn.setEnabled(True); self.reresearch_btn.setEnabled(True)
        self.research_view.setMarkdown(L.research_markdown(d))
        self.rounds.setRowCount(0)
        for r in d.get("rounds", []):
            self._add_round_row(r, True)
        self.start_btn.setEnabled(bool(d.get("rounds")))
        self.research_log.appendPlainText(f"Done: {len(d.get('rounds', []))} rounds found.")
        self._load_cached()

    # =========================================================== live page
    def _build_live(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        top = QHBoxLayout()
        self.round_lbl = QLabel(); self.round_lbl.setFont(_font(14, True))
        self.state_lbl = QLabel("…"); self.state_lbl.setStyleSheet("color:#8b93ab")
        self.timer_lbl = QLabel("00:00"); self.timer_lbl.setFont(_font(24, True))
        self.pause_btn = QPushButton("Pause"); self.pause_btn.clicked.connect(self.toggle_pause)
        self.done_btn = QPushButton("I'm done → next round"); self.done_btn.clicked.connect(self.end_round)
        self.next_btn = QPushButton("Start next round", objectName="primary")
        self.next_btn.clicked.connect(self.next_round); self.next_btn.hide()
        self.end_btn = QPushButton("End loop", objectName="danger"); self.end_btn.clicked.connect(self._end_clicked)
        top.addWidget(self.round_lbl); top.addSpacing(16); top.addWidget(self.state_lbl); top.addStretch()
        top.addWidget(self.timer_lbl); top.addSpacing(16)
        for btn in (self.pause_btn, self.done_btn, self.next_btn, self.end_btn):
            top.addWidget(btn)
        v.addLayout(top)

        split = QSplitter()
        left = QSplitter(Qt.Vertical)
        self.problem_view = RichView()
        conv = QWidget(); cv = QVBoxLayout(conv); cv.setContentsMargins(0, 0, 0, 0)
        self.conv_view = QTextBrowser()
        self.say_box = QLineEdit(placeholderText="Type to the interviewer (Enter) - or just talk, the mic is live")
        self.say_box.returnPressed.connect(self._typed_message)
        cv.addWidget(self.conv_view, 1); cv.addWidget(self.say_box)
        left.addWidget(self.problem_view); left.addWidget(conv); left.setSizes([330, 330])
        from .editor import Workspace
        right = QWidget(objectName="card"); rv = QVBoxLayout(right); rv.setContentsMargins(12, 10, 12, 12)
        self.workspace = Workspace("Workspace · the interviewer sees everything you type here",
                                   language=self.host.settings.code_language)
        self.workspace.code_lang = self.host.settings.code_language
        self.workspace.language_changed.connect(self.host._on_ws_language)
        self.editor = self.workspace.editor
        self.editor.setPlaceholderText("Write code here (pick the language above), or notes and design with "
                                       "{ } Code block snippets. Think aloud while you write.")
        self.editor.textChanged.connect(self._on_edit)
        rv.addWidget(self.workspace)
        split.addWidget(left); split.addWidget(right); split.setSizes([560, 700])
        v.addWidget(split, 1)

        bottom = QHBoxLayout()
        self.cam_view = QLabel("Camera off")
        self.cam_view.setFixedSize(160, 120)
        self.cam_view.setScaledContents(True)
        self.cam_view.setAlignment(Qt.AlignCenter)
        self.cam_view.setStyleSheet("background:#161a26; border:1px solid #252b3d; border-radius:6px; color:#5d6580")
        self.cam_stats = QLabel("")
        self.cam_stats.setStyleSheet("color:#8b93ab")
        bottom.addWidget(self.cam_view)
        self.cam_btn = QPushButton("📷 Camera off")
        self.cam_btn.setCheckable(True)
        self.cam_btn.setToolTip("Turn the camera on or off at any time during the loop")
        self.cam_btn.clicked.connect(lambda: self.host.toggle_camera_now())
        bottom.addWidget(self.cam_btn)
        self.mic_on = QCheckBox("Mic live (hands-free)", checked=True)
        self.mic_on.toggled.connect(lambda on: self.listener and setattr(self.listener, "muted", not on))
        self.level = QProgressBar(maximum=100, textVisible=False); self.level.setFixedWidth(160)
        mic_col = QVBoxLayout()
        mic_row = QHBoxLayout(); mic_row.addWidget(self.mic_on); mic_row.addWidget(self.level); mic_row.addStretch()
        mic_col.addLayout(mic_row); mic_col.addWidget(self.cam_stats)
        bottom.addLayout(mic_col); bottom.addStretch()
        bottom.addWidget(QLabel("Tip: think aloud. Arjun waits until you pause before replying."))
        v.addLayout(bottom)
        return w

    def _build_debrief(self) -> QWidget:
        w = QWidget(); v = QVBoxLayout(w)
        h = QHBoxLayout()
        t = QLabel("Loop debrief"); t.setFont(_font(18, True)); h.addWidget(t); h.addStretch()
        self.view_btn = QPushButton("Open in Past Interviews")
        self.view_btn.setEnabled(False)
        self.view_btn.clicked.connect(self._open_in_past)
        back = QPushButton("Back to Round Builder"); back.clicked.connect(lambda: self.stack.setCurrentIndex(0))
        h.addWidget(self.view_btn); h.addWidget(back)
        v.addLayout(h)
        self.report_view = RichView()
        v.addWidget(self.report_view)
        return w

    # =========================================================== loop control
    def _selected_rounds(self) -> list[L.LoopRound]:
        out = []
        scale = self.time_scale.value()
        for row in range(self.rounds.rowCount()):
            if self.rounds.item(row, 0).checkState() != Qt.Checked:
                continue
            item = self.rounds.item(row, 1)
            src = item.data(Qt.UserRole) or {}
            out.append(L.LoopRound(
                name=item.text(), type=self.rounds.cellWidget(row, 2).currentText(),
                duration_min=max(5, round(self.rounds.cellWidget(row, 3).value() * scale)),
                focus=src.get("focus", ""), reported=src.get("reported_questions", [])))
        return out

    def start_loop(self):
        rounds = self._selected_rounds()
        if not rounds or not self.research:
            return
        self.loop = L.Loop(company=self.research.get("company", self.company.text()), role=self.role.currentText(),
                           difficulty=self.diff.currentData(), research=self.research, rounds=rounds,
                           model=self.host.model.currentText())
        from . import resume as resume_mod
        info = resume_mod.cached(self.host.resume.toPlainText())
        self.loop.resume_brief = resume_mod.brief(info) if info else self.host.resume.toPlainText()[:5000]
        self.idx = -1
        self.loop_finished = False
        self.view_btn.setEnabled(False)
        self.conv_view.clear(); self.problem_view.clear(); self.report_view.clear()
        self.stack.setCurrentIndex(1)
        self._set_state("Loading speech models…")
        if self.host.use_cam.isChecked():
            self.host.start_camera()

        def work():
            try:
                self.host.ensure_models(self.b.status.emit)
                self.b.round_done.emit(-1)  # triggers first round
            except Exception as e:  # noqa: BLE001
                traceback.print_exc(); self.b.error.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def next_round(self):
        if not self.loop or self.loop_finished:
            return
        self.next_btn.hide()
        self.idx += 1
        if self.idx >= len(self.loop.rounds):
            self.end_loop()
            return
        r = self.loop.rounds[self.idx]
        self.round_lbl.setText(f"{self.loop.company} · Round {self.idx + 1}/{len(self.loop.rounds)}: {r.name}")
        self.editor.clear(); self.code_seen = ""
        if r.type == "Frontend Machine Coding" and self.workspace.code_lang not in ("JavaScript", "TypeScript"):
            self.workspace.code_lang = "JavaScript"
        self.workspace.set_language(self.workspace.code_lang if r.type in L.CODING_TYPES else "Notes")
        self.problem_view.setMarkdown("_Preparing the problem…_")
        self._log("—", f"Round {self.idx + 1}: {r.name} ({r.type}, {r.duration_min} min)")
        self._set_state("Arjun is preparing the problem…")
        self.done_btn.setEnabled(True)
        idx = self.idx
        lp = self.loop

        def work():
            try:
                problem = lp.start_round(r)
                if not getattr(lp, "aborted", False):
                    self.b.problem.emit(idx, problem)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc(); self.b.error.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_problem(self, idx: int, problem: dict):
        if not self.loop or self.loop_finished or idx != self.idx:
            return
        r = self.loop.rounds[idx]
        self.problem_view.setMarkdown(f"## {problem.get('title', r.name)}\n\n{problem.get('statement', '')}")
        self.remaining = r.duration_min * 60
        self.warned = set()
        self.paused = False
        self.last_activity = self.last_reaction = time.time()
        self.last_screen = time.time()
        self.react_gen += 1
        self.reacting = False
        self.pending_event = None
        self.move_on_after_speech = False
        self._start_listener()
        self.clock.start(); self._tick()
        self._speak(problem.get("intro", ""))
        self.editor.setFocus()

    def end_round(self):
        if not self.loop or self.idx < 0 or self.idx >= len(self.loop.rounds):
            return
        r = self.loop.rounds[self.idx]
        if r.ended:
            return
        self.clock.stop()
        self.react_gen += 1
        r.code = self.editor.toPlainText()
        r.ended = time.time()
        cam = self.host.camera
        if cam and cam.running:
            r.camera = cam.stats(r.started, r.ended)
        if self.listener:
            self.listener.muted = True
        self.done_btn.setEnabled(False)
        last = self.idx == len(self.loop.rounds) - 1
        closing = "Thanks, that's time for this round." if not last else "Thanks, that wraps up the interview."
        self._speak(closing)
        self._set_state("Round finished. Scoring in the background.")
        self.evaluating += 1

        lp = self.loop

        def work():
            try:
                lp.evaluate_round(r)  # saved only if the whole loop is completed (see end_loop)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                if not getattr(lp, "aborted", False):
                    self.b.error.emit(f"Scoring {r.name} failed: {e}")
            finally:
                self.evaluating -= 1
        threading.Thread(target=work, daemon=True).start()
        if last:
            QTimer.singleShot(1500, self.end_loop)
        else:
            self.next_btn.show()
            self._set_state("Take a breath. Press 'Start next round' when ready.")

    def _on_round_done(self, _idx: int):
        # Only used to start round 1 after models load.
        self.next_round()

    def _loop_complete(self) -> bool:
        """All selected rounds done (the last one may be ended once 90% of its time is used)."""
        lp = self.loop
        if not lp or self.idx != len(lp.rounds) - 1:
            return False
        r = lp.rounds[self.idx]
        if r.ended:
            return True
        return bool(r.started) and (time.time() - r.started) >= r.duration_min * 60 * 0.9

    def _end_clicked(self):
        if not self.loop or self.loop_finished:
            return
        if self._loop_complete():
            self.end_loop()
            return
        if QMessageBox.question(
                self, "End loop early?",
                "Not all rounds are finished.\n\nLoops ended early are discarded: no debrief, no history and "
                "nothing added to your dashboard.\n\nEnd and discard this loop?") == QMessageBox.Yes:
            self.abort_loop()

    def abort_loop(self):
        """Ended early: stop and throw the loop away (no scoring, saving or analysis)."""
        lp = self.loop
        if not lp:
            return
        lp.aborted = True
        self.loop_finished = True
        self.clock.stop()
        self.react_gen += 1
        self._stop_listener()
        if self.host.speaker:
            self.host.speaker.stop()
        if not self.host.interview_active():
            self.host.stop_camera()  # never left on after a loop
        self.loop = None
        self.next_btn.hide()
        self.stack.setCurrentIndex(0)
        self._reset_live_page()
        self.research_log.appendPlainText("Loop ended early and discarded (only completed loops are analysed).")
        self.b.status.emit("Loop ended early and discarded.")

    def end_loop(self):
        if not self.loop or self.loop_finished:
            return
        if not self._loop_complete():
            self.abort_loop()
            return
        self.loop_finished = True
        if not self.loop.rounds[self.idx].ended:
            self.end_round()
        self.clock.stop()
        self._stop_listener()
        if not self.host.interview_active():
            self.host.stop_camera()  # never left on after a loop
        self.stack.setCurrentIndex(2)
        self._reset_live_page()
        self.report_view.setMarkdown("_Waiting for round scores, then writing the hiring-committee debrief…_")

        def work():
            try:
                while self.evaluating > 0:
                    time.sleep(0.5)
                buf = []

                def chunk(c):
                    buf.append(c); self.b.report.emit("".join(buf))
                self.loop.final_report(on_text=chunk)
                self.loop.save_report()
                done = [r for r in self.loop.rounds if r.result]
                for r in done:  # completed loop: now (and only now) record every round
                    self.loop.save_round(r)
                self.b.saved.emit(self.loop.id)
                head = "\n".join(f"- **{r.name}**: {r.result.get('score')}/10 · {r.result.get('decision', '')}"
                                 for r in done)
                self.b.report.emit(f"### Round scores\n{head}\n\n---\n\n{self.loop.report}")
            except Exception as e:  # noqa: BLE001
                traceback.print_exc(); self.b.error.emit(str(e))
        threading.Thread(target=work, daemon=True).start()

    def _on_saved(self, loop_id: str):
        self._saved_id = loop_id
        self.view_btn.setEnabled(True)
        self.host.interviews.refresh(select_id=loop_id)
        self.host.interviews.generate_learnings(loop_id)
        self.b.status.emit("Loop saved. Its feedback, debrief and history are in Past Interviews.")

    def _open_in_past(self):
        self.host.interviews.refresh(select_id=getattr(self, "_saved_id", None))
        self.host.main_tabs.setCurrentWidget(self.host.interviews)

    def toggle_pause(self):
        self.paused = not self.paused
        self.pause_btn.setText("Resume" if self.paused else "Pause")
        if self.listener:
            self.listener.muted = self.paused or not self.mic_on.isChecked()
        self._set_state("Paused" if self.paused else "Listening…")

    # =========================================================== mic / speech
    def _start_listener(self):
        from .stt import LiveMic
        if self.listener:
            self.listener.stop()

        def on_text(text, audio):
            self.b.utterance.emit(text, soft.audio_stats(audio))

        self.listener = LiveMic(self.host.transcriber, on_text, on_partial=self.b.partial.emit,
                                silence_sec=self.patience.value())
        self.listener.muted = not self.mic_on.isChecked()
        self.listener.start()
        self.level_timer.start()

    def _stop_listener(self):
        if self.listener:
            self.listener.stop()
            self.listener = None
        self.level_timer.stop(); self.level.setValue(0)

    def _speak(self, text: str, log: bool = True):
        """Speak and (if log) show the line in the conversation the moment the voice starts."""
        if not text:
            return
        sp = self.host.speaker
        if not sp or not self.host.speak.isChecked():
            if log:
                self._log("Arjun", text)
            return
        if self.listener and not self.headphones.isChecked():
            self.listener.muted = True  # don't transcribe our own voice from the speakers
        sp.say(text, on_start=(lambda: self.b.main.emit(lambda: self._log("Arjun", text))) if log else None)
        self.tts_watch.start()
        self._set_state("Arjun is speaking…")

    def _watch_tts(self):
        sp = self.host.speaker
        if self.headphones.isChecked() and self.listener and self.listener.in_speech and sp and sp.busy:
            sp.stop()  # barge-in: you started talking over the interviewer
        if sp and sp.busy:
            return
        self.tts_watch.stop()
        if self.listener and not self.paused and self.mic_on.isChecked() and self.clock.isActive():
            QTimer.singleShot(350, lambda: self.listener and setattr(self.listener, "muted", False))
        if self.move_on_after_speech:
            self.move_on_after_speech = False
            self.end_round()
        elif self.clock.isActive():
            self._set_state("Listening…")

    def _update_level(self):
        if self.listener:
            self.level.setValue(int(self.listener.level * 100))
            if self.listener.silent and not self.listener.muted:
                self._set_state("⚠ Mic sends silence: the interviewer can't hear you. Pick another Microphone "
                                "on the Interview tab setup (earbuds in music mode have no mic).")
            elif self.listener.in_speech:
                if not self._heard:
                    self._set_state("🎙 You're speaking…")
            elif self.listener.transcribing:
                self._set_state("✎ Got it, writing down what you said…")
            else:
                self._heard = ""

    # =========================================================== interviewer brain
    def _current(self) -> L.LoopRound | None:
        if self.loop and 0 <= self.idx < len(self.loop.rounds) and self.clock.isActive():
            return self.loop.rounds[self.idx]
        return None

    def _on_partial(self, text: str):
        if self.listener and self.listener.busy:
            self._heard = text
            self._set_state("🎙 Heard: " + (text if len(text) <= 70 else "…" + text[-70:]))

    def _on_utterance(self, text: str, stats=None):
        r = self._current()
        if not r:
            return
        if stats:
            r.audio = soft.merge_audio_stats(r.audio, stats)
        self._heard = ""
        r.log.append((time.time(), "You", text))
        self._log("You", text)
        self.last_activity = time.time()
        self._request_reaction("utterance")

    def _typed_message(self):
        text = self.say_box.text().strip()
        r = self._current()
        if not text or not r:
            return
        self.say_box.clear()
        r.log.append((time.time(), "You (typed)", text))
        self._log("You (typed)", text)
        self.last_activity = time.time()
        self._request_reaction("typed")

    def _on_edit(self):
        self.last_edit = self.last_activity = time.time()

    def _request_reaction(self, event: str, images=()):
        r = self._current()
        if not r or self.paused:
            return
        if self.listener and (self.listener.in_speech or (event != "utterance" and self.listener.transcribing)):
            # Still talking or being transcribed: react once everything you said is in.
            if event != "silence":
                self.pending_event = event
            return
        if self.reacting:
            # The candidate said/did more while we were thinking: discard that reply and rethink with everything.
            self.react_gen += 1
            self.pending_event = event
            return
        self.reacting = True
        self.react_gen += 1
        gen = self.react_gen
        r.code = self.editor.toPlainText()
        self.code_seen = r.code
        self.last_reaction = time.time()
        self._set_state("Arjun is thinking…")
        remaining = self.remaining
        lp = self.loop

        def work():
            try:
                data = lp.react(r, event, remaining, images)
            except Exception as e:  # noqa: BLE001
                traceback.print_exc()
                data = {"action": "listen", "_error": str(e)}
            self.b.reaction.emit(gen, data)
        threading.Thread(target=work, daemon=True).start()

    def _on_reaction(self, gen: int, data: dict):
        self.reacting = False
        r = self._current()
        if data.get("_error"):
            self.b.status.emit("Interviewer error: " + data["_error"].splitlines()[0])
        if gen != self.react_gen or not r or (self.listener and self.listener.busy):
            # Stale, or you started talking again: hear you out first, then react to everything.
            ev = self.pending_event or "utterance"
            self.pending_event = None
            if r and not (self.listener and self.listener.busy):
                self._request_reaction(ev)
            elif r:
                self.pending_event = ev
            return
        if self.pending_event:
            ev, self.pending_event = self.pending_event, None
            self._request_reaction(ev)
            return
        if data.get("action") == "speak" and data.get("say"):
            r.log.append((time.time(), "Interviewer", data["say"]))
            self._speak(data["say"])
            self.move_on_after_speech = bool(data.get("move_on"))
            if self.move_on_after_speech and not (self.host.speaker and self.host.speak.isChecked()):
                self.end_round()
        else:
            self._set_state("Listening…")
            if data.get("move_on"):
                self.end_round()

    def _tick(self):
        r = self._current()
        if not r:
            return
        if not self.paused:
            self.remaining -= 1
        m, s = divmod(max(self.remaining, 0), 60)
        self.timer_lbl.setText(f"{m:02d}:{s:02d}")
        color = "#fb7185" if self.remaining <= 60 else "#fbbf24" if self.remaining <= 300 else "#e9ecf5"
        self.timer_lbl.setStyleSheet(f"color:{color}")
        if self.paused:
            return
        for mark, msg in ((300, "Just a heads up, about five minutes left."), (60, "One minute left, let's wrap up.")):
            if self.remaining == mark and mark not in self.warned and r.duration_min * 60 > mark * 2:
                self.warned.add(mark)
                r.log.append((time.time(), "Interviewer", msg)); self._speak(msg)
        if self.remaining <= 0:
            self.end_round()
            return
        now = time.time()
        speaking = self.listener and self.listener.in_speech
        cam = self.host.camera
        if cam and cam.running and speaking and now - self.last_cam_shot >= 150:
            self.last_cam_shot = now
            shot = cam.snapshot()
            if shot:
                r.camera_shots = (r.camera_shots + [str(shot)])[-3:]
        if self.listener and self.listener.busy:
            self.last_activity = now  # talking or still being transcribed is never silence
            return
        busy = self.reacting or speaking or (self.host.speaker and self.host.speaker.busy)
        if busy:
            return
        if self.pending_event:
            ev, self.pending_event = self.pending_event, None
            self._request_reaction(ev)
            return
        code = self.editor.toPlainText()
        if (code != self.code_seen and now - self.last_edit >= self.CODE_IDLE_SEC
                and now - self.last_reaction >= self.MIN_GAP_SEC):
            self._request_reaction("code")
        elif now - self.last_activity >= self.SILENCE_SEC and now - self.last_reaction >= self.SILENCE_SEC:
            self._request_reaction("silence")
        elif (self.watch_screen.isChecked() and now - self.last_screen >= self.SCREEN_EVERY_SEC
              and now - self.last_reaction >= self.MIN_GAP_SEC):
            self.last_screen = now
            self._screen_reaction()

    def _screen_reaction(self):
        def work():
            try:
                shot = screen.capture(interactive=False)
                screen.cleanup()
                self.b.screen_shot.emit(shot)
            except Exception as e:  # noqa: BLE001
                self.b.status.emit(f"Screen capture failed: {e}")
        threading.Thread(target=work, daemon=True).start()

    # =========================================================== misc ui
    def _set_state(self, text: str):
        self.state_lbl.setText(text)

    def _log(self, who: str, text: str):
        color = "#a78bfa" if who == "Arjun" else "#5eead4" if who.startswith("You") else "#8b93ab"
        self.conv_view.append(f'<p style="margin:6px 0"><span style="color:{color};font-weight:600">'
                              f'{html.escape(who)}</span>&nbsp; {html.escape(text)}</p>')
        sb = self.conv_view.verticalScrollBar(); sb.setValue(sb.maximum())

    def _on_error(self, msg: str):
        self.research_btn.setEnabled(True); self.reresearch_btn.setEnabled(True)
        self.research_log.appendPlainText("Error: " + msg)
        QMessageBox.warning(self, "Interview Gym", msg)

    def shutdown(self):
        self.clock.stop()
        self._stop_listener()
