"""Interview Gym desktop UI (PySide6)."""
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
    QSpinBox, QDoubleSpinBox, QSplitter, QTabWidget, QTextBrowser, QVBoxLayout, QWidget, QScrollArea, QFrame, QStackedWidget,
)

from . import screen
from .config import ROOT, SESSIONS_DIR, Settings
from .dashboard import Dashboard
from .interview import (CODE_SEGMENTS, DIFFICULTIES, DURATIONS, ROLES, ROUNDS, SEGMENTS, Profile, Session, Turn,
                        improvement_plan)
from . import resume as resume_mod
from .knowledge import DIFFICULTIES as DIFF_DESC, TIER_NAMES
from . import progress
from . import soft
from PySide6.QtGui import QImage, QPixmap
from .tts import VOICES, voice_key
from .richview import RichView
from .responsive import make_responsive, reflow

STYLE = """
/* ---- Interview Gym theme: deep slate, violet → cyan accent, soft cards ---- */
QMainWindow, QWidget#root { background: #0d0f16; color: #e9ecf5; }
QWidget { selection-background-color: #5b3fd1; selection-color: #ffffff; }
QLabel, QCheckBox, QRadioButton { color: #c3c8da; background: transparent; }
QLabel#paneTitle { color: #e9ecf5; font-weight: 600; }
QLabel#heard { background: #12202a; color: #8fe9dc; border: 1px solid #1d3b44; border-radius: 10px; padding: 6px 10px; }
QLabel#brand { padding: 0 18px 0 14px; }
QWidget#card, QFrame#card { background: #131723; border: 1px solid #222840; border-radius: 14px; }
QToolTip { background: #1e2333; color: #e9ecf5; border: 1px solid #3b3f6e; border-radius: 6px; padding: 6px 8px; }

/* inputs */
QTextBrowser, QPlainTextEdit, QTextEdit, QLineEdit, QComboBox, QSpinBox, QDoubleSpinBox, QListWidget, QTreeWidget {
  background: #161a26; color: #e9ecf5; border: 1px solid #252b3d; border-radius: 10px; padding: 7px; }
QPlainTextEdit#codeEditor { background: #12141b; border-radius: 10px; padding: 4px; }
QLineEdit:focus, QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus, QPlainTextEdit:focus, QTextEdit:focus {
  border: 1px solid #8b5cf6; }
QLineEdit:hover, QComboBox:hover, QSpinBox:hover, QDoubleSpinBox:hover { border-color: #3b4466; }
QComboBox { padding-right: 24px; }
QComboBox::drop-down { border: none; width: 22px; }
QComboBox::down-arrow { image: url(__ASSETS__/chevron.svg); width: 12px; height: 12px; margin-right: 8px; }
QComboBox QAbstractItemView { background: #161a26; color: #e9ecf5; border: 1px solid #333b55; border-radius: 8px;
  padding: 4px; selection-background-color: #2b2257; outline: 0; }
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button { width: 0; border: none; }
QListWidget::item { padding: 8px 10px; border-radius: 8px; margin: 1px 2px; }
QListWidget::item:hover { background: #1c2133; }
QListWidget::item:selected { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2d2160, stop:1 #143845);
  color: #ffffff; }
QCheckBox::indicator { width: 16px; height: 16px; border-radius: 5px; border: 1px solid #3b4466; background: #161a26; }
QCheckBox::indicator:hover { border-color: #8b5cf6; }
QCheckBox::indicator:checked { background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 #8b5cf6, stop:1 #06b6d4);
  border-color: #8b5cf6; }

/* buttons */
QPushButton { background: #1e2333; color: #e9ecf5; border: 1px solid #2f3650; border-radius: 10px; padding: 8px 14px; }
QPushButton:hover { background: #262c42; border-color: #4a4f86; }
QPushButton:pressed { background: #1a1e2d; }
QPushButton:checked { background: #2b2257; border-color: #8b5cf6; }
QPushButton:disabled { color: #5d6580; background: #161a26; border-color: #222840; }
QPushButton#primary { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #7c3aed, stop:1 #0891b2);
  border: none; color: #ffffff; font-weight: 700; padding: 9px 16px; }
QPushButton#primary:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #8b5cf6, stop:1 #06b6d4); }
QPushButton#primary:disabled, QPushButton#mic:disabled { background: #1e2333; color: #5d6580; border: 1px solid #2f3650; }
QPushButton#mic { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #059669, stop:1 #0d9488);
  border: none; color: #ffffff; font-weight: 700; min-height: 34px; }
QPushButton#mic:hover { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #14b8a6); }
QPushButton#mic[rec="true"] { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e11d48, stop:1 #db2777); }
QPushButton#danger { background: #3a1422; color: #fda4af; border: 1px solid #7f1d3a; font-weight: 700; }
QPushButton#danger:hover { background: #be123c; color: #ffffff; }
QPushButton#danger:disabled { background: #161a26; color: #5d6580; border-color: #222840; }

/* tables */
QTableWidget, QTableView { background: #131723; color: #e9ecf5; gridline-color: #1e2333; border: 1px solid #222840;
  border-radius: 10px; }
QTableWidget::item:selected { background: #2b2257; }
QHeaderView::section { background: #131723; color: #8b93ab; border: none; border-bottom: 1px solid #222840;
  padding: 6px; font-weight: 600; }
QTableCornerButton::section { background: #131723; border: none; }

/* scrolling, splitters */
QScrollArea, QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #2a3148; border-radius: 4px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: #4a4f86; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #2a3148; border-radius: 4px; min-width: 30px; }
QScrollBar::handle:horizontal:hover { background: #4a4f86; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal { width: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }
QSplitter::handle { background: transparent; }
QSplitter::handle:hover { background: #2b2257; }
QSplitter::handle:horizontal { width: 8px; }
QSplitter::handle:vertical { height: 8px; }

/* tabs: inner tabs as underlined text, main navigation as pills */
QTabWidget::pane { border: 1px solid #222840; border-radius: 12px; top: -1px; background: #0f121b; }
QTabBar::tab { background: transparent; color: #8b93ab; padding: 8px 14px; border: none;
  border-bottom: 2px solid transparent; }
QTabBar::tab:hover { color: #e9ecf5; }
QTabBar::tab:selected { color: #ffffff; border-bottom: 2px solid #8b5cf6; }
QTabWidget#mainTabs::pane { border: none; background: #0d0f16; }
QTabWidget#mainTabs > QTabBar { background: #0a0c12; qproperty-drawBase: 0; border: none; }
QTabWidget#mainTabs QLabel#brand { background: #0a0c12; }
QTabWidget#mainTabs > QTabBar::tab { color: #8b93ab; padding: 9px 18px; margin: 8px 4px; border-radius: 18px;
  border: 1px solid transparent; font-weight: 600; }
QTabWidget#mainTabs > QTabBar::tab:hover { background: #161a26; color: #e9ecf5; }
QTabWidget#mainTabs > QTabBar::tab:selected { color: #ffffff; border: 1px solid #4c3a9e;
  background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #2d2160, stop:1 #12394a); }

/* progress, status bar, menus */
QProgressBar { background: #161a26; border: none; border-radius: 4px; height: 8px; }
QProgressBar::chunk { border-radius: 4px; background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #10b981, stop:1 #22d3ee); }
QStatusBar { background: #0a0c12; color: #8b93ab; border-top: 1px solid #161a26; }
QStatusBar::item { border: none; }
QMenu { background: #161a26; color: #e9ecf5; border: 1px solid #333b55; border-radius: 8px; padding: 4px; }
QMenu::item { padding: 6px 14px; border-radius: 6px; }
QMenu::item:selected { background: #2b2257; }
QMessageBox, QDialog { background: #131723; }
QFormLayout QLabel { color: #8b93ab; }
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
    saved = Signal(str)
    hint_ready = Signal(str)
    agenda = Signal(object)
    resume_done = Signal(object)
    screen_note = Signal(str)
    restore_mic_test = Signal()
    restore_voice_preview = Signal()


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
        self.setWindowTitle("Interview Gym")
        self.resize(1320, 840)
        self.settings = Settings.load()
        self.b = Bridge()
        self.session: Session | None = None
        self.speaker = None
        self.transcriber = None
        self.recorder = None
        self._pending = 0

        self.main_tabs = QTabWidget(objectName="mainTabs")
        self.main_tabs.setDocumentMode(True)
        brand = QLabel("<span style='font-size:17px;font-weight:800;color:#a78bfa'>Interview</span>"
                       "<span style='font-size:17px;font-weight:800;color:#22d3ee'>&nbsp;Gym</span>"
                       "<span style='color:#5d6580'>&nbsp;&nbsp;·&nbsp;&nbsp;train like it's real</span>",
                       objectName="brand")
        brand.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
        brand.setMinimumHeight(54)
        self.main_tabs.setCornerWidget(brand, Qt.TopLeftCorner)
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
        self.main_tabs.addTab(root, "🎯  Interview")
        from .reports import PastInterviews
        self.interviews = PastInterviews()
        self.interviews.setObjectName("root")
        self.main_tabs.addTab(self.interviews, "🗂  Past Interviews")
        self.interviews.changed.connect(lambda: self.dashboard.refresh())
        iv = self.interviews
        iv.focus_requested.connect(lambda: self.toggle_focus(
            iv.full_btn, [iv.left_panel, iv.title, iv.overview, iv.open_btn, iv.del_btn]))
        self.interviews.model_getter = lambda: self.model.currentText()
        from .builder import RoundBuilder
        self.builder = RoundBuilder(self)
        self.builder.setObjectName("root")
        self.main_tabs.addTab(self.builder, "🏢  Round Builder")
        self.dashboard = Dashboard()
        self.dashboard.setObjectName("root")
        self.main_tabs.addTab(self.dashboard, "📈  Dashboard")
        self.main_tabs.currentChanged.connect(lambda i: self.main_tabs.widget(i) is self.dashboard and self.dashboard.refresh())
        self.dashboard.plan_requested.connect(self.generate_plan)
        self.dashboard.practice_requested.connect(self.practice_area)
        setup_scroll = QScrollArea(widgetResizable=True)
        setup_scroll.setFrameShape(QFrame.NoFrame)
        setup_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        setup_w = self._build_setup()
        make_responsive(setup_w)
        setup_scroll.setWidget(setup_w)
        setup_scroll.setMinimumWidth(295)  # narrower than this, the setup column folds away (▸ Setup brings it back)
        left = QWidget()
        lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0)
        lv.addWidget(setup_scroll, 1)
        lv.addWidget(self.start_btn)  # pinned so it's always visible
        split.addWidget(left)
        split.addWidget(self._build_side())
        split.setSizes([460, 900])
        split.setChildrenCollapsible(False)
        split.setCollapsible(0, True)   # past its minimum width the setup column hides instead of clipping
        split.setCollapsible(1, False)
        self.setup_split = split
        split.splitterMoved.connect(lambda *_: self._sync_setup_toggle())
        self.iv_stack.addWidget(self._build_interview())  # page 1: live interview

        self.level_bar = QProgressBar(maximum=100, textVisible=False)
        self.level_bar.setFixedWidth(140)
        self.statusBar().addPermanentWidget(QLabel("Mic"))
        self.statusBar().addPermanentWidget(self.level_bar)
        self.statusBar().setStyleSheet("color:#8b93ab")
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
        b.saved.connect(self._on_saved)
        b.hint_ready.connect(self._on_hint)
        b.resume_done.connect(self._on_resume_done)
        b.screen_note.connect(self._on_screen_note)
        b.restore_mic_test.connect(lambda: self.mic_test.setEnabled(True))
        b.restore_voice_preview.connect(lambda: self.voice_preview.setEnabled(True))
        self._clock = QTimer(self, interval=1000, timeout=self._tick)

        QShortcut(QKeySequence("Ctrl+Space"), self, activated=self.toggle_mic)
        QShortcut(QKeySequence("Esc"), self, activated=self.exit_focus)
        QShortcut(QKeySequence("F11"), self, activated=self._focus_current)
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
        title = QLabel("<span style='font-size:22px;font-weight:800;color:#e9ecf5'>New interview</span><br>"
                       "<span style='color:#8b93ab'>Set it up, then Arjun takes it from here.</span>")
        v.addWidget(title)
        v.addSpacing(4)

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
        clear = QPushButton("🧹 Clear")
        clear.setToolTip("Clear the setup form, and optionally delete saved resume data")
        clear.clicked.connect(self.clear_setup)
        prow.addWidget(clear)
        v.addWidget(reflow(prow))

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
        self.resume_status.setStyleSheet("color:#8b93ab; font-size:11px")
        upload = QPushButton("Upload resume…")
        upload.clicked.connect(self._upload_resume)
        self.resume_view_btn = QPushButton("Analysis")
        self.resume_view_btn.setToolTip("Show the claims Arjun will verify")
        self.resume_view_btn.clicked.connect(self._show_resume_analysis)
        rrow.addWidget(self.resume_status, 1); rrow.addWidget(upload); rrow.addWidget(self.resume_view_btn)
        v.addWidget(reflow(rrow))
        self.resume = QPlainTextEdit(placeholderText="Upload your resume (.pdf / .docx / .txt / .md) or paste it. "
                                                     "Arjun will always grill your experience section.")
        self.resume.textChanged.connect(self._refresh_resume_status)
        v.addWidget(self.resume, 2)

        jrow = QHBoxLayout()
        jrow.addWidget(QLabel("Job description (optional)"))
        loadj = QPushButton("Load file…")
        loadj.clicked.connect(lambda: self._load_file(self.jd))
        jrow.addStretch(); jrow.addWidget(loadj)
        v.addWidget(reflow(jrow))
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
        self.whisper = QComboBox(); self.whisper.addItems(["parakeet", "small.en", "base.en", "tiny.en"])
        self.whisper.setToolTip("Speech to text. parakeet: most accurate and ~8x faster on this laptop (recommended). "
                                "small.en / base.en / tiny.en: Whisper models (slower or less accurate).")
        self.whisper.setCurrentText(self.settings.whisper_model)
        self.speak = QCheckBox("Speak questions aloud", checked=self.settings.speak_questions)
        self.live_fb = QCheckBox("Show feedback after each answer", checked=True)
        self.use_cam = QCheckBox("Camera (confidence && presence)", checked=self.settings.use_camera)
        self.use_cam.setToolTip("Webcam is analysed locally (eye contact, posture, fidgeting). Occasional snapshots "
                                "go to Claude for feedback on expression and posture.")
        self.use_cam.toggled.connect(self._camera_toggled)
        f2.addRow("Claude model", self.model)
        voice_row = QHBoxLayout()
        self.voice_preview = QPushButton("▶ Preview")
        self.voice_preview.setToolTip("Hear this voice. 'Natural' voices sound like a real person; "
                                      "'Classic' ones are faster but robotic.")
        self.voice_preview.clicked.connect(self._preview_voice)
        voice_row.addWidget(self.voice, 1); voice_row.addWidget(self.voice_preview)
        f2.addRow("Voice", reflow(voice_row))
        self.voice_speed = QComboBox()
        for x in (1.0, 1.1, 1.25, 1.4, 1.55):
            self.voice_speed.addItem({1.0: "Slow", 1.1: "Relaxed", 1.25: "Normal", 1.4: "Brisk", 1.55: "Fast"}[x], x)
        self.voice_speed.setCurrentIndex(max(0, self.voice_speed.findData(self.settings.speech_rate)))
        self.voice_speed.setToolTip("How fast Arjun talks. Press ▶ Preview to hear it.")
        self.voice_speed.currentIndexChanged.connect(
            lambda _: setattr(self.settings, "speech_rate", self.voice_speed.currentData()))
        f2.addRow("Voice speed", self.voice_speed)
        f2.addRow("Speech model", self.whisper)
        mic_row = QHBoxLayout()
        self.mic_box = QComboBox()
        self.mic_box.setToolTip("Which microphone Arjun listens to. Auto uses your default mic, but skips it if it "
                                "sends silence (e.g. Bluetooth earbuds in music mode have no working mic).")
        self.mic_test = QPushButton("Test")
        self.mic_test.setToolTip("Check that this microphone actually hears you")
        self.mic_test.clicked.connect(self._test_mic)
        mic_row.addWidget(self.mic_box, 1); mic_row.addWidget(self.mic_test)
        f2.addRow("Microphone", reflow(mic_row))
        self._fill_mics()
        self.pause_box = QDoubleSpinBox(minimum=1.0, maximum=6.0, singleStep=0.5, suffix=" s",
                                        value=self.settings.answer_pause)
        self.pause_box.setToolTip("How long you must stay quiet before Arjun treats your answer as finished, "
                                  "then thinks and replies. Short pauses while you think don't end your turn.")
        f2.addRow("Wait after I stop", self.pause_box)
        v.addLayout(f2)
        v.addWidget(self.speak)
        v.addWidget(self.live_fb)
        v.addWidget(self.use_cam)
        self.hands_free = QCheckBox("Hands-free conversation", checked=self.settings.hands_free)
        self.hands_free.setToolTip("Arjun speaks, listens continuously, waits until you finish, reacts, nudges and "
                                   "gives occasional hints. Say \"I'm done\" (or press Ctrl+Enter) to finish an answer.")
        self.headphones = QCheckBox("Headphones / earbuds", checked=self.settings.headphones)
        self.headphones.setToolTip("Tick when you wear headphones or earbuds: the mic stays on while Arjun talks, "
                                   "and he acknowledges you the moment you pause")
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
        self.live_state.setStyleSheet("color:#8b93ab; font-weight:600")
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
        self.q_card.setStyleSheet("background:#161a26; border:1px solid #8b5cf6; border-radius:8px; padding:14px;"
                                  "font-size:16px; color:#e9ecf5")
        q_scroll = QScrollArea(widgetResizable=True)
        q_scroll.setFrameShape(QFrame.NoFrame)
        q_scroll.setWidget(self.q_card)
        self.chat_view = QTextBrowser(openExternalLinks=True)
        left.addWidget(q_scroll); left.addWidget(self.chat_view)
        left.setSizes([260, 420])

        # ---- right: ONE big workspace for notes, code and design (Arjun reads all of it)
        from .editor import Workspace
        right = QWidget(objectName="card")
        rv = QVBoxLayout(right); rv.setContentsMargins(12, 10, 12, 12)
        self.workspace = Workspace("Workspace · Arjun reads everything you write here")
        self.workspace.code_lang = self.settings.code_language
        self.workspace.language_changed.connect(self._on_ws_language)
        self.pad = self.workspace.editor
        self.pad.setPlaceholderText(
            "Just talk. Your spoken answer is captured automatically (see 'Heard' above and the chat).\n\n"
            "Write here whenever it helps:\n"
            "  • code: pick the language above (Java, Python, C++…). Auto-indent and colouring are on\n"
            "  • system design: notes, components, APIs, schema, numbers, plus { } Code block for snippets\n\n"
            "Ctrl+Enter submit · Ctrl+H hint · Ctrl+Space mute · Ctrl+Shift+S review my screen")
        # Spoken transcript buffer (not a separate box any more; shown compactly as 'Heard').
        self.answer = QPlainTextEdit(); self.answer.hide()
        self.heard_lbl = QLabel("")
        self.heard_lbl.setObjectName("heard")
        self.heard_lbl.setWordWrap(True)
        self.heard_lbl.setMaximumHeight(80)  # room for two lines at the larger font
        self.heard_lbl.setToolTip("What Arjun has heard you say on this question (speech-to-text)")
        rv.addWidget(self.heard_lbl)
        rv.addWidget(self.workspace, 1)
        self.live_fb_view = RichView()
        self.live_fb_view.setVisible(False)

        main.addWidget(left); main.addWidget(right); main.addWidget(self.live_fb_view)
        main.setSizes([520, 760, 0])
        self._live_main = main
        v.addWidget(main, 1)

        self._answer_cache = self._pad_cache = self._pad_snapshot = ""
        self.live = None
        def _answer_changed():
            self._answer_cache = self.answer.toPlainText().strip()
            t = self._answer_cache
            self.heard_lbl.setText(("🎙 Heard: " + (t if len(t) <= 160 else "…" + t[-160:])) if t else "")
            self.heard_lbl.setVisible(bool(t))
        self.answer.textChanged.connect(_answer_changed)
        _answer_changed()

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
        self.live_cam_view.setStyleSheet("background:#161a26; border:1px solid #252b3d; border-radius:6px; "
                                         "color:#5d6580; font-size:10px")
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
        self.cam_btn = QPushButton("📷 Camera")
        self.cam_btn.setCheckable(True)
        self.cam_btn.setToolTip("Turn the camera on or off at any time during the interview")
        self.cam_btn.clicked.connect(self.toggle_camera_now)
        for btn in (self.hint_btn, self.repeat_btn, self.screen_btn, self.region_btn, self.skip_btn, self.cam_btn,
                    self.fb_toggle):
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

    def _focus_pad(self, segment: str):
        # Coding / machine coding: colour and indent as code. Theory and system design: notes with code blocks.
        self.workspace.set_language(self.workspace.code_lang if segment in ("coding", "machine_coding") else "Notes")
        self.pad.setFocus()

    def _on_ws_language(self, name: str):
        if name != "Notes" and name != self.settings.code_language:
            self.settings.code_language = name
            self.settings.save()

    WELCOME = ("### Get ready\n\n"
               "1. **Upload resume…** and wait for ✓. Press **Analysis** to see the claims Arjun will verify.\n"
               "2. Pick role, difficulty, company tier, round and **duration**.\n"
               "3. Check the **Microphone** (press Test), sit facing a light, and press **Start interview**.\n\n"
               "> [!TIP] The camera only switches on during the interview, and you can turn it off any time "
               "with **📷 Camera**.\n\n"
               "Feedback, reports and the full history of every completed interview are in **Past Interviews**.")

    def _show_welcome(self):
        self.fb_view.setMarkdown(self.WELCOME, "top")

    def _reset_live_page(self):
        """Interview over: wipe the live screen so nothing from it lingers (it's all saved in Past Interviews)."""
        self.chat_view.clear(); self.answer.clear(); self.pad.clear()
        self.live_fb_view.clear()
        self.q_card.setText("<i>Arjun will ask the first question in a moment…</i>")
        self.agenda_lbl.setText(""); self.clock_lbl.setText(""); self.live_state.setText("")
        self.fb_toggle.setChecked(False); self.fb_toggle.setText("📊 Feedback")

    def clear_setup(self):
        """🧹 Clear on the Interview tab: reset the form, optionally delete saved resume data."""
        box = QMessageBox(self)
        box.setWindowTitle("Clear interview setup")
        box.setText("Clear the setup form: resume, job description, company and focus?\n\n"
                    "'Also delete saved resume data' removes stored resume analyses and the resume / JD saved in "
                    "your profiles. Past interviews and your dashboard are kept.")
        form_btn = box.addButton("Clear form", QMessageBox.AcceptRole)
        all_btn = box.addButton("Also delete saved resume data", QMessageBox.DestructiveRole)
        box.addButton(QMessageBox.Cancel)
        box.exec()
        clicked = box.clickedButton()
        if clicked not in (form_btn, all_btn):
            return
        for w in (self.resume, self.jd):
            w.clear()
        self.company.clear(); self.focus.clear()
        self._refresh_resume_status()
        self.chat_view.clear()
        self._show_welcome()
        if clicked is all_btn:
            from .resume import RESUME_DIR
            n = 0
            for f in RESUME_DIR.glob("*.json"):
                f.unlink(missing_ok=True); n += 1
            for prof in self.settings.profiles.values():
                prof["resume"] = ""; prof["jd"] = ""
            self.settings.save()
            self.statusBar().showMessage(f"Cleared. Deleted {n} saved resume analyses and the resume/JD in profiles.")
        else:
            self.statusBar().showMessage("Setup form cleared.")

    def _build_side(self) -> QWidget:
        self.tabs = QTabWidget()
        self.fb_view = RichView()
        self._show_welcome()
        side = QWidget()
        sv = QVBoxLayout(side); sv.setContentsMargins(0, 0, 0, 0)
        self.cam_view = QLabel("Camera off")
        self.cam_view.setFixedSize(240, 180)
        self.cam_view.setAlignment(Qt.AlignCenter)
        self.cam_view.setStyleSheet("background:#161a26; border:1px solid #252b3d; border-radius:6px; color:#5d6580")
        self.cam_stats = QLabel("")
        self.cam_stats.setStyleSheet("color:#8b93ab; font-size:11px")
        ch = QHBoxLayout(); ch.addWidget(self.cam_view); ch.addWidget(self.cam_stats, 1)
        tools = QVBoxLayout()
        self.setup_toggle = QPushButton("◂ Hide setup")
        self.setup_toggle.setToolTip("Fold the setup column away to give this panel more room (or drag the divider)")
        self.setup_toggle.clicked.connect(self._toggle_setup)
        self.side_full_btn = QPushButton("⛶ Full screen")
        self.side_full_btn.setToolTip("Show this panel on the whole screen (Esc to exit)")
        self.side_full_btn.clicked.connect(lambda: self.toggle_focus(
            self.side_full_btn, [self.setup_split.widget(0), self.cam_view, self.cam_stats, self.setup_toggle]))
        tools.addWidget(self.setup_toggle); tools.addWidget(self.side_full_btn); tools.addStretch()
        ch.addLayout(tools)
        sv.addLayout(ch)
        sv.addWidget(self.tabs, 1)
        self.tabs.addTab(self.fb_view, "Preparation")
        return side

    # ------------------------------------------------------------------ profiles
    def _focus_current(self):
        """F11: full screen for the reading panel of the current tab."""
        if getattr(self, "_focus", None):
            self.exit_focus()
        elif self.main_tabs.currentWidget() is self.interviews:
            self.interviews.full_btn.click()
        elif self.main_tabs.currentIndex() == 0 and self.iv_stack.currentIndex() == 0:
            self.side_full_btn.click()

    def _toggle_setup(self):
        sp = self.setup_split
        sizes = sp.sizes(); total = sum(sizes)
        if sizes[0] > 0:
            self._setup_width = sizes[0]
            sp.setSizes([0, total])
        else:
            w = max(360, getattr(self, "_setup_width", 460))
            sp.setSizes([w, max(300, total - w)])
        self._sync_setup_toggle()

    def _sync_setup_toggle(self):
        shown = self.setup_split.sizes()[0] > 0
        self.setup_toggle.setText("◂ Hide setup" if shown else "▸ Show setup")

    # ------------------------------------------------------------------ full screen focus
    def toggle_focus(self, btn, hide: list):
        """Show one panel on the whole screen: hide the given widgets, the navigation and the status bar."""
        if getattr(self, "_focus", None):
            self.exit_focus()
            return
        hidden = [w for w in hide if w is not None and w.isVisible()]
        for w in hidden:
            w.hide()
        self.main_tabs.tabBar().hide()
        if self.main_tabs.cornerWidget(Qt.TopLeftCorner):
            self.main_tabs.cornerWidget(Qt.TopLeftCorner).hide()
        self.statusBar().hide()
        self._focus = (hidden, btn, self.isMaximized())
        btn.setText("⤡ Exit full screen")
        self.showFullScreen()

    def exit_focus(self):
        f = getattr(self, "_focus", None)
        if not f:
            return
        hidden, btn, was_max = f
        self._focus = None
        for w in hidden:
            w.show()
        self.main_tabs.tabBar().show()
        if self.main_tabs.cornerWidget(Qt.TopLeftCorner):
            self.main_tabs.cornerWidget(Qt.TopLeftCorner).show()
        self.statusBar().show()
        btn.setText("⛶ Full screen")
        self.showMaximized() if was_max else self.showNormal()

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
            self.fb_view.setMarkdown(resume_mod.markdown(a), "top")

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
        self.settings.mic = self.mic_box.currentData() or ""
        self.settings.answer_pause = self.pause_box.value()
        self._stop_live()
        self._iv_running = True
        if self.use_cam.isChecked():
            self.start_camera()
        self.settings.save()

        if self.speaker:
            self.speaker.stop()
        self.session = Session(profile=self._current_profile(), model=self.settings.claude_model)
        self.session.pause_sec = self.pause_box.value()  # tells Claude how long you had paused
        self.chat_view.clear(); self.answer.clear()
        self.pad.clear(); self._pad_snapshot = ""; self._time_up = False
        self.agenda_lbl.setText("<i>Planning the agenda…</i>"); self.clock_lbl.setText("")
        self.q_card.setText("<i>Getting ready: loading voice and planning your agenda…</i>")
        self.live_fb_view.clear(); self.fb_toggle.setChecked(False); self.fb_toggle.setText("📊 Feedback")
        self.iv_stack.setCurrentIndex(1)
        self.start_btn.setEnabled(False)
        run_bg(self.b, self._prepare_and_ask)

    def _prepare_and_ask(self):
        s = self.session  # keep a local handle: the user may end/discard while we're preparing
        self.ensure_models(self.b.status.emit)
        p = s.profile
        if p.resume.strip() and not resume_mod.cached(p.resume):
            self.b.status.emit("Analysing your resume's experience section…")
            try:
                self.b.resume_done.emit(resume_mod.analyze(p.resume, s.model))
            except Exception as e:  # noqa: BLE001
                self.b.status.emit(f"Resume analysis failed, using raw text: {e}")
        if s.aborted:
            return
        self.b.status.emit(f"Planning a {p.duration_min}-minute agenda…")
        s.make_agenda()
        if s.aborted:
            return
        s.clock_start = time.time()
        self.b.agenda.emit(s.agenda)
        self.b.ready.emit()
        self._ask_next()

    def _fill_mics(self):
        from .stt import list_mics
        self.mic_box.clear()
        self.mic_box.addItem("Auto (default, skip silent mics)", "")
        for node, desc in list_mics():
            self.mic_box.addItem(desc + ("  (Bluetooth: music mode has no mic)" if node.startswith("bluez") else ""),
                                 node)
        i = self.mic_box.findData(self.settings.mic)
        self.mic_box.setCurrentIndex(max(0, i))

    PREVIEW_LINE = ("Ok, that's a reasonable start. But you said the cache is always consistent. Are you sure? "
                    "Walk me through what happens when two writes hit the same key.")

    def _preview_voice(self):
        voice, spk = self.voice.currentData().split("#")
        spk = int(spk) if spk else None
        self.voice_preview.setEnabled(False)
        self.b.status.emit("Loading the voice…")

        def work():
            from .tts import Speaker
            try:
                key = (voice_key(voice, spk), self.settings.speech_rate)
                if self.speaker is None or getattr(self, "_voice_key", None) != key:
                    if self.speaker:
                        self.speaker.stop()
                    self.speaker = Speaker(voice, spk, self.settings.speech_rate, progress=self.b.status.emit)
                    self._voice_key = key
                self.speaker.stop()
                self.speaker.say(self.PREVIEW_LINE)
                self.b.status.emit("Playing preview…")
            except Exception as e:  # noqa: BLE001
                self.b.status.emit(f"Voice preview failed: {e}")
            self.b.restore_voice_preview.emit()
        run_bg(self.b, work, busy=False)

    def _test_mic(self):
        node = self.mic_box.currentData() or ""
        self.mic_test.setEnabled(False)
        self.b.status.emit("Testing the microphone: say something for 2 seconds…")

        def work():
            from .stt import SILENT, choose_mic, probe_mic
            try:
                if node:
                    peak = probe_mic(node, 2.5)
                    msg = ("✓ Microphone works." if peak >= 0.03 else
                           "Microphone is on but very quiet. Speak up or raise the input volume." if peak >= SILENT
                           else "✗ This microphone sends silence. Pick another one.")
                else:
                    used, note = choose_mic("")
                    peak = probe_mic(used, 2.5)
                    msg = (note + " " if note else "") + ("✓ Microphone works." if peak >= 0.03 else
                                                          "Microphone is very quiet. Speak up." if peak >= SILENT
                                                          else "✗ No sound from the microphone.")
            except Exception as e:  # noqa: BLE001
                msg = f"Mic test failed: {e}"
            self.b.status.emit(msg)
            self.b.restore_mic_test.emit()
        run_bg(self.b, work, busy=False)

    def ensure_models(self, status):
        """Load speech + voice models and pick a working microphone (call from a background thread)."""
        from .stt import Recorder, Transcriber, choose_mic
        from .tts import Speaker

        s = self.settings
        status("Checking the microphone…")
        node, note = choose_mic(s.mic)
        self.mic_note = note
        if note:
            status("🎙 " + note)
        if self.recorder is None:
            self.recorder = Recorder()
        if self.transcriber is None or getattr(self, "_whisper_name", None) != s.whisper_model:
            status(f"Loading speech model {s.whisper_model} (first run downloads it)…")
            self.transcriber = Transcriber(s.whisper_model)
            self._whisper_name = s.whisper_model
        key = (voice_key(s.voice, s.voice_speaker), s.speech_rate)
        if s.speak_questions and (self.speaker is None or getattr(self, "_voice_key", None) != key):
            status("Loading voice…")
            self.speaker = Speaker(s.voice, s.voice_speaker, s.speech_rate, progress=status)
            self._voice_key = key

    def _ask_next(self):
        s = self.session
        if not s or s.aborted:
            return
        self._asking = True
        self.b.status.emit("Arjun is thinking of a question…")
        try:
            turn = s.next_question()
        except Exception:
            self._asking = False
            if s.aborted:
                return
            raise
        self._asking = False
        if not s.aborted:
            self.b.question.emit(turn)

    def _on_ready(self):
        if not self.session or self.session.aborted:
            return
        self._set_interview_enabled(True)
        if self.hands_free.isChecked():
            self._start_live()

    def _on_question(self, turn: Turn):
        if not self.session or self.session.aborted or turn not in self.session.turns:
            return
        from .live import no_okay
        turn.question = no_okay(turn.question)  # shown and spoken the same way: "Ok"/"Got it", never "Okay"
        tag = {"followup": "Follow-up", "wrap": "Interviewer"}.get(turn.kind, f"Q{self.session.main_questions_asked}")
        seg_name = SEGMENTS.get(turn.segment, "").split(" (")[0]
        meta = " · ".join(x for x in (tag, seg_name, turn.topic) if x)
        meta_html = f"<span style='color:#a78bfa;font-size:12px;font-weight:600'>{html.escape(meta)}</span>"
        hint = ("<br><span style='color:#8b93ab;font-size:13px'>Write your solution in the pad on the right and talk "
                "through it.</span>" if turn.segment in CODE_SEGMENTS else "")

        def reveal():
            # Shown the moment Arjun's voice starts, so text and speech stay in sync.
            if not self.session or self.session.current is not turn:
                return
            self._append_chat(f"Arjun · {tag}" + (f" · {turn.topic}" if turn.topic else ""), turn.question)
            self.q_card.setText(f"{meta_html}<br><br>{html.escape(turn.question)}{hint}")

        if self.live and turn.kind != "wrap":
            self.q_card.setText(f"{meta_html}<br><br><span style='color:#8b93ab'>Arjun is asking…</span>")
            self.live.new_question(turn.question, on_start=reveal, kind=turn.kind,
                                   first=len(self.session.turns) <= 1)
        else:
            reveal()
            if self.speaker and self.speak.isChecked():
                self.speaker.say(turn.question)
        self.answer.clear()
        self._turn_start, self._turn_audio = time.time(), {}
        if turn.kind == "question" and self.pad.toPlainText().strip():
            self.pad.clear()  # new question: fresh workspace (what you wrote is saved with its answer)
        self._focus_pad(turn.segment)
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
        if self.live and self.live.mic_busy and getattr(self, "_submit_wait", 0) < 75:
            # Your last words are still being written down: wait (up to ~15 s) so they're part of the answer.
            self._submit_wait = getattr(self, "_submit_wait", 0) + 1
            self.live_state.setText("●  Finishing writing down your answer…")
            QTimer.singleShot(200, self.submit_answer)
            return
        self._submit_wait = 0
        turn = self.session.current
        turn.answer = _strip_done(self.answer.toPlainText().strip())
        turn.code = self._pad_for(turn)
        if not turn.answer and not turn.screenshots and not turn.code.strip():
            self.b.status.emit("Say or type an answer first (or press Skip).")
            return
        turn.metrics = soft.delivery(turn.answer, getattr(self, "_turn_audio", {}))
        if self.camera and self.camera.running:
            turn.camera = self.camera.stats(getattr(self, "_turn_start", time.time() - 120))
        if self.live:
            self.live.hold()
            self._append_chat("You · final answer", "(submitted)" if turn.answer else "(answered in the workspace)")
        else:
            if self.speaker:
                self.speaker.stop()
            self._append_chat("You · final answer", "(submitted)" if turn.answer else "(answered in the workspace)")
        self.answer.clear()
        # Evaluate and fetch the next question in parallel to cut waiting time.
        run_bg(self.b, self._evaluate, turn)
        run_bg(self.b, self._ask_next)

    def _evaluate(self, turn: Turn):
        session = self.session
        session.evaluate(turn)
        if not session.aborted:
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
        self.b.screen_note.emit(note)

    def interview_active(self) -> bool:
        """An interview or a Round Builder loop is in progress (the only time the camera may run)."""
        lp = self.builder.loop
        return bool(getattr(self, "_iv_running", False) or (lp and not self.builder.loop_finished))

    def abort_interview(self):
        """Ended early: stop everything and throw the interview away (no scoring, saving or analysis)."""
        if not self.session:
            return
        self.session.aborted = True
        self._iv_running = False
        self._set_interview_enabled(False)
        self._clock.stop()
        self._stop_live()
        if self.speaker:
            self.speaker.stop()
        if self.recorder and self.recorder.recording:
            self.recorder.stop(); self._set_mic_ui(False); self._level_timer.stop()
        if not self.builder.loop:
            self.stop_camera()
        self.session = None
        self.iv_stack.setCurrentIndex(0)
        self._reset_live_page()
        self.start_btn.setEnabled(True)
        self.fb_view.setMarkdown("_The last interview was ended early, so it was discarded: no report, history or "
                                 "dashboard data. Only completed interviews (time up, or Arjun wraps up) are analysed._")
        self.tabs.setCurrentWidget(self.fb_view)
        self.statusBar().showMessage("Interview ended early and discarded.")

    def end_interview(self):
        if not self.session or not self.session.turns or self.session.aborted:
            return
        self._set_interview_enabled(False)
        self._clock.stop()
        self._stop_live()
        self._iv_running = False
        if not self.interview_active():
            self.stop_camera()  # interview over: the camera is never left on
        self.iv_stack.setCurrentIndex(0)
        self._reset_live_page()
        p = self.session.profile
        self.main_tabs.setCurrentWidget(self.interviews)  # the report is written straight into Past Interviews
        self.interviews.show_pending(
            f"{time.strftime('%d %b %Y · %H:%M', time.localtime(self.session.started))}  ·  Interview · {p.round}"
            f"  ·  {p.duration_min} min planned")

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
            self.session.save()
            self.b.saved.emit(self.session.id)
        run_bg(self.b, work)

    # ------------------------------------------------------------------ agenda & clock
    def _pad_for(self, turn: Turn) -> str:
        pad = self.pad.toPlainText()
        return pad if (turn.segment in CODE_SEGMENTS or pad != getattr(self, "_pad_snapshot", "")) else ""

    def _on_agenda(self, agenda):
        if not self.session or self.session.aborted:
            return
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
                parts.append(f'<span style="color:#5d6580">✓ {name} {seg["minutes"]}m</span>')
            elif i == cur:
                parts.append(f'<span style="color:#a78bfa;font-weight:600">▶ {name} {seg["minutes"]}m</span>')
            else:
                parts.append(f'<span style="color:#8b93ab">{name} {seg["minutes"]}m</span>')
        self.agenda_lbl.setText("  ·  ".join(parts))

    def _tick(self):
        s = self.session
        if not s or not s.clock_start:
            return
        rem = s.remaining()
        m, sec = divmod(max(0, int(rem)), 60)
        h, m = divmod(m, 60)
        self.clock_lbl.setText(f"{h}:{m:02d}:{sec:02d}" if h else f"{m:02d}:{sec:02d}")
        self.clock_lbl.setStyleSheet(f"color:{'#fb7185' if rem <= 120 else '#fbbf24' if rem <= 300 else '#e9ecf5'}")
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
            self._append_chat("You", text)
        self.b.status.emit("Got it. Edit if needed, then Ctrl+Enter to submit." if text else "Didn't catch that.")

    # ------------------------------------------------------------------ rendering
    def _append_chat(self, who: str, text: str):
        color = "#a78bfa" if who.startswith("Arjun") else "#5eead4" if who == "You" else "#fbbf24"
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
        self.interviews.set_pending_report(text)
        if self.session and self.session.report and not self.builder.loop:
            self.stop_camera()
        self.start_btn.setEnabled(True)

    def _on_saved(self, session_id: str):
        self.interviews.refresh(select_id=session_id)
        self.interviews.generate_learnings(session_id)  # detailed study notes, in the background
        self.statusBar().showMessage("Interview saved. Its feedback, report and history are in Past Interviews.")

    def _on_error(self, msg: str):
        self._asking = False
        if self.session and not self.session.turns:
            self._stop_live()
            self._clock.stop()
            self.iv_stack.setCurrentIndex(0)
        self.statusBar().showMessage("Error: " + msg.splitlines()[0])
        QMessageBox.warning(self, "Interview Gym", msg)
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
            patience=self.pause_box.value(), headphones=self.headphones.isChecked())
        self.live.user_text.connect(self._live_user_text)
        self.live.interviewer.connect(self._live_interviewer)
        self.live.next_requested.connect(lambda _reason: self.submit_answer())
        self.live.state.connect(self._live_state)
        self.live.partial.connect(self._live_partial)
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
                 "pushback": "Arjun", "clarify": "Arjun · clarifies",
                 "screen": "Arjun · watching your screen"}.get(kind, "Arjun")
        if kind == "ack":
            self.live_state.setText(f"Arjun: {text}")
            return
        self._append_chat(label, text)

    def _on_screen_note(self, note: str):
        if self.live:
            self.live.say(note, "screen")  # mutes the mic while speaking and shows the note in sync
            return
        self._append_chat("Arjun · watching your screen", note)
        if self.speaker and self.speak.isChecked():
            self.speaker.say(note)

    def _live_partial(self, text: str):
        if self.live and self.live._last_state in ("you", "transcribing"):
            tail = text if len(text) <= 70 else "…" + text[-70:]
            self.live_state.setText(f"●  Heard: {tail}")

    def _live_state(self, state: str):
        txt = {"listening": ("●  Listening", "#34d399"), "you": ("●  You're speaking…", "#5eead4"),
               "transcribing": ("●  Got it, writing down what you said…", "#5eead4"),
               "nomic": ("⚠  Mic sends silence: Arjun can't hear you. Pick another Microphone in setup "
                         "(earbuds in music mode have no mic)", "#fb7185"),
               "thinking": ("●  Arjun is thinking…", "#fbbf24"), "speaking": ("●  Arjun is speaking…", "#a78bfa"),
               "paused": ("●  Mic muted", "#fb7185"), "hold": ("●  Noting your answer…", "#fbbf24")}.get(state)
        if txt:
            self.live_state.setText(txt[0])
            self.live_state.setStyleSheet(f"color:{txt[1]}; font-weight:600")

    def _set_mic_ui_live(self):
        muted = bool(self.live and self.live.paused)
        self.mic_btn.setText("🔇  Muted (click to unmute)" if muted else "🎙  Mic live (click to mute)")
        self.mic_btn.setProperty("rec", "true" if muted else "false")
        self.mic_btn.style().unpolish(self.mic_btn); self.mic_btn.style().polish(self.mic_btn)

    def _confirm_end(self):
        if not self.session:
            return
        if not self.session.mostly_done:
            left = max(0, int(self.session.remaining() // 60))
            if QMessageBox.question(
                    self, "End interview early?",
                    f"You still have about {left} min left.\n\nInterviews ended early are discarded: no report, "
                    "no history and nothing added to your dashboard.\n\nEnd and discard this interview?") \
                    == QMessageBox.Yes:
                self.abort_interview()
            return
        if QMessageBox.question(self, "End interview", "Finish now and get your scored report?") \
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
            QMessageBox.information(self, "Interview Gym", "Complete at least one scored interview first.")
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
    # ------------------------------------------------------------------ camera
    def start_camera(self):
        if not self.interview_active():
            return  # the camera only ever runs during an interview
        if self.camera is None:
            self.camera = soft.CameraTracker()
        self.camera.start()
        self._cam_timer.start()
        self._sync_cam_buttons()

    def stop_camera(self):
        if self.camera:
            self.camera.stop()
        self._cam_timer.stop()
        for lbl in (self.cam_view, self.builder.cam_view, self.live_cam_view):
            lbl.clear(); lbl.setText("Camera off")
        self.cam_stats.setText("")
        self._sync_cam_buttons()

    def toggle_camera_now(self):
        """📷 button on the live screens: switch the camera on/off for this interview only."""
        if self.camera and self.camera.running:
            self.stop_camera()
        else:
            self.start_camera()
            if not (self.camera and self.camera.running):
                self.statusBar().showMessage("The camera can only run during an interview.")
        self._sync_cam_buttons()

    def _sync_cam_buttons(self):
        on = bool(self.camera and self.camera.running)
        for btn in (getattr(self, "cam_btn", None), getattr(self.builder, "cam_btn", None)):
            if btn:
                btn.setChecked(on)
                btn.setText("📷 Camera on" if on else "📷 Camera off")

    def _camera_toggled(self, on: bool):
        self.settings.use_camera = on
        self.settings.save()
        if on and self.interview_active():
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
        if self.session and not self.session.report:
            self.session.aborted = True  # closed mid-interview: discard, never saved or analysed
        super().closeEvent(e)


def _strip_done(answer: str) -> str:
    """Drop a trailing spoken 'I'm done' / 'that's my answer' from the transcript."""
    import re
    from .live import DONE_RE
    return re.sub(r"[\s,.]*(" + DONE_RE.pattern + r")[\s.!]*$", "", answer, flags=re.I).strip()


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
    log_path = DATA_DIR / "interview-gym.log"
    logging.basicConfig(filename=log_path, level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    crash_file = open(DATA_DIR / "crash.log", "a")  # noqa: SIM115 (kept open for faulthandler)
    faulthandler.enable(file=crash_file, all_threads=True)
    faulthandler.enable(file=sys.stderr, all_threads=True)
    logging.info("Interview Gym starting")

    def hook(exc_type, exc, tb):
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        logging.error("Uncaught exception:\n%s", text)
        print(text, file=sys.stderr)
        app = QApplication.instance()
        if app:
            QMessageBox.critical(None, "Interview Gym error", f"{exc_type.__name__}: {exc}\n\nDetails: {log_path}")
    sys.excepthook = hook
    threading.excepthook = lambda a: hook(a.exc_type, a.exc_value, a.exc_traceback)


def main():
    _install_crash_logging()
    app = QApplication(sys.argv)
    app.setApplicationName("Interview Gym")
    app.setDesktopFileName("interview-gym")
    from PySide6.QtGui import QIcon
    from .config import ROOT
    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256, 512):
        icon.addFile(str(ROOT / "assets" / f"interview-gym-{size}.png"))
    app.setWindowIcon(QIcon.fromTheme("interview-gym", icon))
    font = app.font()
    font.setPointSize(11)
    app.setFont(font)
    # Reading panes (feedback, report, history, learnings, chat, research, plans) get larger text.
    reading = QFont(font)
    reading.setPointSize(13)
    app.setFont(reading, "QTextBrowser")
    app.setStyleSheet(STYLE.replace("__ASSETS__", (ROOT / "assets").as_posix()))
    w = MainWindow()
    w.showMaximized()
    code = app.exec()
    import logging
    logging.info("Interview Gym exited with code %s", code)
    sys.exit(code)
