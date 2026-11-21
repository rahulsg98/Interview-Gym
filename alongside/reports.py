"""Past Interviews tab: every completed interview / company loop with its feedback, report and full history."""
from __future__ import annotations

import html
import json
import threading
import time
from contextlib import closing
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QComboBox, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QSplitter,
    QTabWidget, QTextBrowser, QVBoxLayout, QWidget,
)

from .config import SESSIONS_DIR

SOFT_KEYS = ["Clarity", "Structure", "Conciseness", "Confidence", "Presence", "Listening", "Thinking aloud"]


# ------------------------------------------------------------------------------------------ data

def _fmt_dur(sec: float) -> str:
    m = max(0, round(sec / 60))
    return f"{m} min" if m < 60 else f"{m // 60} hr" + (f" {m % 60} min" if m % 60 else "")


def _score_color(v) -> str:
    if not isinstance(v, (int, float)):
        return "#9aa0ac"
    return "#1f9d63" if v >= 7.5 else "#c98a1b" if v >= 6 else "#c0392b"


def load_records() -> list[dict]:
    """All completed interviews and loops, newest first."""
    out = []
    for p in SESSIONS_DIR.glob("*.json"):
        try:
            d = json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            continue
        if d.get("kind") == "loop":
            rounds = d.get("rounds", [])
            scores = [r["result"].get("score") for r in rounds if isinstance(r.get("result", {}).get("score"),
                                                                              (int, float))]
            planned = sum(r.get("duration_min", 0) for r in rounds)
            actual = sum(max(0, (r.get("ended") or 0) - (r.get("started") or 0)) for r in rounds)
            out.append({
                "id": p.stem, "kind": "loop", "path": p, "data": d, "started": d.get("started", 0),
                "mode": f"Company loop · {d.get('company', '')}",
                "details": f"{d.get('role', '')} · {d.get('difficulty', '')} · {len(rounds)} rounds",
                "planned": planned, "actual": actual / 60,
                "score": round(sum(scores) / len(scores), 1) if scores else None,
            })
        else:
            if d.get("loop_id") or d.get("kind") == "loop-round":
                continue  # shown inside its loop
            prof = d.get("profile", {})
            turns = d.get("turns", [])
            scores = [t["feedback"]["score"] for t in turns
                      if isinstance((t.get("feedback") or {}).get("score"), (int, float))]
            started = d.get("started", 0)
            clock = d.get("clock_start") or started
            ended = d.get("ended") or (max((t.get("ts") or 0) for t in turns) if turns else started)
            company = f" · {prof.get('company')}" if prof.get("company") else ""
            out.append({
                "id": p.stem, "kind": "interview", "path": p, "data": d, "started": started,
                "mode": f"Interview · {prof.get('round', '')}",
                "details": f"{prof.get('role', '')} · {prof.get('difficulty', '')} · {prof.get('tier', '')}{company}",
                "planned": prof.get("duration_min"), "actual": max(0, ended - clock) / 60 if clock else None,
                "score": round(sum(scores) / len(scores), 1) if scores else None,
            })
    return sorted(out, key=lambda r: r["started"], reverse=True)


def title_of(r: dict) -> str:
    when = time.strftime("%d %b %Y · %H:%M", time.localtime(r["started"])) if r["started"] else "Unknown date"
    planned = f"{_fmt_dur(r['planned'] * 60)} planned" if r.get("planned") else ""
    actual = f"{_fmt_dur(r['actual'] * 60)} actual" if (r.get("actual") or 0) >= 1 else ""
    dur = " / ".join(x for x in (planned, actual) if x)
    return f"{when}  ·  {r['mode']}" + (f"  ·  {dur}" if dur else "")


def _soft_line(sk: dict) -> str:
    dims = [f"{k} {sk[k]}" for k in SOFT_KEYS if isinstance((sk or {}).get(k), (int, float))]
    return " · ".join(dims)


def feedback_md(r: dict) -> str:
    d = r["data"]
    md = []
    if r["kind"] == "loop":
        for i, rd in enumerate(d.get("rounds", []), 1):
            res = rd.get("result") or {}
            md += [f"## Round {i}: {rd.get('name')} ({rd.get('type')}) · {res.get('score', '–')}/10 · "
                   f"{res.get('decision', '')}", f"**Problem:** {rd.get('problem', {}).get('title', '')}", ""]
            if res.get("verdict"):
                md += [f"_{res['verdict']}_", ""]
            for key, label in (("strengths", "Strengths"), ("gaps", "Missed / wrong"),
                               ("trap_results", "🪤 Traps")):
                if res.get(key):
                    md += [f"**{label}**"] + [f"- {x}" for x in res[key]] + [""]
            sk = res.get("soft_skills") or {}
            if _soft_line(sk):
                md += [f"**Communication & confidence:** {_soft_line(sk)}", ""]
            lacking = list(sk.get("lacking", [])) + list(res.get("delivery_flags", []))
            if lacking:
                md += ["**Lacking**"] + [f"- {x}" for x in lacking] + [""]
            if res.get("model_answer"):
                md += ["**Model answer**", "", res["model_answer"], ""]
            md.append("---")
        return "\n".join(md) or "_No feedback recorded._"
    for i, t in enumerate(d.get("turns", []), 1):
        fb = t.get("feedback") or {}
        if not fb and not t.get("answer"):
            continue
        seg = f" · {t.get('segment')}" if t.get("segment") else ""
        md += [f"## Q{i}{seg} · {fb.get('score', '–')}/10 · {fb.get('verdict', '')}", f"**{t.get('question', '')}**", ""]
        if fb.get("authenticity"):
            md += [f"**🔍 Resume claim check:** {fb['authenticity']}", ""]
        if fb.get("trap_result"):
            md += [f"**🪤 Trap:** {fb['trap_result']}", ""]
        for key, label in (("strengths", "Strengths"), ("gaps", "Missed / wrong")):
            if fb.get(key):
                md += [f"**{label}**"] + [f"- {x}" for x in fb[key]] + [""]
        sk = fb.get("soft_skills") or {}
        if _soft_line(sk):
            md += [f"**Communication & confidence:** {_soft_line(sk)}", ""]
        lacking = list(sk.get("lacking", [])) + list(fb.get("delivery_flags", []))
        if lacking:
            md += ["**Lacking**"] + [f"- {x}" for x in lacking] + [""]
        if fb.get("tip"):
            md += [f"**Delivery tip:** {fb['tip']}", ""]
        if fb.get("model_answer"):
            md += ["**Model answer**", "", fb["model_answer"], ""]
        md.append("---")
    return "\n".join(md) or "_No feedback recorded._"


def report_md(r: dict) -> str:
    rep = r["data"].get("report", "")
    return rep or "_No final report was written for this interview._"


def history_html(r: dict) -> str:
    """Full chronological conversation."""
    d = r["data"]

    def line(who, text, color="#e6e6e6", note=""):
        who_c = {"Arjun": "#7fb2ff", "You": "#7ee0a8"}.get(who, "#f5c26b")
        n = f' <span style="color:#6b7080">({html.escape(note)})</span>' if note else ""
        return (f'<p style="margin:6px 0"><b style="color:{who_c}">{html.escape(who)}</b>{n}<br>'
                f'<span style="color:{color}">{html.escape(text).replace(chr(10), "<br>")}</span></p>')

    def code_block(code):
        return (f'<pre style="background:#1d2027;border:1px solid #2c313b;padding:8px;color:#e6e6e6">'
                f'{html.escape(code)}</pre>')

    parts = []
    if r["kind"] == "loop":
        for i, rd in enumerate(d.get("rounds", []), 1):
            parts.append(f'<h3 style="color:#e6e6e6">Round {i}: {html.escape(rd.get("name", ""))} '
                         f'({html.escape(rd.get("type", ""))}, {rd.get("duration_min")} min)</h3>')
            st = rd.get("problem", {}).get("statement", "")
            if st:
                parts.append(f'<p style="color:#9aa0ac">{html.escape(st).replace(chr(10), "<br>")}</p>')
            for ts, who, text in rd.get("log", []):
                t0 = rd.get("started") or ts
                stamp = f"{int(ts - t0) // 60:02d}:{int(ts - t0) % 60:02d}"
                parts.append(line("Arjun" if who == "Interviewer" else "You" if who.startswith("You") else who,
                                  text, note=stamp))
            if rd.get("code"):
                parts.append("<b style='color:#9aa0ac'>Your editor</b>" + code_block(rd["code"]))
        return "".join(parts) or "<i>No history.</i>"
    for i, t in enumerate(d.get("turns", []), 1):
        tag = {"followup": "follow-up", "wrap": "close"}.get(t.get("kind"), f"Q{i}")
        parts.append(line("Arjun", t.get("question", ""), note=" · ".join(x for x in (tag, t.get("segment", ""),
                                                                                      t.get("topic", "")) if x)))
        exchanges = [(list(ex) + ["", "", ""])[:3] for ex in t.get("exchanges", [])]
        spoke = any(who == "Candidate" for who, _, _ in exchanges)
        for who, text, kind in exchanges:  # the live back-and-forth, in the order it happened
            if who == "Candidate":
                parts.append(line("You", text))
            elif kind != "ack":
                parts.append(line("Arjun", text, note=kind))
        if t.get("answer") and not spoke:
            parts.append(line("You", t["answer"]))
        if t.get("code", "").strip():
            parts.append("<b style='color:#9aa0ac'>Your pad</b>" + code_block(t["code"]))
        for note in t.get("screen_notes", []):
            parts.append(line("Arjun", note, note="looking at your screen"))
    return "".join(parts) or "<i>No history.</i>"


def overview_html(r: dict) -> str:
    d = r["data"]
    score = r.get("score")
    sc = f'<span style="color:{_score_color(score)};font-size:20px;font-weight:700">' \
         f'{score if score is not None else "–"}/10</span>'
    rows = [("Mode", r["mode"]), ("Details", r["details"])]
    if r.get("planned"):
        rows.append(("Planned duration", _fmt_dur(r["planned"] * 60)))
    if (r.get("actual") or 0) >= 1:
        rows.append(("Actual duration", _fmt_dur(r["actual"] * 60)))
    if r["kind"] == "interview" and d.get("agenda"):
        rows.append(("Agenda", " → ".join(f"{a.get('title', a.get('kind', '')).split(' (')[0]} {a.get('minutes')}m"
                                          for a in d["agenda"])))
    if r["kind"] == "interview":
        n = sum(1 for t in d.get("turns", []) if (t.get("feedback") or {}).get("score") is not None)
        rows.append(("Questions scored", str(n)))
    cells = "".join(f'<tr><td style="color:#9aa0ac;padding:2px 14px 2px 0">{html.escape(k)}</td>'
                    f'<td style="color:#e6e6e6">{html.escape(str(v))}</td></tr>' for k, v in rows)
    return f'<div>{sc}&nbsp;&nbsp;<span style="color:#9aa0ac">average score</span></div><table>{cells}</table>'


def delete_record(r: dict) -> None:
    """Delete an interview (files + dashboard rows). Loops also delete their round sessions."""
    from . import progress
    ids = [r["id"]]
    if r["kind"] == "loop":
        for p in SESSIONS_DIR.glob("*.json"):
            try:
                if json.loads(p.read_text()).get("loop_id") == r["id"]:
                    ids.append(p.stem)
            except Exception:  # noqa: BLE001
                continue
    with closing(progress.connect()) as con, con:
        for i in ids:
            for table in ("sessions", "answers", "soft"):
                con.execute(f"DELETE FROM {table} WHERE {'id' if table == 'sessions' else 'session_id'}=?", (i,))
    for i in ids:
        for ext in (".json", ".md"):
            (SESSIONS_DIR / f"{i}{ext}").unlink(missing_ok=True)


# ------------------------------------------------------------------------------------------ widget

class PastInterviews(QWidget):
    changed = Signal()   # emitted after a delete, so the dashboard can refresh
    _learn_progress = Signal(str, int, int, str)   # record id, done, total, error

    model_getter = staticmethod(lambda: "sonnet")

    def __init__(self):
        super().__init__()
        self.records: list[dict] = []
        self.current: dict | None = None
        self._pending = False
        self._generating: dict[str, tuple[int, int]] = {}   # id -> (done, total)
        self._learn_progress.connect(self._on_learn_progress)
        outer = QVBoxLayout(self)
        split = QSplitter()
        outer.addWidget(split)

        left = QWidget(); lv = QVBoxLayout(left)
        t = QLabel("Past interviews"); f = QFont(); f.setPointSize(16); f.setBold(True); t.setFont(f)
        lv.addWidget(t)
        frow = QHBoxLayout()
        self.search = QLineEdit(placeholderText="Search role, company, mode…")
        self.search.textChanged.connect(self._fill)
        self.kind = QComboBox(); self.kind.addItems(["All", "Interviews", "Company loops"])
        self.kind.currentIndexChanged.connect(self._fill)
        frow.addWidget(self.search, 1); frow.addWidget(self.kind)
        lv.addLayout(frow)
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.setSpacing(3)
        self.list.currentItemChanged.connect(lambda cur, _prev: self._open(cur))
        lv.addWidget(self.list, 1)
        self.count = QLabel(""); self.count.setStyleSheet("color:#9aa0ac")
        lv.addWidget(self.count)

        right = QWidget(); rv = QVBoxLayout(right)
        hrow = QHBoxLayout()
        self.title = QLabel("Select an interview")
        tf = QFont(); tf.setPointSize(13); tf.setBold(True); self.title.setFont(tf)
        self.title.setWordWrap(True)
        self.open_btn = QPushButton("Open as file")
        self.open_btn.clicked.connect(self._open_file)
        self.del_btn = QPushButton("Delete", objectName="danger")
        self.del_btn.clicked.connect(self._delete)
        hrow.addWidget(self.title, 1); hrow.addWidget(self.open_btn); hrow.addWidget(self.del_btn)
        rv.addLayout(hrow)
        self.overview = QLabel("")
        self.overview.setTextFormat(Qt.RichText)
        self.overview.setWordWrap(True)
        rv.addWidget(self.overview)
        self.tabs = QTabWidget()
        self.fb = QTextBrowser(openExternalLinks=True)
        self.report = QTextBrowser(openExternalLinks=True)
        self.history = QTextBrowser(openExternalLinks=True)
        learn_box = QWidget(); lb = QVBoxLayout(learn_box); lb.setContentsMargins(0, 4, 0, 0)
        lrow = QHBoxLayout()
        self.learn_status = QLabel("")
        self.learn_status.setStyleSheet("color:#9aa0ac")
        self.learn_btn = QPushButton("Generate learnings", objectName="primary")
        self.learn_btn.setToolTip("Write detailed study notes for every question: ideal answer, key points, your "
                                  "mistakes, how to say it, follow-ups and what to study")
        self.learn_btn.clicked.connect(lambda: self.current and self.generate_learnings(self.current["id"]))
        lrow.addWidget(self.learn_status, 1); lrow.addWidget(self.learn_btn)
        lb.addLayout(lrow)
        self.learn = QTextBrowser(openExternalLinks=True)
        lb.addWidget(self.learn, 1)
        self.tabs.addTab(self.fb, "Feedback")
        self.tabs.addTab(self.report, "Report")
        self.tabs.addTab(self.history, "History")
        self.tabs.addTab(learn_box, "Learnings")
        rv.addWidget(self.tabs, 1)

        split.addWidget(left); split.addWidget(right)
        split.setSizes([430, 900])
        self._set_buttons(False)
        self.refresh()

    def _set_buttons(self, on: bool):
        self.open_btn.setEnabled(on); self.del_btn.setEnabled(on)

    # ---------------------------------------------------------------- list
    def refresh(self, select_id: str | None = None):
        self._pending = False
        keep = select_id or (self.current["id"] if self.current else None)
        self.records = load_records()
        self._fill(select=keep)

    def _fill(self, *_args, select: str | None = None):
        q = self.search.text().strip().lower()
        kind = self.kind.currentIndex()
        self.list.blockSignals(True)
        self.list.clear()
        shown = 0
        target_row = -1
        for r in self.records:
            if kind == 1 and r["kind"] != "interview" or kind == 2 and r["kind"] != "loop":
                continue
            hay = f"{title_of(r)} {r['details']}".lower()
            if q and q not in hay:
                continue
            score = f"{r['score']}/10" if r.get("score") is not None else "–"
            when = time.strftime("%d %b %Y · %H:%M", time.localtime(r["started"])) if r["started"] else "?"
            dur = f"{_fmt_dur(r['planned'] * 60)}" if r.get("planned") else ""
            it = QListWidgetItem(f"{when}  ·  {r['mode']}\n{r['details']}  ·  {dur}  ·  score {score}")
            it.setToolTip(title_of(r))
            it.setData(Qt.UserRole, r["id"])
            it.setForeground(Qt.white)
            self.list.addItem(it)
            if r["id"] == select:
                target_row = self.list.count() - 1
            shown += 1
        self.list.blockSignals(False)
        self.count.setText(f"{shown} completed interview{'s' if shown != 1 else ''}"
                           + ("" if shown == len(self.records) else f" (of {len(self.records)})"))
        if target_row >= 0:
            self.list.setCurrentRow(target_row)
        elif self.list.count() and not self._pending:
            self.list.setCurrentRow(0)
        elif not self.list.count() and not self._pending:
            self._clear_detail("No completed interviews yet. Finish an interview to see its feedback, report "
                               "and history here.")

    def _clear_detail(self, msg: str):
        self.current = None
        self.title.setText(msg)
        self.overview.setText("")
        for v in (self.fb, self.report, self.history, self.learn):
            v.clear()
        self.learn_status.setText(""); self.learn_btn.setEnabled(False)
        self._set_buttons(False)

    def _open(self, item):
        if not item:
            return
        rid = item.data(Qt.UserRole)
        r = next((x for x in self.records if x["id"] == rid), None)
        if not r:
            return
        self._pending = False
        self.current = r
        self.title.setText(title_of(r))
        self.overview.setText(overview_html(r))
        self.fb.setMarkdown(feedback_md(r))
        self.report.setMarkdown(report_md(r))
        self.history.setHtml(history_html(r))
        self._render_learnings()
        self._set_buttons(True)

    # ---------------------------------------------------------------- learnings
    def _missing(self, r: dict) -> list[dict]:
        have = r["data"].get("learnings") or {}
        return [it for it in learning_items(r) if it["key"] not in have]

    def _render_learnings(self, keep_scroll: bool = False):
        r = self.current
        if not r:
            return
        sb = self.learn.verticalScrollBar()
        pos = sb.value()
        self.learn.setMarkdown(learnings_md(r))
        if keep_scroll:
            sb.setValue(pos)
        total = len(learning_items(r))
        missing = len(self._missing(r))
        if r["id"] in self._generating:
            done, tot = self._generating[r["id"]]
            self.learn_status.setText(f"Writing detailed notes… {done}/{tot} done")
            self.learn_btn.setEnabled(False)
            self.learn_btn.setText("Generating…")
        elif missing:
            self.learn_status.setText(f"{total - missing}/{total} questions have detailed notes")
            self.learn_btn.setEnabled(True)
            self.learn_btn.setText(f"Generate learnings ({missing})")
        else:
            self.learn_status.setText(f"Detailed notes for all {total} questions")
            self.learn_btn.setEnabled(False)
            self.learn_btn.setText("Learnings ready")

    def generate_learnings(self, rid: str):
        """Write study notes for every question that doesn't have one yet (runs in the background)."""
        if rid in self._generating:
            return
        r = next((x for x in load_records() if x["id"] == rid), None)
        if not r:
            return
        todo = self._missing(r)
        if not todo:
            return
        model = self.model_getter()
        total = len(todo)
        self._generating[rid] = (0, total)
        if self.current and self.current["id"] == rid:
            self._render_learnings(keep_scroll=True)

        def work():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            done = 0
            err = ""
            with ThreadPoolExecutor(max_workers=3) as pool:
                futs = {pool.submit(generate_learning, r, it, model): it for it in todo}
                for fut in as_completed(futs):
                    it = futs[fut]
                    try:
                        save_learning(r["path"], it["key"], fut.result())
                    except Exception as e:  # noqa: BLE001
                        err = str(e).splitlines()[0]
                    done += 1
                    self._learn_progress.emit(rid, done, total, err)
        threading.Thread(target=work, daemon=True).start()

    def _on_learn_progress(self, rid: str, done: int, total: int, err: str):
        if done >= total:
            self._generating.pop(rid, None)
        else:
            self._generating[rid] = (done, total)
        # reload that record's data from disk
        for i, rec in enumerate(self.records):
            if rec["id"] == rid:
                try:
                    rec["data"] = json.loads(Path(rec["path"]).read_text())
                except Exception:  # noqa: BLE001
                    pass
        if self.current and self.current["id"] == rid:
            self.current = next((x for x in self.records if x["id"] == rid), self.current)
            self._render_learnings(keep_scroll=True)
            if err and done >= total:
                self.learn_status.setText(self.learn_status.text() + f"  ·  some notes failed: {err}")

    # ---------------------------------------------------------------- live report while it's being written
    def show_pending(self, title: str):
        self._pending = True
        self.current = None
        self.list.clearSelection()
        self.title.setText(title)
        self.overview.setText('<span style="color:#c98a1b">Scoring your answers and writing the report…</span>')
        self.fb.setMarkdown("_Feedback appears here once scoring finishes._")
        self.history.clear()
        self.report.setMarkdown("_Writing your report…_")
        self.tabs.setCurrentWidget(self.report)
        self._set_buttons(False)

    def set_pending_report(self, text: str):
        if self._pending:
            self.report.setMarkdown(text)

    # ---------------------------------------------------------------- actions
    def _open_file(self):
        if self.current:
            md = Path(self.current["path"]).with_suffix(".md")
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(md if md.exists() else self.current["path"])))

    def _delete(self):
        r = self.current
        if not r:
            return
        if QMessageBox.question(self, "Delete interview",
                                f"Permanently delete this interview?\n\n{title_of(r)}\n\nIts feedback, report, "
                                "history and dashboard data will be removed. This can't be undone.") \
                != QMessageBox.Yes:
            return
        delete_record(r)
        self.current = None
        self.refresh()
        self.changed.emit()


# ------------------------------------------------------------------------------------------ learnings

LEARN_SYSTEM = """You are a senior engineer and interview coach writing study notes for a candidate after a mock \
interview. Be accurate, thorough and practical: explain from first principles, show how a strong candidate would \
actually answer in the interview, and connect it to real-world engineering. Use markdown; include code (with \
comments) and complexity where relevant."""


def learning_items(r: dict) -> list[dict]:
    """Every question (or round) with what the candidate actually said/wrote and the feedback they got."""
    d = r["data"]
    items = []
    if r["kind"] == "loop":
        for i, rd in enumerate(d.get("rounds", [])):
            said = "\n".join(t for _, who, t in rd.get("log", []) if str(who).startswith("You"))
            prob = rd.get("problem", {})
            items.append({"key": str(i), "label": f"Round {i + 1}: {rd.get('name', '')} ({rd.get('type', '')})",
                          "question": f"{prob.get('title', '')}\n\n{prob.get('statement', '')}".strip(),
                          "answer": said, "code": rd.get("code", ""), "feedback": rd.get("result") or {}})
        return items
    for i, t in enumerate(d.get("turns", [])):
        if t.get("kind") == "wrap" or not t.get("question"):
            continue
        said = t.get("answer", "")
        ex = [e for e in t.get("exchanges", []) if e and e[0] == "Interviewer" and len(e) > 2 and e[2] != "ack"]
        items.append({"key": str(i), "label": f"Q{i + 1}" + (f" · {t.get('topic')}" if t.get("topic") else ""),
                      "question": t["question"], "answer": said, "code": t.get("code", ""),
                      "feedback": t.get("feedback") or {},
                      "interviewer_notes": [f"{e[2]}: {e[1]}" for e in ex]})
    return items


def generate_learning(r: dict, item: dict, model: str = "sonnet") -> dict:
    from . import llm
    d = r["data"]
    if r["kind"] == "loop":
        ctx = f"{d.get('company')} company loop · {d.get('role')} · {d.get('difficulty')}"
    else:
        p = d.get("profile", {})
        ctx = f"{p.get('role')} · {p.get('difficulty')} · {p.get('tier')}" + (f" · {p.get('company')}"
                                                                               if p.get("company") else "")
    fb = item["feedback"]
    prompt = f"""Mock interview context: {ctx}.

Question:
{item['question']}

The candidate's ACTUAL answer (speech-to-text, may contain transcription errors):
{item['answer'] or '(no answer given / skipped)'}
{f"Their code / design pad:{chr(10)}```{chr(10)}{item['code'][-6000:]}{chr(10)}```" if item.get('code', '').strip() else ""}
{"Interviewer's probes/hints during the answer: " + " | ".join(item.get('interviewer_notes', [])) if item.get('interviewer_notes') else ""}

Feedback they received: score {fb.get('score', 'n/a')}/10; gaps: {json.dumps(fb.get('gaps', []))}; \
trap: {fb.get('trap_result') or fb.get('trap_results') or 'none'}.

Write detailed study notes for THIS question. Return JSON:
{{"ideal_answer": "<the complete, correct, detailed answer in markdown: explain the concept properly from first \
principles, the reasoning, trade-offs, edge cases; code with comments and time/space complexity if relevant; for \
design questions: components, APIs, data model, scale numbers, bottlenecks>",
  "key_points": ["<the points a strong candidate must hit>"],
  "your_mistakes": ["<specifically what was wrong, missing or weak in THEIR answer, and the correction>"],
  "how_to_say_it": "<a natural 60-90 second spoken answer they could give in the interview>",
  "follow_ups": [{{"q": "<likely follow-up>", "a": "<concise strong answer>"}}],
  "study": ["<specific topics, problems or resources to practise next>"]}}"""
    return llm.ask_json(prompt, LEARN_SYSTEM, model, timeout=300)


def learnings_md(r: dict) -> str:
    learn = r["data"].get("learnings") or {}
    items = learning_items(r)
    if not items:
        return "_No questions in this interview._"
    md = []
    for it in items:
        L = learn.get(it["key"])
        fb = it["feedback"]
        md += [f"## {it['label']}  ·  {fb.get('score', '–')}/10", "", "**Question**", "", it["question"], "",
               "**Your answer**", "", it["answer"] or "_(no answer / skipped)_", ""]
        if it.get("code", "").strip():
            md += ["**Your code / pad**", "", "```", it["code"].rstrip(), "```", ""]
        if not L:
            md += ["_Detailed learning notes not generated yet._", "", "---"]
            continue
        md += ["### ✅ Ideal answer", "", L.get("ideal_answer", ""), ""]
        if L.get("key_points"):
            md += ["### 🎯 Key points to hit"] + [f"- {x}" for x in L["key_points"]] + [""]
        if L.get("your_mistakes"):
            md += ["### ⚠️ Where your answer fell short"] + [f"- {x}" for x in L["your_mistakes"]] + [""]
        if L.get("how_to_say_it"):
            md += ["### 🗣️ How to say it in the interview", "", f"> {L['how_to_say_it']}", ""]
        if L.get("follow_ups"):
            md += ["### 🔁 Follow-ups to expect"]
            for fu in L["follow_ups"]:
                md += [f"- **{fu.get('q', '')}**  ", f"  {fu.get('a', '')}"]
            md.append("")
        if L.get("study"):
            md += ["### 📚 Study next"] + [f"- {x}" for x in L["study"]] + [""]
        md.append("---")
    return "\n".join(md)


_LEARN_LOCK = threading.Lock()


def save_learning(path: Path, key: str, note: dict) -> dict:
    with _LEARN_LOCK:
        d = json.loads(Path(path).read_text())
        d.setdefault("learnings", {})[key] = note
        Path(path).write_text(json.dumps(d, indent=2))
        return d
