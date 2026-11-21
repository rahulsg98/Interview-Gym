"""Progress dashboard: KPIs, score trend, per-area strengths/weaknesses, readiness matrix, improvement plan."""
from __future__ import annotations

import time

from PySide6.QtCharts import (
    QBarCategoryAxis, QBarSet, QChart, QChartView, QDateTimeAxis, QHorizontalStackedBarSeries, QLineSeries,
    QScatterSeries, QValueAxis,
)
from PySide6.QtCore import QDateTime, QMargins, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QPushButton, QScrollArea, QTableWidget,
    QTableWidgetItem, QTextBrowser, QVBoxLayout, QWidget,
)

from . import progress
from .interview import ROLES
from .knowledge import DIFFICULTIES, TIER_NAMES
from .soft import SOFT_HELP, SOFT_SKILLS

BG, PANEL, GRID, TEXT, MUTED = "#14161b", "#1d2027", "#2c313b", "#e6e6e6", "#9aa0ac"
ACCENT = "#2f6fed"


def _font(size: int, weight=QFont.Normal) -> QFont:
    f = QFont()
    f.setPointSize(size)
    f.setWeight(weight)
    return f


def score_color(v: float | None) -> str:
    if v is None:
        return "#3a404d"
    if v >= 7.5:
        return "#1f9d63"
    if v >= 6:
        return "#c98a1b"
    return "#c0392b"


def _style_chart(chart: QChart, title: str) -> None:
    chart.setTitle(title)
    chart.setTitleBrush(QColor(TEXT))
    chart.setTitleFont(_font(11, QFont.DemiBold))
    chart.setBackgroundBrush(QColor(PANEL))
    chart.setBackgroundRoundness(8)
    chart.setMargins(QMargins(6, 6, 6, 6))
    chart.legend().hide()


def _style_axis(axis) -> None:
    if hasattr(axis, "setTruncateLabels"):
        axis.setTruncateLabels(False)
    axis.setLabelsBrush(QColor(MUTED))
    axis.setGridLineColor(QColor(GRID))
    axis.setLinePenColor(QColor(GRID))


class Tile(QFrame):
    def __init__(self, label: str):
        super().__init__()
        self.setStyleSheet(f"QFrame {{ background:{PANEL}; border:1px solid {GRID}; border-radius:8px; }}"
                           "QLabel { border:none; }")
        v = QVBoxLayout(self)
        self.value = QLabel("–")
        self.value.setFont(_font(20, QFont.Bold))
        self.value.setStyleSheet(f"color:{TEXT}")
        self.sub = QLabel("")
        self.sub.setStyleSheet(f"color:{MUTED}; font-size:12px")
        lab = QLabel(label)
        lab.setStyleSheet(f"color:{MUTED}; font-size:12px")
        v.addWidget(lab); v.addWidget(self.value); v.addWidget(self.sub)

    def set(self, value: str, sub: str = "", color: str = TEXT):
        self.value.setText(value)
        self.value.setStyleSheet(f"color:{color}")
        self.sub.setText(sub)


class Dashboard(QWidget):
    plan_requested = Signal(str, str, str)       # role, difficulty, tier
    practice_requested = Signal(str, str, str, str)  # role, difficulty, tier, focus area

    def __init__(self):
        super().__init__()
        outer = QVBoxLayout(self)
        bar = QHBoxLayout()
        title = QLabel("Progress")
        title.setFont(_font(18, QFont.Bold))
        bar.addWidget(title)
        bar.addStretch()
        self.role = QComboBox()
        self.role.addItem("All fields", "")
        for r in ROLES:
            self.role.addItem(r, r)
        self.diff = QComboBox()
        self.diff.addItem("All difficulties", "")
        for d, desc in DIFFICULTIES.items():
            self.diff.addItem(f"{d} ({desc.split(' (')[0]})", d)
        self.tier = QComboBox()
        self.tier.addItems(TIER_NAMES)
        self.tier.setCurrentText("Product unicorn")
        self.tier.setToolTip("Company tier used for recommendations")
        for w in (QLabel("Field"), self.role, QLabel("Difficulty"), self.diff, QLabel("Target tier"), self.tier):
            bar.addWidget(w)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh)
        bar.addWidget(refresh)
        outer.addLayout(bar)
        for c in (self.role, self.diff, self.tier):
            c.currentIndexChanged.connect(self.refresh)

        scroll = QScrollArea(widgetResizable=True)
        scroll.setFrameShape(QFrame.NoFrame)
        body = QWidget()
        scroll.setWidget(body)
        outer.addWidget(scroll)
        g = QGridLayout(body)
        g.setSpacing(12)

        self.t_sessions, self.t_answers = Tile("Sessions"), Tile("Questions answered")
        self.t_avg, self.t_ready = Tile("Avg score (last 20)"), Tile("Readiness (last 15 answers)")
        for i, t in enumerate((self.t_sessions, self.t_answers, self.t_avg, self.t_ready)):
            g.addWidget(t, 0, i)

        self.next_box = QLabel()
        self.next_box.setWordWrap(True)
        self.next_box.setTextFormat(Qt.MarkdownText)
        self.next_box.setStyleSheet(f"background:{PANEL}; border:1px solid {ACCENT}; border-radius:8px; "
                                    f"padding:10px; color:{TEXT}")
        nb = QHBoxLayout()
        nb.addWidget(self.next_box, 1)
        self.practice_btn = QPushButton("Practise weakest area")
        self.practice_btn.setObjectName("primary")
        self.practice_btn.clicked.connect(self._practice_weakest)
        nb.addWidget(self.practice_btn)
        g.addLayout(nb, 1, 0, 1, 4)

        self.trend_view = QChartView()
        self.trend_view.setRenderHint(QPainter.Antialiasing)
        self.trend_view.setMinimumHeight(260)
        self.trend_view.setStyleSheet(f"background:{BG}; border:none")
        self.area_view = QChartView()
        self.area_view.setRenderHint(QPainter.Antialiasing)
        self.area_view.setMinimumHeight(260)
        self.area_view.setStyleSheet(f"background:{BG}; border:none")
        g.addWidget(self.trend_view, 2, 0, 1, 2)
        g.addWidget(self.area_view, 2, 2, 1, 2)

        mat_lbl = QLabel("Readiness by difficulty × company tier  (avg of last 15 answers · count)")
        mat_lbl.setStyleSheet(f"color:{MUTED}")
        g.addWidget(mat_lbl, 3, 0, 1, 4)
        self.matrix = QTableWidget(len(DIFFICULTIES), len(TIER_NAMES))
        self.matrix.setHorizontalHeaderLabels(TIER_NAMES)
        self.matrix.setVerticalHeaderLabels([f"{d}  {v.split(' (')[0]}" for d, v in DIFFICULTIES.items()])
        self.matrix.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matrix.verticalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.matrix.setEditTriggers(QTableWidget.NoEditTriggers)
        self.matrix.setFixedHeight(150)
        self.matrix.setStyleSheet(f"QTableCornerButton::section {{ background:{PANEL}; border:none; }} "
                                  f"QHeaderView::section {{ background:{PANEL}; color:{MUTED}; border:none; "
                                  f"padding:4px; }} QTableWidget {{ gridline-color:{GRID}; }}")
        g.addWidget(self.matrix, 4, 0, 1, 4)

        soft_lbl = QLabel("Soft skills · communication & confidence (last 20 answers)")
        soft_lbl.setFont(_font(13, QFont.DemiBold))
        g.addWidget(soft_lbl, 5, 0, 1, 4)
        self.s_overall, self.s_pace = Tile("Soft-skill score"), Tile("Speaking pace")
        self.s_fill, self.s_eye = Tile("Filler words"), Tile("Eye contact")
        for i, t in enumerate((self.s_overall, self.s_pace, self.s_fill, self.s_eye)):
            g.addWidget(t, 6, i)
        self.soft_view = QChartView()
        self.soft_view.setRenderHint(QPainter.Antialiasing)
        self.soft_view.setMinimumHeight(260)
        self.soft_view.setStyleSheet(f"background:{BG}; border:none")
        self.soft_trend = QChartView()
        self.soft_trend.setRenderHint(QPainter.Antialiasing)
        self.soft_trend.setMinimumHeight(260)
        self.soft_trend.setStyleSheet(f"background:{BG}; border:none")
        g.addWidget(self.soft_view, 7, 0, 1, 2)
        g.addWidget(self.soft_trend, 7, 2, 1, 2)
        self.soft_lacking = QTextBrowser()
        self.soft_lacking.setMinimumHeight(170)
        g.addWidget(self.soft_lacking, 8, 0, 1, 4)

        imp_bar = QHBoxLayout()
        imp_lbl = QLabel("Improvement points")
        imp_lbl.setFont(_font(13, QFont.DemiBold))
        imp_bar.addWidget(imp_lbl)
        imp_bar.addStretch()
        self.plan_btn = QPushButton("Generate improvement plan with Claude")
        self.plan_btn.clicked.connect(
            lambda: self.plan_requested.emit(self.role.currentData(), self.diff.currentData(),
                                             self.tier.currentText()))
        imp_bar.addWidget(self.plan_btn)
        g.addLayout(imp_bar, 9, 0, 1, 4)
        self.gaps_view = QTextBrowser()
        self.gaps_view.setMinimumHeight(220)
        self.plan_view = QTextBrowser()
        self.plan_view.setMinimumHeight(220)
        g.addWidget(self.gaps_view, 10, 0, 1, 2)
        g.addWidget(self.plan_view, 10, 2, 1, 2)
        self._weakest: str | None = None

    # ------------------------------------------------------------------
    def filter(self) -> progress.Filter:
        return progress.Filter(role=self.role.currentData(), difficulty=self.diff.currentData())

    def refresh(self):
        f = self.filter()
        s = progress.summary(f)
        self.t_sessions.set(str(s["sessions"]))
        self.t_answers.set(str(s["answers"]))
        if s["recent_avg"] is not None:
            delta = ""
            if s["prev_avg"] is not None:
                d = s["recent_avg"] - s["prev_avg"]
                delta = f"{'▲' if d >= 0 else '▼'} {abs(d):.1f} vs previous 20"
            self.t_avg.set(f"{s['recent_avg']:.1f}/10", delta, score_color(s["recent_avg"]))
        else:
            self.t_avg.set("–", "no answers yet")
        ready_color = {"Ready": "#1f9d63", "Close": "#c98a1b", "Needs work": "#c0392b"}.get(s["readiness"], MUTED)
        self.t_ready.set(s["readiness"], "≥7.5 Ready · 6–7.5 Close", ready_color)

        role = f.role or "Software Developer"
        diff = f.difficulty or "Medium"
        self.next_box.setText("**Next step:** " + progress.suggest_next(f.role, diff, self.tier.currentText()))

        self._draw_trend(progress.timeline(f))
        areas = progress.by_area(f)
        self._weakest = next((a["area"] for a in areas if a["count"] >= 2), areas[0]["area"] if areas else None)
        self.practice_btn.setEnabled(self._weakest is not None)
        self._draw_areas(areas)
        self._fill_matrix(progress.readiness_matrix(f.role))
        self._fill_gaps(f, areas)
        self._fill_soft(f)
        plan = progress.latest_plan(f.role)
        if plan:
            self.plan_view.setMarkdown(f"_Plan from {time.strftime('%d %b %Y', time.localtime(plan[0]))}_\n\n"
                                       + plan[1])
        else:
            self.plan_view.setMarkdown("_No plan yet. Do a few sessions, then press "
                                       "**Generate improvement plan with Claude**._")
        _ = role

    def _draw_trend(self, points, view=None, title="Score trend (per session)"):
        chart = QChart()
        _style_chart(chart, title)
        line, dots = QLineSeries(), QScatterSeries()
        line.setPen(QPen(QColor(ACCENT), 2.5))
        dots.setColor(QColor(ACCENT)); dots.setMarkerSize(8); dots.setBorderColor(QColor(ACCENT))
        for ts, sc in points:
            ms = int(ts * 1000)
            line.append(ms, sc); dots.append(ms, sc)
        chart.addSeries(line); chart.addSeries(dots)
        x = QDateTimeAxis(); x.setFormat("dd MMM"); x.setTickCount(min(max(len(points), 2), 6))
        if points:
            lo, hi = points[0][0], points[-1][0]
            pad = max((hi - lo) * 0.04, 43200)
            lo, hi = lo - pad, hi + pad
            x.setRange(QDateTime.fromSecsSinceEpoch(int(lo)), QDateTime.fromSecsSinceEpoch(int(hi)))
        y = QValueAxis(); y.setRange(0, 10); y.setTickCount(6); y.setLabelFormat("%d")
        for a in (x, y):
            _style_axis(a)
        chart.addAxis(x, Qt.AlignBottom); chart.addAxis(y, Qt.AlignLeft)
        for s in (line, dots):
            s.attachAxis(x); s.attachAxis(y)
        (view or self.trend_view).setChart(chart)

    def _draw_areas(self, areas):
        chart = QChart()
        _style_chart(chart, "By area · recent avg (weakest at top)")
        shown = list(reversed(areas[:10]))  # bar charts draw bottom-up
        series = QHorizontalStackedBarSeries()
        series.setBarWidth(0.65)
        # One set per colour band so bars are coloured by score.
        bands = [("#c0392b", lambda v: v < 6), ("#c98a1b", lambda v: 6 <= v < 7.5), ("#1f9d63", lambda v: v >= 7.5)]
        for color, test in bands:
            bs = QBarSet("")
            bs.setColor(QColor(color)); bs.setBorderColor(QColor(color))
            for a in shown:
                bs.append(a["recent"] if test(a["recent"]) else 0)
            series.append(bs)
        series.setLabelsVisible(False)
        chart.addSeries(series)
        cats = QBarCategoryAxis()
        cats.append([f"{a['area']} ({a['count']})" for a in shown] or [" "])
        val = QValueAxis(); val.setRange(0, 10); val.setTickCount(6); val.setLabelFormat("%d")
        for a in (cats, val):
            _style_axis(a)
        chart.addAxis(cats, Qt.AlignLeft); chart.addAxis(val, Qt.AlignBottom)
        series.attachAxis(cats); series.attachAxis(val)
        self.area_view.setChart(chart)

    def _fill_matrix(self, cells):
        for r, d in enumerate(DIFFICULTIES):
            for c, t in enumerate(TIER_NAMES):
                avg, n = cells.get((d, t), (None, 0))
                label = progress.readiness_label(avg, min(n, 15))
                text = f"{avg:.1f} · {n}\n{label}" if n else "–"
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignCenter)
                item.setBackground(QColor(score_color(avg) if n >= 5 else PANEL))
                item.setForeground(QColor(TEXT))
                self.matrix.setItem(r, c, item)

    def _fill_gaps(self, f, areas):
        if not areas:
            self.gaps_view.setMarkdown("_Your weak spots will show up here after your first scored answers._")
            return
        md = []
        for a in areas[:6]:
            gaps = progress.recent_gaps(f, a["area"], limit=4)
            md.append(f"#### {a['area']} · {a['recent']:.1f}/10 ({a['count']} answers)")
            md += [f"- {g}" for g in gaps] or ["- _no specific gaps recorded_"]
            md.append("")
        self.gaps_view.setMarkdown("\n".join(md))

    def _fill_soft(self, f):
        s = progress.soft_summary(f)
        if not s:
            for t in (self.s_overall, self.s_pace, self.s_fill, self.s_eye):
                t.set("–", "no data yet")
            self.soft_lacking.setMarkdown("_Answer a few questions by voice (camera on for presence) to see your "
                                          "communication and confidence analysis._")
            self.soft_view.setChart(QChart()); self.soft_trend.setChart(QChart())
            return
        ov = s["overall"]
        delta = ""
        if ov is not None and s["prev_overall"] is not None:
            d = ov - s["prev_overall"]
            delta = f"{'▲' if d >= 0 else '▼'} {abs(d):.1f} vs previous"
        self.s_overall.set(f"{ov:.1f}/10" if ov is not None else "–", delta, score_color(ov))
        wpm = s["wpm"]
        if wpm:
            ok = 125 <= wpm <= 170
            self.s_pace.set(f"{wpm:.0f} wpm", "ideal 130-160", "#1f9d63" if ok else "#c98a1b")
        else:
            self.s_pace.set("–", "speak your answers to measure")
        fr = s["filler_rate"]
        if fr is not None:
            self.s_fill.set(f"{fr:.1f}/100 words", "aim below 3", "#1f9d63" if fr < 3 else "#c98a1b" if fr < 6
                            else "#c0392b")
        else:
            self.s_fill.set("–", "speak your answers to measure")
        ec = s["eye_contact"]
        if ec is not None:
            self.s_eye.set(f"{ec:.0f}%", f"in frame {s['presence']:.0f}% · fidget {s['fidget']}",
                           "#1f9d63" if ec >= 70 else "#c98a1b" if ec >= 50 else "#c0392b")
        else:
            self.s_eye.set("–", "turn the camera on")

        # per-dimension bars
        chart = QChart()
        _style_chart(chart, "Soft-skill dimensions (weakest at top)")
        dims = sorted(((k, v) for k, v in s["dims"].items() if k in SOFT_SKILLS), key=lambda kv: -kv[1])
        series = QHorizontalStackedBarSeries(); series.setBarWidth(0.65)
        for color, test in (("#c0392b", lambda v: v < 6), ("#c98a1b", lambda v: 6 <= v < 7.5),
                            ("#1f9d63", lambda v: v >= 7.5)):
            bs = QBarSet(""); bs.setColor(QColor(color)); bs.setBorderColor(QColor(color))
            for _, v in dims:
                bs.append(v if test(v) else 0)
            series.append(bs)
        chart.addSeries(series)
        cats = QBarCategoryAxis(); cats.append([k for k, _ in dims] or [" "])
        val = QValueAxis(); val.setRange(0, 10); val.setTickCount(6); val.setLabelFormat("%d")
        for a in (cats, val):
            _style_axis(a)
        chart.addAxis(cats, Qt.AlignLeft); chart.addAxis(val, Qt.AlignBottom)
        series.attachAxis(cats); series.attachAxis(val)
        self.soft_view.setChart(chart)
        self._draw_trend(progress.soft_timeline(f), self.soft_trend, "Soft-skill trend (per session)")

        weakest = [k for k, v in reversed(dims) if v < 7][:3]
        md = ["#### What you're lacking"]
        md += [f"- {x}" for x in progress.soft_lacking(f)] or ["- _nothing recurring yet_"]
        if weakest:
            md += ["", "#### Focus dimensions"]
            md += [f"- **{k}** ({s['dims'][k]}/10): {SOFT_HELP[k]}" for k in weakest]
        self.soft_lacking.setMarkdown("\n".join(md))

    def _practice_weakest(self):
        if self._weakest:
            self.practice_requested.emit(self.role.currentData() or "", self.diff.currentData() or "",
                                         self.tier.currentText(), self._weakest)

    def show_plan(self, text: str):
        self.plan_view.setMarkdown(text)
