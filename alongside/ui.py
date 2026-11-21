"""AlongSide desktop UI (PySide6)."""
from __future__ import annotations

import html
import sys
import threading
import time
import traceback
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QFont, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication, QCheckBox, QComboBox, QFileDialog, QFormLayout, QHBoxLayout, QInputDialog, QLabel,
    QLineEdit, QListWidget, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar, QPushButton,
    QSpinBox, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QScrollArea, QFrame, QStackedWidget,
)

from . import screen
from .config import SESSIONS_DIR, Settings
from .dashboard import Dashboard
from .interview import (CODE_SEGMENTS, DIFFICULTIES, DURATIONS, ROLES, ROUNDS, SEGMENTS, Profile, Session, Turn,
                        improvement_plan)
from . import resume as resume_mod
from .knowledge import DIFFICULTIES as DIFF_DESC, TIER_NAMES
from . import progress
from . import soft
from PySide6.QtGui import QImage, QPixmap
from .tts import VOICES, voice_key

STYLE = """
QMainWindow, QWidget#root { background: #14161b; color: #e6e6e6; }
QLabel, QCheckBox { color: #c9ccd3; }
QPushButton#primary:disabled, QPushButton#mic:disabled { background: #2a2f3a; border-color: #3a404d; }
QTextBrowser, QPlainTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget {
  background: #1d2027; color: #e6e6e6; border: 1px solid #2c313b; border-radius: 6px; padding: 6px; }
QPushButton { background: #2a2f3a; color: #e6e6e6; border: 1px solid #3a404d; border-radius: 6px; padding: 7px 12px; }
QPushButton:hover { background: #343a47; }
QPushButton:disabled { color: #6b7080; }
QPushButton#primary { background: #2f6fed; border-color: #2f6fed; font-weight: 600; }
QPushButton#mic { background: #1f7a4d; border-color: #1f7a4d; font-weight: 600; min-height: 34px; }
QPushButton#mic[rec="true"] { background: #c0392b; border-color: #c0392b; }
QPushButton#danger { background: #8e2a20; border-color: #c0392b; font-weight: 600; }
QPushButton#danger:hover { background: #a93226; }
QPushButton#danger:disabled { background: #2a2f3a; border-color: #3a404d; }
QScrollArea, QScrollArea > QWidget > QWidget { background: #14161b; }
QTableWidget { background: #1d2027; color: #e6e6e6; }
QHeaderView::section { background: #1d2027; color: #9aa0ac; border: none; padding: 4px; }
QTableCornerButton::section { background: #1d2027; border: none; }
QScrollBar:vertical { background: #14161b; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #3a404d; border-radius: 4px; min-height: 30px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: #14161b; height: 10px; margin: 0; }
QScrollBar::handle:horizontal { background: #3a404d; border-radius: 4px; min-width: 30px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QTabWidget::pane { border: 1px solid #2c313b; border-radius: 6px; }
QTabBar::tab { background: #1d2027; color: #c9ccd3; padding: 7px 14px; }
QTabBar::tab:selected { background: #2a2f3a; color: white; }
QProgressBar { background: #1d2027; border: 1px solid #2c313b; border-radius: 4px; height: 8px; }
QProgressBar::chunk { background: #1f9d63; }
"""


class Bridge(QObject):
    status = Signal(str)
    chat = Signal(str, str)          # who, text
    question = Signal(object)        # Turn
    feedback = Signal(object)        # Turn
    transcript = Signal(str)
    stream = Signal(str)             # streamed chunk for the side panel
    report = Signal(str)
    error = Signal(str)
    ready = Signal()
    busy = Signal(bool)
    restore = Signal()
    submit_now = Signal()
    plan = Signal(str)
    hint_ready = Signal(str)
    agenda = Signal(object)
    resume_done = Signal(object)


def run_bg(bridge: Bridge, fn, *args, busy: bool = True):
    def target():
        if busy:
            bridge.busy.emit(True)
        try:
            fn(*args)
        except Exception as e:  # noqa: BLE001
            traceback.print_exc()
            bridge.error.emit(str(e))
        finally:
            if busy:
                bridge.busy.emit(False)
    threading.Thread(target=target, daemon=True).start()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("AlongSide - Mock Interview Practice")
        self.resize(1320, 840)
        self.settings = Settings.load()
        self.b = Bridge()
        self.session: Session | None = None
        self.speaker = None
        self.transcriber = None
        self.recorder = None
        self._pending = 0

        self.main_tabs = QTabWidget()
        self.main_tabs.setDocumentMode(True)
        self.setCentralWidget(self.main_tabs)
        root = QWidget(objectName="root")
        lay = QHBoxLayout(root)
        self.iv_stack = QStackedWidget()
        lay.addWidget(self.iv_stack)
        setup_page = QWidget()
        sp_lay = QHBoxLayout(setup_page); sp_lay.setContentsMargins(0, 0, 0, 0)
        split = QSplitter()
        sp_lay.addWidget(split)
        self.iv_stack.addWidget(setup_page)
        self.main_tabs.addTab(root, "Interview")
        from .builder import RoundBuilder
        self.builder = RoundBuilder(self)
        self.builder.setObjectName("root")
        self.main_tabs.addTab(self.builder, "Round Builder")
        self.dashboard = Dashboard()
        self.dashboard.setObjectName("root")
        self.main_tabs.addTab(self.dashboard, "Dashboard")
        self.main_tabs.currentChanged.connect(lambda i: self.main_tabs.widget(i) is self.dashboard and self.dashboard.refresh())
        self.dashboard.plan_requested.connect(self.generate_plan)
        self.dashboard.practice_requested.connect(self.practice_area)
        setup_scroll = QScrollArea(widgetResizable=True)
        setup_scroll.setFrameShape(QFrame.NoFrame)
        setup_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        setup_scroll.setWidget(self._build_setup())
        setup_scroll.setMinimumWidth(320)
        left = QWidget()
        lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(setup_scroll, 1)
        lv.addWidget(self.start_btn)  # pinned so it's always visible
        split.addWidget(left)
        split.addWidget(self._build_side())
        split.setSizes([460, 900])
        self.iv_stack.addWidget(self._build_interview())  # page 1: live interview

        self.level_bar = QProgressBar(maximum=100, textVisible=False)
        self.level_bar.setFixedWidth(140)
        self.statusBar().addPermanentWidget(QLabel("Mic"))
        self.statusBar().addPermanentWidget(self.level_bar)
        self.statusBar().setStyleSheet("color:#9aa0ac")
        self._level_timer = QTimer(self, interval=100, timeout=self._update_level)
        self.camera = None
        self._cam_timer = QTimer(self, interval=150, timeout=self._update_camera)

        b = self.b
        b.status.connect(self.statusBar().showMessage)
        b.chat.connect(self._append_chat)
        b.question.connect(self._on_question)
        b.feedback.connect(self._on_feedback)
        b.transcript.connect(self._on_transcript)
        b.stream.connect(self._on_stream)
        b.report.connect(self._on_report)
        b.error.connect(self._on_error)
        b.ready.connect(self._on_ready)
        b.busy.connect(self._on_busy)
        b.restore.connect(self.showNormal)
        b.submit_now.connect(self.submit_answer)
        b.plan.connect(self.dashboard.show_plan)
        b.agenda.connect(self._on_agenda)
        b.hint_ready.connect(self._on_hint)
        b.resume_done.connect(self._on_resume_done)
        self._clock = QTimer(self, interval=1000, timeout=self._tick)

        QShortcut(QKeySequence("Ctrl+Space"), self, activated=self.toggle_mic)
        QShortcut(QKeySequence("Ctrl+Return"), self, activated=self.submit_answer)
        QShortcut(QKeySequence("Ctrl+H"), self, activated=self.ask_hint)
        QShortcut(QKeySequence("Ctrl+Shift+S"), self, activated=lambda: self.review_screen(False))
        quit_act = QAction("Quit", self, shortcut=QKeySequence("Ctrl+Q"), triggered=self.close)
        self.addAction(quit_act)

        self._set_interview_enabled(False)
        self._load_profile_names()
        self.statusBar().showMessage("Fill in your profile, then press Start interview.")

    # ------------------------------------------------------------------ layout
    def _build_setup(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        title = QLabel("AlongSide")
        f = QFont(); f.setPointSize(20); f.setBold(True); title.setFont(f)
        v.addWidget(title)
        v.addWidget(QLabel("Mock interview practice"))

        prow = QHBoxLayout()
        self.profile_box = QComboBox()
        self.profile_box.activated.connect(lambda _: self._apply_profile(self.profile_box.currentText()))
        save = QPushButton("Save")
        save.clicked.connect(self._save_profile)
        delete = QPushButton("Delete")
        delete.clicked.connect(self._delete_profile)
        prow.addWidget(self.profile_box, 1)
        prow.addWidget(save)
        prow.addWidget(delete)
        v.addLayout(prow)

        f = QFormLayout()
        self.role = QComboBox(); self.role.addItems(ROLES); self.role.setEditable(True)
        self.difficulty = QComboBox()
        for d in DIFFICULTIES:
            self.difficulty.addItem(f"{d}  ({DIFF_DESC[d].split(' (')[0]})", d)
        self.difficulty.setCurrentIndex(1)
        self.tier = QComboBox(); self.tier.addItems(TIER_NAMES); self.tier.setCurrentText("Product unicorn")
        self.tier.setToolTip("Startup → Indian product unicorns (Flipkart, Razorpay, Swiggy…) → "
                             "Big Tech (Microsoft, Amazon, Atlassian, Uber) → Top tier (Google, Meta)")
        self.company = QLineEdit(placeholderText="optional, e.g. Flipkart, Atlassian, Google")
        self.round = QComboBox(); self.round.addItems(ROUNDS)
        self.duration = QComboBox()
        for m in DURATIONS:
            self.duration.addItem(f"{m} min" if m < 60 else f"{m // 60} hr" + (f" {m % 60} min" if m % 60 else ""), m)
        self.duration.setCurrentIndex(DURATIONS.index(45))
        self.duration.setToolTip("The agenda (resume / theory / coding / machine coding / design) is planned to fit "
                                 "this length, and the interview ends when time is up.")
        self.focus = QLineEdit(placeholderText="e.g. React hooks, Kafka, K8s networking")
        f.addRow("Role", self.role)
        f.addRow("Difficulty", self.difficulty)
        f.addRow("Company tier", self.tier)
        f.addRow("Company", self.company)
        f.addRow("Round", self.round)
        f.addRow("Duration", self.duration)
        f.addRow("Focus", self.focus)
        v.addLayout(f)

        rrow = QHBoxLayout()
        rrow.addWidget(QLabel("Resume"))
        self.resume_status = QLabel("")
        self.resume_status.setStyleSheet("color:#9aa0ac; font-size:11px")
        upload = QPushButton("Upload resume…")
        upload.clicked.connect(self._upload_resume)
        self.resume_view_btn = QPushButton("Analysis")
        self.resume_view_btn.setToolTip("Show the claims Arjun will verify")
        self.resume_view_btn.clicked.connect(self._show_resume_analysis)
        rrow.addWidget(self.resume_status, 1); rrow.addWidget(upload); rrow.addWidget(self.resume_view_btn)
        v.addLayout(rrow)
        self.resume = QPlainTextEdit(placeholderText="Upload your resume (.pdf / .docx / .txt / .md) or paste it. "
                                                     "Arjun will always grill your experience section.")
        self.resume.textChanged.connect(self._refresh_resume_status)
        v.addWidget(self.resume, 2)

        jrow = QHBoxLayout()
        jrow.addWidget(QLabel("Job description (optional)"))
        loadj = QPushButton("Load file…")
        loadj.clicked.connect(lambda: self._load_file(self.jd))
        jrow.addStretch(); jrow.addWidget(loadj)
        v.addLayout(jrow)
        self.jd = QPlainTextEdit(placeholderText="Paste the JD to get company-specific questions")
        v.addWidget(self.jd, 1)

        f2 = QFormLayout()
        self.model = QComboBox(); self.model.addItems(["sonnet", "opus", "haiku"])
        self.model.setCurrentText(self.settings.claude_model)
        self.voice = QComboBox()
        for key, (_, _, label) in VOICES.items():
            self.voice.addItem(label, key)
        idx = self.voice.findData(voice_key(self.settings.voice, self.settings.voice_speaker))
        self.voice.setCurrentIndex(max(idx, 0))
        self.whisper = QComboBox(); self.whisper.addItems(["base.en", "small.en", "tiny.en"])
        self.whisper.setCurrentText(self.settings.whisper_model)
        self.speak = QCheckBox("Speak questions aloud", checked=self.settings.speak_questions)
        self.live_fb = QCheckBox("Show feedback after each answer", checked=True)
        self.use_cam = QCheckBox("Camera on: judge confidence && presence", checked=self.settings.use_camera)
        self.use_cam.setToolTip("Webcam is analysed locally (eye contact, posture, fidgeting). Occasional snapshots "
                                "go to Claude for feedback on expression and posture.")
        self.use_cam.toggled.connect(self._camera_toggled)
        f2.addRow("Claude model", self.model)
        f2.addRow("Voice", self.voice)
        f2.addRow("Speech model", self.whisper)
        v.addLayout(f2)
        v.addWidget(self.speak)
        v.addWidget(self.live_fb)
        v.addWidget(self.use_cam)
        self.hands_free = QCheckBox("Hands-free: talk with Arjun like a real call", checked=self.settings.hands_free)
        self.hands_free.setToolTip("Arjun speaks, listens continuously, waits until you finish, reacts, nudges and "
                                   "gives occasional hints. Say \"I'm done\" (or press Ctrl+Enter) to finish an answer.")
        self.headphones = QCheckBox("I'm wearing headphones (lets me interrupt Arjun)", checked=self.settings.headphones)
        v.addWidget(self.hands_free)
        v.addWidget(self.headphones)

        self.start_btn = QPushButton("Start interview", objectName="primary")
        self.start_btn.clicked.connect(self.start_interview)
        return w

    def _build_interview(self) -> QWidget:
        """Full-width live interview screen: question + conversation on the left, writing space on the right."""
        w = QWidget()
        v = QVBoxLayout(w)
        top = QHBoxLayout()
        self.agenda_lbl = QLabel("")
        self.agenda_lbl.setWordWrap(True)
        self.agenda_lbl.setTextFormat(Qt.RichText)
        self.clock_lbl = QLabel("")
        f = QFont(); f.setPointSize(18); f.setBold(True); self.clock_lbl.setFont(f)
        self.live_state = QLabel("")
        self.live_state.setStyleSheet("color:#9aa0ac; font-weight:600")
        self.end_top_btn = QPushButton("■  End interview", objectName="danger")
        self.end_top_btn.setToolTip("Stop now and get the scored report")
        self.end_top_btn.clicked.connect(self._confirm_end)
        self.end_top_btn.setEnabled(False)
        top.addWidget(self.agenda_lbl, 1); top.addWidget(self.live_state); top.addSpacing(10)
        top.addWidget(self.clock_lbl); top.addSpacing(10); top.addWidget(self.end_top_btn)
        v.addLayout(top)

        main = QSplitter()
        # ---- left: current question + conversation
        left = QSplitter(Qt.Vertical)
        self.q_card = QLabel("<i>Arjun will ask the first question in a moment…</i>")
        self.q_card.setWordWrap(True)
        self.q_card.setTextFormat(Qt.RichText)
        self.q_card.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        self.q_card.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self.q_card.setStyleSheet("background:#1d2027; border:1px solid #2f6fed; border-radius:8px; padding:14px;"
                                  "font-size:16px; color:#e6e6e6")
        q_scroll = QScrollArea(widgetResizable=True)
        q_scroll.setFrameShape(QFrame.NoFrame)
        q_scroll.setWidget(self.q_card)
        self.chat_view = QTextBrowser(openExternalLinks=True)
        left.addWidget(q_scroll); left.addWidget(self.chat_view)
        left.setSizes([260, 420])

        # ---- right: writing space, both always visible
        right = QWidget()
        rv = QVBoxLayout(right); rv.setContentsMargins(0, 0, 0, 0)
        self.write_split = QSplitter(Qt.Vertical)
        ans_box = QWidget(); av = QVBoxLayout(ans_box); av.setContentsMargins(0, 0, 0, 0)
        av.addWidget(QLabel("Your answer: live transcript of what you say (you can also type or edit)"))
        self.answer = QPlainTextEdit()
        self.answer.setPlaceholderText("Just talk. Your words appear here. Ctrl+Enter: submit   Ctrl+H: hint   "
                                       "Ctrl+Space: mute/unmute   Ctrl+Shift+S: review my screen")
        av.addWidget(self.answer)
        pad_box = QWidget(); pv = QVBoxLayout(pad_box); pv.setContentsMargins(0, 0, 0, 0)
        pv.addWidget(QLabel("Code / design pad: Arjun reads everything you write here"))
        self.pad = QPlainTextEdit()
        from PySide6.QtGui import QFontDatabase
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont); mono.setPointSize(12)
        self.pad.setFont(mono)
        self.pad.setTabStopDistance(4 * self.pad.fontMetrics().horizontalAdvance(" "))
        self.pad.setPlaceholderText("Write code for coding rounds. For system design, outline components, APIs, "
                                    "schema and numbers (or draw in a whiteboard app and press 'Review my screen').")
        pv.addWidget(self.pad)
        self.write_split.addWidget(ans_box); self.write_split.addWidget(pad_box)
        self.write_split.setSizes([300, 300])
        rv.addWidget(self.write_split, 1)
        self.live_fb_view = QTextBrowser(openExternalLinks=True)
        self.live_fb_view.setVisible(False)

        main.addWidget(left); main.addWidget(right); main.addWidget(self.live_fb_view)
        main.setSizes([520, 760, 0])
        self._live_main = main
        v.addWidget(main, 1)

        self._answer_cache = self._pad_cache = self._pad_snapshot = ""
        self.live = None
        self.answer.textChanged.connect(lambda: setattr(self, "_answer_cache", self.answer.toPlainText().strip()))

        def _pad_changed():
            self._pad_cache = self.pad.toPlainText()
            if self.live:
                self.live.note_edit()
        self.pad.textChanged.connect(_pad_changed)

        # ---- bottom controls
        bar = QHBoxLayout()
        self.live_cam_view = QLabel("Camera off")
        self.live_cam_view.setFixedSize(128, 96)
        self.live_cam_view.setScaledContents(True)
        self.live_cam_view.setAlignment(Qt.AlignCenter)
        self.live_cam_view.setStyleSheet("background:#1d2027; border:1px solid #2c313b; border-radius:6px; "
                                         "color:#6b7080; font-size:10px")
        bar.addWidget(self.live_cam_view)
        col = QVBoxLayout()
        r1 = QHBoxLayout()
        self.mic_btn = QPushButton("🎙  Start speaking", objectName="mic")
        self.mic_btn.clicked.connect(self.toggle_mic)
        self.submit_btn = QPushButton("Submit answer  (Ctrl+Enter)", objectName="primary")
        self.submit_btn.clicked.connect(self.submit_answer)
        r1.addWidget(self.mic_btn, 2)
        r1.addWidget(self.submit_btn, 1)
        col.addLayout(r1)
        r2 = QHBoxLayout()
        self.hint_btn = QPushButton("Hint")
        self.hint_btn.clicked.connect(self.ask_hint)
        self.repeat_btn = QPushButton("Repeat question")
        self.repeat_btn.clicked.connect(self.repeat_question)
        self.screen_btn = QPushButton("Review my screen")
        self.screen_btn.clicked.connect(lambda: self.review_screen(False))
        self.region_btn = QPushButton("Review region…")
        self.region_btn.clicked.connect(lambda: self.review_screen(True))
        self.skip_btn = QPushButton("Skip")
        self.skip_btn.clicked.connect(self.skip_question)
        self.fb_toggle = QPushButton("📊 Feedback")
        self.fb_toggle.setCheckable(True)
        self.fb_toggle.setToolTip("Peek at feedback on your previous answers (hidden by default to keep focus)")
        self.fb_toggle.toggled.connect(self._toggle_live_fb)
        self.end_btn = QPushButton("End && report")  # kept for shortcuts/state; End lives in the top bar
        self.end_btn.clicked.connect(self._confirm_end)
        self.end_btn.hide()
        for btn in (self.hint_btn, self.repeat_btn, self.screen_btn, self.region_btn, self.skip_btn, self.fb_toggle):
            r2.addWidget(btn)
        col.addLayout(r2)
        bar.addLayout(col, 1)
        v.addLayout(bar)
        return w

    def _toggle_live_fb(self, on: bool):
        self.live_fb_view.setVisible(on)
        sizes = self._live_main.sizes()
        total = sum(sizes)
        self._live_main.setSizes([int(total * 0.3), int(total * 0.45), int(total * 0.25)] if on
                                 else [int(total * 0.4), int(total * 0.6), 0])

    def _focus_pad(self, coding: bool):
        total = sum(self.write_split.sizes()) or 600
        self.write_split.setSizes([int(total * 0.25), int(total * 0.75)] if coding else [int(total * 0.6),
                                                                                         int(total * 0.4)])
        (self.pad if coding else self.answer).setFocus()

    def _build_side(self) -> QWidget:
        self.tabs = QTabWidget()
        self.fb_view = QTextBrowser(openExternalLinks=True)
        self.report_view = QTextBrowser(openExternalLinks=True)
        hist = QWidget()
        hv = QVBoxLayout(hist)
        self.hist_list = QListWidget()
        self.hist_list.itemClicked.connect(self._open_history)
        self.hist_view = QTextBrowser()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._load_history)
        hv.addWidget(refresh)
        hv.addWidget(self.hist_list, 1)
        hv.addWidget(self.hist_view, 3)
        side = QWidget()
        sv = QVBoxLayout(side); sv.setContentsMargins(0, 0, 0, 0)
        self.cam_view = QLabel("Camera off")
        self.cam_view.setFixedSize(240, 180)
        self.cam_view.setAlignment(Qt.AlignCenter)
        self.cam_view.setStyleSheet("background:#1d2027; border:1px solid #2c313b; border-radius:6px; color:#6b7080")
        self.cam_stats = QLabel("")
        self.cam_stats.setStyleSheet("color:#9aa0ac; font-size:11px")
        ch = QHBoxLayout(); ch.addWidget(self.cam_view); ch.addWidget(self.cam_stats, 1)
        sv.addLayout(ch)
        sv.addWidget(self.tabs, 1)
        self.tabs.addTab(self.fb_view, "Feedback")
        self.tabs.addTab(self.report_view, "Report")
        self.tabs.addTab(hist, "History")
        self._load_history()
        return side

    # ------------------------------------------------------------------ profiles
    def _current_profile(self) -> Profile:
        return Profile(
            name=self.profile_box.currentText() or "Default", role=self.role.currentText(),
            difficulty=self.difficulty.currentData(), tier=self.tier.currentText(),
            company=self.company.text(), round=self.round.currentText(),
            resume=self.resume.toPlainText(), jd=self.jd.toPlainText(), focus=self.focus.text(),
            duration_min=self.duration.currentData(),
        )

    def _load_profile_names(self):
        self.profile_box.clear()
        self.profile_box.addItems(sorted(self.settings.profiles) or ["Default"])
        if self.settings.profiles:
            self._apply_profile(self.profile_box.currentText())

    def _apply_profile(self, name: str):
        p = self.settings.profiles.get(name)
        if not p:
            return
        p = Profile(**{k: v for k, v in p.items() if k in Profile.__dataclass_fields__})
        self.role.setCurrentText(p.role)
        self.difficulty.setCurrentIndex(max(0, self.difficulty.findData(p.difficulty)))
        self.tier.setCurrentText(p.tier); self.company.setText(p.company)
        self.round.setCurrentText(p.round)
        self.duration.setCurrentIndex(max(0, self.duration.findData(p.duration_min)))
        self.focus.setText(p.focus); self.resume.setPlainText(p.resume); self.jd.setPlainText(p.jd)

    def _save_profile(self):
        name, ok = QInputDialog.getText(self, "Save profile", "Profile name (e.g. 'Backend - Java'):",
                                        text=self.profile_box.currentText())
        if not ok or not name.strip():
            return
        p = self._current_profile(); p.name = name.strip()
        self.settings.profiles[p.name] = asdict(p)
        self.settings.save()
        self._load_profile_names()
        self.profile_box.setCurrentText(p.name)

    def _delete_profile(self):
        name = self.profile_box.currentText()
        if name in self.settings.profiles and QMessageBox.question(self, "Delete", f"Delete profile '{name}'?") \
                == QMessageBox.Yes:
            del self.settings.profiles[name]
            self.settings.save()
            self._load_profile_names()

    def _load_file(self, target: QPlainTextEdit):
        path, _ = QFileDialog.getOpenFileName(self, "Open", str(Path.home()),
                                              "Documents (*.pdf *.docx *.txt *.md)")
        if not path:
            return False
        try:
            target.setPlainText(resume_mod.extract_text(path))
            return True
        except Exception as e:  # noqa: BLE001
            self._on_error(f"Could not read file: {e}")
            return False

    # ------------------------------------------------------------------ resume
    def _upload_resume(self):
        if self._load_file(self.resume):
            self._analyse_resume()

    def _analyse_resume(self):
        text = self.resume.toPlainText()
        if not text.strip() or resume_mod.cached(text):
            self._refresh_resume_status()
            return
        self.resume_status.setText("Analysing experience…")
        model = self.model.currentText()

        def work():
            try:
                self.b.resume_done.emit(resume_mod.analyze(text, model))
            except Exception as e:  # noqa: BLE001
                self.b.resume_done.emit({"_error": str(e)})
        run_bg(self.b, work, busy=False)

    def _on_resume_done(self, a: dict):
        if a.get("_error"):
            self.resume_status.setText("Analysis failed (will use raw text)")
            self.b.status.emit("Resume analysis failed: " + a["_error"].splitlines()[0])
            return
        self._refresh_resume_status()
        self._show_resume_analysis()

    def _refresh_resume_status(self):
        text = self.resume.toPlainText()
        a = resume_mod.cached(text) if text.strip() else None
        if a:
            self.resume_status.setText(f"✓ {len(a.get('experiences', []))} roles · {resume_mod.claim_count(a)} claims"
                                       f" · {len(a.get('red_flags', []))} red flags")
        else:
            self.resume_status.setText("not analysed yet" if text.strip() else "")
        self.resume_view_btn.setEnabled(bool(a))

    def _show_resume_analysis(self):
        a = resume_mod.cached(self.resume.toPlainText())
        if a:
            self.tabs.setCurrentWidget(self.fb_view)
            self.fb_view.setMarkdown(resume_mod.markdown(a))

    # ------------------------------------------------------------------ interview flow
    def start_interview(self):
        self.settings.claude_model = self.model.currentText()
        self.settings.voice, spk = self.voice.currentData().split("#")
        self.settings.voice_speaker = int(spk) if spk else None
        self.settings.whisper_model = self.whisper.currentText()
        self.settings.speak_questions = self.speak.isChecked()
        self.settings.use_camera = self.use_cam.isChecked()
        self.settings.hands_free = self.hands_free.isChecked()
        self.settings.headphones = self.headphones.isChecked()
        self._stop_live()
        if self.use_cam.isChecked():
            self.start_camera()
        self.settings.save()

        if self.speaker:
            self.speaker.stop()
        self.session = Session(profile=self._current_profile(), model=self.settings.claude_model)
        self.chat_view.clear(); self.fb_view.clear(); self.report_view.clear(); self.answer.clear()
        self.pad.clear(); self._pad_snapshot = ""; self._time_up = False
        self.agenda_lbl.setText("<i>Planning the agenda…</i>"); self.clock_lbl.setText("")
        self.q_card.setText("<i>Getting ready: loading voice and planning your agenda…</i>")
        self.live_fb_view.clear(); self.fb_toggle.setChecked(False); self.fb_toggle.setText("📊 Feedback")
        self.iv_stack.setCurrentIndex(1)
        self.start_btn.setEnabled(False)
        run_bg(self.b, self._prepare_and_ask)

    def _prepare_and_ask(self):
        self.ensure_models(self.b.status.emit)
        p = self.session.profile
        if p.resume.strip() and not resume_mod.cached(p.resume):
            self.b.status.emit("Analysing your resume's experience section…")
            try:
                self.b.resume_done.emit(resume_mod.analyze(p.resume, self.session.model))
            except Exception as e:  # noqa: BLE001
                self.b.status.emit(f"Resume analysis failed, using raw text: {e}")
        self.b.status.emit(f"Planning a {p.duration_min}-minute agenda…")
        self.session.make_agenda()
        self.session.clock_start = time.time()
        self.b.agenda.emit(self.session.agenda)
        self.b.ready.emit()
        self._ask_next()

    def ensure_models(self, status):
        """Load speech + voice models (call from a background thread)."""
        from .stt import Recorder, Transcriber
        from .tts import Speaker

        s = self.settings
        if self.recorder is None:
            self.recorder = Recorder()
        if self.transcriber is None or getattr(self, "_whisper_name", None) != s.whisper_model:
            status(f"Loading speech model {s.whisper_model} (first run downloads it)…")
            self.transcriber = Transcriber(s.whisper_model)
            self._whisper_name = s.whisper_model
        key = voice_key(s.voice, s.voice_speaker)
        if s.speak_questions and (self.speaker is None or getattr(self, "_voice_key", None) != key):
            status("Loading voice…")
            self.speaker = Speaker(s.voice, s.voice_speaker, s.speech_rate, progress=status)
            self._voice_key = key

    def _ask_next(self):
        self._asking = True
        self.b.status.emit("Arjun is thinking of a question…")
        try:
            turn = self.session.next_question()
        except Exception:
            self._asking = False
            raise
        self._asking = False
        self.b.question.emit(turn)

    def _on_ready(self):
        self._set_interview_enabled(True)
        if self.hands_free.isChecked():
            self._start_live()

    def _on_question(self, turn: Turn):
        tag = {"followup": "Follow-up", "wrap": "Interviewer"}.get(turn.kind, f"Q{self.session.main_questions_asked}")
        self._append_chat(f"Arjun · {tag}" + (f" · {turn.topic}" if turn.topic else ""), turn.question)
        if self.live:
            self.live.new_question(turn.question)
        elif self.speaker and self.speak.isChecked():
            self.speaker.say(turn.question)
        self.answer.clear()
        self._turn_start, self._turn_audio = time.time(), {}
        if turn.segment in CODE_SEGMENTS and turn.kind == "question" and self.pad.toPlainText().strip():
            self.pad.clear()  # new problem: fresh pad (previous code is saved with its answer)
        self._focus_pad(turn.segment in CODE_SEGMENTS)
        seg_name = SEGMENTS.get(turn.segment, "").split(" (")[0]
        meta = " · ".join(x for x in (tag, seg_name, turn.topic) if x)
        hint = ("<br><span style='color:#9aa0ac;font-size:13px'>Write your solution in the pad on the right and talk "
                "through it.</span>" if turn.segment in CODE_SEGMENTS else "")
        self.q_card.setText(f"<span style='color:#7fb2ff;font-size:12px;font-weight:600'>{html.escape(meta)}</span>"
                            f"<br><br>{html.escape(turn.question)}{hint}")
        self._pad_snapshot = self.pad.toPlainText()
        self._draw_agenda()
        if turn.kind == "wrap":
            self.end_interview()
        elif self.live:
            self.b.status.emit("Arjun is listening. Just talk. Say \"I'm done\" or press Ctrl+Enter when you've finished.")
        else:
            self.b.status.emit("Your turn. Ctrl+Space to talk, Ctrl+Enter to submit.")

    def submit_answer(self):
        # Only block while the next question is being prepared; scoring of earlier answers runs in the background.
        if not self.session or not self.session.current or getattr(self, "_asking", False):
            return
        if not self.live and self.recorder and self.recorder.recording:
            self.toggle_mic(then_submit=True)
            return
        turn = self.session.current
        turn.answer = self.answer.toPlainText().strip()
        turn.code = self._pad_for(turn)
        if not turn.answer and not turn.screenshots and not turn.code.strip():
            self.b.status.emit("Say or type an answer first (or press Skip).")
            return
        turn.metrics = soft.delivery(turn.answer, getattr(self, "_turn_audio", {}))
        if self.camera and self.camera.running:
            turn.camera = self.camera.stats(getattr(self, "_turn_start", time.time() - 120))
        if self.live:
            self.live.hold()
            self._append_chat("You · final answer", "(submitted)" if turn.answer else "(answered in the pad)")
        else:
            if self.speaker:
                self.speaker.stop()
            self._append_chat("You", turn.answer or "(answered on screen)")
        self.answer.clear()
        # Evaluate and fetch the next question in parallel to cut waiting time.
        run_bg(self.b, self._evaluate, turn)
        run_bg(self.b, self._ask_next)

    def _evaluate(self, turn: Turn):
        self.session.evaluate(turn)
        self.b.feedback.emit(turn)

    def skip_question(self):
        if not self.session or not self.session.current or getattr(self, "_asking", False):
            return
        if self.live:
            self.live.hold()
        self.session.current.answer = "(skipped)"
        self._append_chat("You", "(skipped)")
        run_bg(self.b, self._ask_next)

    def repeat_question(self):
        if not (self.session and self.session.current and self.speaker):
            return
        self.speaker.stop()
        if self.live:
            self.live.say(self.session.current.question, "repeat")
        else:
            self.speaker.say(self.session.current.question)

    def ask_hint(self):
        if not self.session or not self.session.current:
            return
        turn = self.session.current
        turn.answer = self.answer.toPlainText().strip()
        turn.code = self._pad_for(turn)
        self._stream_start("Hint")
        run_bg(self.b, lambda: self.b.hint_ready.emit(self.session.hint(turn, on_text=self.b.stream.emit)), busy=False)

    def _on_hint(self, text: str):
        if self.live:
            self.live.say(text, "hint")  # spoken, shown in chat, and recorded as a hint used
        else:
            if self.session and self.session.current:
                self.session.current.exchanges.append(["Interviewer", text, "hint"])
            self._append_chat("Arjun · hint", text)
            if self.speaker and self.speak.isChecked():
                self.speaker.say(text)

    def review_screen(self, interactive: bool):
        if not self.session or not self.session.current:
            return
        turn = self.session.current
        turn.answer = self.answer.toPlainText().strip()
        if not interactive:
            self.showMinimized()
        QTimer.singleShot(150 if interactive else 700, lambda: run_bg(self.b, self._capture_review, turn, interactive))

    def _capture_review(self, turn: Turn, interactive: bool):
        self.b.status.emit("Capturing screen…")
        try:
            shot = screen.capture(interactive=interactive)
        finally:
            self.b.restore.emit()
        screen.cleanup()
        self.b.status.emit("Arjun is looking at your screen…")
        self.b.stream.emit("\x00Screen review")
        note = self.session.review_screen(turn, shot, on_text=self.b.stream.emit)
        self.b.chat.emit("Arjun · watching your screen", note)
        if self.speaker and self.speak.isChecked():
            self.speaker.say(note)

    def end_interview(self):
        if not self.session or not self.session.turns:
            return
        self._set_interview_enabled(False)
        self._clock.stop()
        self._stop_live()
        self.iv_stack.setCurrentIndex(0)  # back to the setup screen, where the analysis lives
        self.tabs.setCurrentWidget(self.report_view)
        self.report_view.setMarkdown("_Writing your report…_")

        def work():
            self.b.status.emit("Writing your final report…")
            # Wait for in-flight evaluations / questions (this task counts as one).
            while self._pending > 1:
                time.sleep(0.3)
            for t in self.session.turns:
                if t.answer and t.answer != "(skipped)" and not t.feedback:
                    self.session.evaluate(t)
            buf = []

            def chunk(c):
                buf.append(c)
                self.b.report.emit("".join(buf))
            self.session.final_report(on_text=chunk)
            self.b.report.emit(self.session.report)
            path = self.session.save()
            self.b.status.emit(f"Saved to {path}")
        run_bg(self.b, work)

    # ------------------------------------------------------------------ agenda & clock
    def _pad_for(self, turn: Turn) -> str:
        pad = self.pad.toPlainText()
        return pad if (turn.segment in CODE_SEGMENTS or pad != getattr(self, "_pad_snapshot", "")) else ""

    def _on_agenda(self, agenda):
        self._draw_agenda()
        self._clock.start()
        self._tick()

    def _draw_agenda(self):
        s = self.session
        if not s or not s.agenda:
            return
        cur, _ = s.segment_at()
        parts = []
        for i, seg in enumerate(s.agenda):
            name = seg["title"].split(" (")[0]
            if i < cur:
                parts.append(f'<span style="color:#6b7080">✓ {name} {seg["minutes"]}m</span>')
            elif i == cur:
                parts.append(f'<span style="color:#7fb2ff;font-weight:600">▶ {name} {seg["minutes"]}m</span>')
            else:
                parts.append(f'<span style="color:#9aa0ac">{name} {seg["minutes"]}m</span>')
        self.agenda_lbl.setText("  ·  ".join(parts))

    def _tick(self):
        s = self.session
        if not s or not s.clock_start:
            return
        rem = s.remaining()
        m, sec = divmod(max(0, int(rem)), 60)
        h, m = divmod(m, 60)
        self.clock_lbl.setText(f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}")
        self.clock_lbl.setStyleSheet(f"color:{'#c0392b' if rem <= 120 else '#c98a1b' if rem <= 300 else '#e6e6e6'}")
        if int(s.elapsed()) % 15 == 0:
            self._draw_agenda()
        if rem <= 0 and not self._time_up:
            self._time_up = True
            self._clock.stop()
            if self.recorder and self.recorder.recording:
                self.recorder.stop(); self._set_mic_ui(False); self._level_timer.stop()
            turn = s.current
            if turn and not turn.answer:
                turn.answer = self.answer.toPlainText().strip()
                turn.code = self._pad_for(turn)
                if turn.answer or turn.code.strip():
                    turn.metrics = soft.delivery(turn.answer, getattr(self, "_turn_audio", {}))
            msg = "That's time. Thanks, we'll stop here."
            self._append_chat("Arjun", msg)
            if self.speaker and self.speak.isChecked():
                self.speaker.stop(); self.speaker.say(msg)
            self.end_interview()

    # ------------------------------------------------------------------ mic
    def toggle_mic(self, then_submit: bool = False):
        if self.live:
            self.live.set_paused(not self.live.paused)
            self._set_mic_ui_live()
            return
        if not self.recorder or not self.session:
            return
        if not self.recorder.recording:
            if self.speaker:
                self.speaker.stop()
            self.recorder.start()
            self._level_timer.start()
            self._set_mic_ui(True)
            self.b.status.emit("Listening… press Ctrl+Space (or the button) when done.")
            return
        audio = self.recorder.stop()
        self._level_timer.stop(); self.level_bar.setValue(0)
        if self.camera and self.camera.running and self.session.current:
            shot = self.camera.snapshot()
            if shot:
                self.session.current.camera_shots = (self.session.current.camera_shots + [str(shot)])[-2:]
        self._set_mic_ui(False)
        self.b.status.emit("Transcribing…")

        def work():
            text = self.transcriber.transcribe(audio)
            if text:
                self._turn_audio = soft.merge_audio_stats(getattr(self, "_turn_audio", {}), soft.audio_stats(audio))
            self.b.transcript.emit(text)
            if then_submit:
                self.b.submit_now.emit()
        run_bg(self.b, work, busy=False)

    def _set_mic_ui(self, on: bool):
        self.mic_btn.setText("⏹  Stop (transcribe)" if on else "🎙  Start speaking")
        self.mic_btn.setProperty("rec", "true" if on else "false")
        self.mic_btn.style().unpolish(self.mic_btn); self.mic_btn.style().polish(self.mic_btn)

    def _update_level(self):
        if self.live:
            self.level_bar.setValue(int(self.live.level * 100))
        elif self.recorder:
            self.level_bar.setValue(int(self.recorder.level * 100))

    def _on_transcript(self, text: str):
        if text:
            cur = self.answer.toPlainText().strip()
            self.answer.setPlainText((cur + " " + text).strip())
        self.b.status.emit("Got it. Edit if needed, then Ctrl+Enter to submit." if text else "Didn't catch that.")

    # ------------------------------------------------------------------ rendering
    def _append_chat(self, who: str, text: str):
        color = "#7fb2ff" if who.startswith("Arjun") else "#7ee0a8" if who == "You" else "#f5c26b"
        self.chat_view.append(
            f'<p style="margin:10px 0 2px 0;color:{color};font-weight:600">{html.escape(who)}</p>'
            f'<p style="margin:0 0 8px 0;line-height:140%">{html.escape(text).replace(chr(10), "<br>")}</p>'
        )
        self.chat_view.verticalScrollBar().setValue(self.chat_view.verticalScrollBar().maximum())

    def _stream_start(self, title: str):
        self._stream_buf = f"### {title}\n\n"
        self.tabs.setCurrentWidget(self.fb_view)
        self.fb_view.setMarkdown(self._stream_buf)

    def _on_stream(self, chunk: str):
        if chunk.startswith("\x00"):
            self._stream_start(chunk[1:])
            return
        self._stream_buf = getattr(self, "_stream_buf", "") + chunk
        self.fb_view.setMarkdown(self._stream_buf)

    def _on_feedback(self, turn: Turn):
        fb = turn.feedback
        if not self.live_fb.isChecked() or not fb:
            return
        md = [f"### {fb.get('score', '?')}/10 · {fb.get('verdict', '')}", f"*{turn.question}*", ""]
        if fb.get("authenticity"):
            md += [f"**🔍 Resume claim check:** {fb['authenticity']}", ""]
        if fb.get("trap_result"):
            md += [f"**🪤 Trap:** {fb['trap_result']}", ""]
        if fb.get("strengths"):
            md += ["**Strengths**"] + [f"- {s}" for s in fb["strengths"]] + [""]
        if fb.get("gaps"):
            md += ["**Missed / wrong**"] + [f"- {s}" for s in fb["gaps"]] + [""]
        md += ["**Model answer**", "", fb.get("model_answer", ""), ""]
        if fb.get("tip"):
            md += [f"**Delivery tip:** {fb['tip']}", ""]
        md += soft_markdown(fb, turn.metrics, turn.camera)
        self.tabs.setCurrentWidget(self.fb_view)
        self.fb_view.setMarkdown("\n".join(md))
        self.live_fb_view.setMarkdown("\n".join(md))
        self.fb_toggle.setText(f"📊 Feedback · last {fb.get('score', '?')}/10")

    def _on_report(self, text: str):
        self.report_view.setMarkdown(text)
        if self.session and self.session.report and not self.builder.loop:
            self.stop_camera()
        self._load_history()
        self.start_btn.setEnabled(True)

    def _on_error(self, msg: str):
        self._asking = False
        if self.session and not self.session.turns:
            self._stop_live()
            self._clock.stop()
            self.iv_stack.setCurrentIndex(0)
        self.statusBar().showMessage("Error: " + msg.splitlines()[0])
        QMessageBox.warning(self, "AlongSide", msg)
        self.start_btn.setEnabled(True)
        if self.session and self.session.turns:
            self._set_interview_enabled(True)

    def _on_busy(self, on: bool):
        self._pending = max(0, self._pending + (1 if on else -1))
        ready = not getattr(self, "_asking", False) and self.session is not None and not self.session.report
        self.submit_btn.setEnabled(ready)
        self.skip_btn.setEnabled(ready)

    def _set_interview_enabled(self, on: bool):
        for btn in (self.mic_btn, self.submit_btn, self.hint_btn, self.repeat_btn, self.screen_btn,
                    self.region_btn, self.skip_btn, self.end_btn, self.end_top_btn):
            btn.setEnabled(on)

    # ------------------------------------------------------------------ hands-free live conversation
    def _start_live(self):
        from .live import LiveConversation
        self._stop_live()
        self.live = LiveConversation(
            self, react_fn=self._live_react, get_code=lambda: self._pad_cache,
            is_code_question=lambda: bool(self.session and self.session.current
                                          and self.session.current.segment in CODE_SEGMENTS),
            patience=2.0, headphones=self.headphones.isChecked())
        self.live.user_text.connect(self._live_user_text)
        self.live.interviewer.connect(self._live_interviewer)
        self.live.next_requested.connect(lambda _reason: self.submit_answer())
        self.live.state.connect(self._live_state)
        self.live.start()
        self._level_timer.start()
        self._set_mic_ui_live()

    def _stop_live(self):
        live = getattr(self, "live", None)
        if live:
            live.stop()
        self.live = None
        self.live_state.setText("")
        if hasattr(self, "_level_timer"):
            self._level_timer.stop()

    def _live_react(self, event: str) -> dict:
        # Runs on a worker thread: only plain data here, no widget access.
        turn = self.session.current if self.session else None
        if not turn or turn.kind == "wrap":
            return {"action": "listen"}
        turn.answer = self._answer_cache
        turn.code = self._pad_cache if (turn.segment in CODE_SEGMENTS or self._pad_cache != self._pad_snapshot) else ""
        return self.session.react(turn, event)

    def _live_user_text(self, text: str, stats):
        turn = self.session.current if self.session else None
        if not turn:
            return
        cur = self.answer.toPlainText().strip()
        self.answer.setPlainText((cur + " " + text).strip())
        turn.exchanges.append(["Candidate", text, "speech"])
        self._turn_audio = soft.merge_audio_stats(getattr(self, "_turn_audio", {}), stats or {})
        self._append_chat("You", text)
        if self.camera and self.camera.running and len(turn.camera_shots) < 2:
            shot = self.camera.snapshot()
            if shot:
                turn.camera_shots.append(str(shot))

    def _live_interviewer(self, text: str, kind: str):
        turn = self.session.current if self.session else None
        if turn:
            turn.exchanges.append(["Interviewer", text, kind])
        label = {"hint": "Arjun · hint", "ack": "Arjun", "nudge": "Arjun · nudge", "time": "Arjun · time",
                 "pushback": "Arjun", "clarify": "Arjun · clarifies"}.get(kind, "Arjun")
        if kind == "ack":
            self.live_state.setText(f"Arjun: {text}")
            return
        self._append_chat(label, text)

    def _live_state(self, state: str):
        txt = {"listening": ("●  Listening", "#1f9d63"), "you": ("●  You're speaking…", "#7ee0a8"),
               "thinking": ("●  Arjun is thinking…", "#c98a1b"), "speaking": ("●  Arjun is speaking…", "#7fb2ff"),
               "paused": ("●  Mic muted", "#c0392b"), "hold": ("●  Noting your answer…", "#c98a1b")}.get(state)
        if txt:
            self.live_state.setText(txt[0])
            self.live_state.setStyleSheet(f"color:{txt[1]}; font-weight:600")

    def _set_mic_ui_live(self):
        muted = bool(self.live and self.live.paused)
        self.mic_btn.setText("🔇  Muted (click to unmute)" if muted else "🎙  Mic live (click to mute)")
        self.mic_btn.setProperty("rec", "true" if muted else "false")
        self.mic_btn.style().unpolish(self.mic_btn); self.mic_btn.style().polish(self.mic_btn)

    def _confirm_end(self):
        if not self.session or not self.session.turns:
            return
        if QMessageBox.question(self, "End interview", "End the interview now and get your scored report?") \
                == QMessageBox.Yes:
            turn = self.session.current
            if turn and not turn.answer and turn.kind != "wrap":
                turn.answer = self.answer.toPlainText().strip()
                turn.code = self._pad_for(turn)
                if turn.answer or turn.code.strip():
                    turn.metrics = soft.delivery(turn.answer, getattr(self, "_turn_audio", {}))
            if self.speaker:
                self.speaker.stop()
            self.end_interview()

    # ------------------------------------------------------------------ dashboard actions
    def generate_plan(self, role: str, difficulty: str, tier: str):
        f = progress.Filter(role=role, difficulty=difficulty)
        areas = progress.by_area(f)
        if not areas:
            QMessageBox.information(self, "AlongSide", "Complete at least one scored interview first.")
            return
        gaps = {a["area"]: progress.recent_gaps(f, a["area"]) for a in areas[:6]}
        self.dashboard.show_plan("_Claude is writing your plan…_")
        model = self.model.currentText()

        def work():
            buf = []

            def chunk(c):
                buf.append(c)
                self.b.plan.emit("".join(buf))
            text = improvement_plan(role, areas, gaps, difficulty, tier, model, on_text=chunk,
                                    soft=progress.soft_summary(f), soft_lacking=progress.soft_lacking(f))
            progress.save_plan(role, text)
            self.b.plan.emit(text)
        run_bg(self.b, work, busy=False)

    def practice_area(self, role: str, difficulty: str, tier: str, area: str):
        if role:
            self.role.setCurrentText(role)
        if difficulty:
            self.difficulty.setCurrentIndex(max(0, self.difficulty.findData(difficulty)))
        self.tier.setCurrentText(tier)
        self.focus.setText(area)
        self.round.setCurrentText("Concepts deep-dive")
        self.main_tabs.setCurrentIndex(0)
        self.statusBar().showMessage(f"Set up a {area} drill. Press Start interview when ready.")

    # ------------------------------------------------------------------ history
    def _load_history(self):
        self.hist_list.clear()
        for p in sorted(SESSIONS_DIR.glob("*.md"), reverse=True):
            self.hist_list.addItem(p.stem)

    def _open_history(self, item):
        self.hist_view.setMarkdown((SESSIONS_DIR / f"{item.text()}.md").read_text())

    # ------------------------------------------------------------------ camera
    def start_camera(self):
        if self.camera is None:
            self.camera = soft.CameraTracker()
        self.camera.start()
        self._cam_timer.start()

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
        self._cam_timer.stop()
        for lbl in (self.cam_view, self.builder.cam_view, self.live_cam_view):
            lbl.clear(); lbl.setText("Camera off")
        self.cam_stats.setText("")

    def _camera_toggled(self, on: bool):
        self.settings.use_camera = on
        self.settings.save()
        if on and (self.session or self.builder.loop):
            self.start_camera()
        elif not on:
            self.stop_camera()

    def _update_camera(self):
        cam = self.camera
        if not cam:
            return
        if cam.error:
            self.cam_view.setText("Camera error")
            self.cam_stats.setText(cam.error)
            self._cam_timer.stop()
            return
        data = cam.preview_rgb()
        if not data:
            return
        buf, w, h = data
        pix = QPixmap.fromImage(QImage(buf, w, h, 3 * w, QImage.Format_RGB888).copy())
        for lbl in (self.cam_view, self.builder.cam_view, self.live_cam_view):
            if lbl.isVisible():
                lbl.setPixmap(pix)
        st = cam.stats(time.time() - 60)
        if st:
            txt = (f"Last minute\nIn frame: {st['presence']}%\nEye contact: {st['eye_contact']}%\n"
                   f"Fidget: {st['fidget']}")
            self.cam_stats.setText(txt)
            self.builder.cam_stats.setText(txt.replace("\n", "  ·  ").replace("Last minute  ·  ", ""))

    def closeEvent(self, e):
        self.stop_camera()
        self.builder.shutdown()
        if self.speaker:
            self.speaker.stop()
        if self.recorder and self.recorder.recording:
            self.recorder.stop()
        if self.session and self.session.turns and not self.session.report:
            self.session.save()
        super().closeEvent(e)


def soft_markdown(fb: dict, metrics: dict, camera: dict) -> list[str]:
    """Markdown block for the 'Communication & confidence' part of feedback."""
    sk = fb.get("soft_skills") or {}
    dims = [(k, sk.get(k)) for k in soft.SOFT_SKILLS if isinstance(sk.get(k), (int, float))]
    md = ["---", "### Communication & confidence"]
    if dims:
        md += [" · ".join(f"**{k}** {v}/10" for k, v in dims), ""]
    line = []
    if metrics.get("spoken"):
        line += [f"{metrics.get('wpm')} wpm", f"{metrics.get('fillers')} fillers",
                 f"{metrics.get('hedges')} hedges", f"longest pause {metrics.get('longest_pause')}s"]
    if camera:
        line += [f"eye contact {camera.get('eye_contact')}%", f"in frame {camera.get('presence')}%"]
    if line:
        md += ["_" + " · ".join(line) + "_", ""]
    lacking = list(sk.get("lacking", [])) + list(fb.get("delivery_flags", []))
    if lacking:
        md += ["**Lacking**"] + [f"- {x}" for x in lacking] + [""]
    if sk.get("good"):
        md += ["**Good**"] + [f"- {x}" for x in sk["good"]]
    return md if len(md) > 2 else []


def _install_crash_logging():
    """Never die silently: log uncaught errors and hard crashes to a file and the terminal."""
    import faulthandler
    import logging
    from .config import DATA_DIR
    log_path = DATA_DIR / "alongside.log"
    logging.basicConfig(filename=log_path, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    crash_file = open(DATA_DIR / "crash.log", "a")  # noqa: SIM115 (kept open for faulthandler)
    faulthandler.enable(file=crash_file, all_threads=True)
    faulthandler.enable(file=sys.stderr, all_threads=True)
    logging.info("AlongSide starting")

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.error("Uncaught exception:\n%s", text)
        print(text, file=sys.stderr)
        app = QApplication.instance()
        if app:
            QMessageBox.critical(None, "AlongSide error", f"{exc_type.__name__}: {exc}\n\nDetails: {log_path}")
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def main():
    _install_crash_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("AlongSide")
    app.setDesktopFileName("alongside")
    from PySide6.QtGui import QIcon
    from .config import ROOT
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        icon.addFile(str(ROOT / "assets" / f"alongside-{size}.png"))
    app.setWindowIcon(QIcon.fromTheme("alongside", icon))
    font = app.font()
    font.setPointSize(10)
    app.setFont(font)
    app.setStyleSheet(STYLE)
    w = MainWindow()
    w.showMaximized()
    code = app.exec()
    import logging
    logging.info("AlongSide exited with code %s", code)
    sys.exit(code)
