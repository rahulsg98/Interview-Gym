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
from .knowledge import RICH_FORMAT

SOFT_KEYS = ["Clarity", "Structure", "Conciseness", "Confidence", "Presence", "Listening", "Thinking aloud"]


# ------------------------------------------------------------------------------------------ data

def _fmt_dur(sec: float) -> str:
    m = max(0, round(sec / 60))
    return f"{m} min" if m < 60 else f"{m // 60} hr" + (f" {m % 60} min" if m % 60 else "")


def _score_color(v) -> str:
    if not isinstance(v, (int, float)):
        return "#8b93ab"
    return "#34d399" if v >= 7.5 else "#fbbf24" if v >= 6 else "#fb7185"


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


def _soft_block(sk: dict, flags: list) -> str:
    from . import richview as R
    sk = sk or {}
    meters = "".join(R.meter(k, sk[k]) for k in SOFT_KEYS if isinstance(sk.get(k), (int, float)))
    lacking = list(sk.get("lacking", [])) + list(flags or [])
    chips = "".join(R.chip(x, "warn") for x in lacking)
    if not meters and not chips:
        return ""
    return R.section("Communication & confidence", meters + (f'<div style="margin-top:8px">{chips}</div>' if chips else ""),
                     "🗣️", "cyan")


def _trap_chip(text: str) -> str:
    from . import richview as R
    if not text:
        return ""
    t = text.lower()
    kind = "good" if t.startswith("caught") else "bad" if t.startswith("fell") else "warn"
    return R.chip("🪤 " + text, kind)


def _claim_chip(text: str) -> str:
    from . import richview as R
    if not text:
        return ""
    t = text.lower()
    kind = "good" if t.startswith("convincing") else "bad" if "inflated" in t else "warn"
    return R.chip("🔍 Claim check: " + text, kind)


def _feedback_card(anchor, title, sub, score, question, fb, extra_chips="", decision="") -> str:
    from . import richview as R
    head = (f'<span class="title">{R.esc(title)}</span><span class="sub">{R.esc(sub)}</span>'
            + (R.chip(decision, "good" if "hire" in decision.lower() and "no" not in decision.lower() else "bad")
               if decision else "") + R.badge(score))
    body = f'<div class="q">{R.esc(question)}</div>' if question else ""
    if fb.get("verdict"):
        body += f'<p class="verdict">“{R.esc(fb["verdict"])}”</p>'
    chips = extra_chips + _trap_chip(fb.get("trap_result", "")) + _claim_chip(fb.get("authenticity", ""))
    if chips:
        body += f"<div>{chips}</div>"
    traps = fb.get("trap_results") or []
    good = R.section("What you got right", R.bullet_list(fb.get("strengths", []), "good"), "✅", "good")
    bad = R.section("Missed or wrong", R.bullet_list(fb.get("gaps", []), "bad"), "⚠️", "bad")
    if good or bad:
        body += f'<div class="grid2">{good or "<div></div>"}{bad or "<div></div>"}</div>'
    if traps:
        body += R.section("Traps", R.bullet_list(traps, "warn"), "🪤", "warn")
    body += _soft_block(fb.get("soft_skills") or {}, fb.get("delivery_flags", []))
    if fb.get("tip"):
        body += f'<div class="callout tip"><div class="ct">💡 Delivery tip</div><p>{R.esc(fb["tip"])}</p></div>'
    if fb.get("model_answer"):
        body += R.details("📘 Model answer", R.md(fb["model_answer"]))
    return R.card(head, body, anchor)


def feedback_html(r: dict) -> str:
    from . import richview as R
    d = r["data"]
    cards, toc = [], []
    if r["kind"] == "loop":
        for i, rd in enumerate(d.get("rounds", []), 1):
            res = rd.get("result") or {}
            toc.append((f"r{i}", f"Round {i}", res.get("score")))
            cards.append(_feedback_card(f"r{i}", f"Round {i}: {rd.get('name', '')}", rd.get("type", ""),
                                        res.get("score"), rd.get("problem", {}).get("title", ""), res,
                                        decision=res.get("decision", "")))
    else:
        for i, t in enumerate(d.get("turns", []), 1):
            fb = t.get("feedback") or {}
            if not fb and not t.get("answer"):
                continue
            sub = " · ".join(x for x in (t.get("segment", ""), t.get("topic", "")) if x)
            toc.append((f"q{i}", f"Q{i}", fb.get("score")))
            cards.append(_feedback_card(f"q{i}", f"Q{i}", sub, fb.get("score"), t.get("question", ""), fb))
    if not cards:
        return '<div class="empty">No feedback recorded.</div>'
    return _toc(toc) + "".join(cards)


def _toc(items) -> str:
    from . import richview as R
    if len(items) < 2:
        return ""
    links = "".join(f'<a href="#" onclick="jump(\'{a}\');return false;">{R.esc(label)} '
                    f'<span class="{R.score_class(sc)}" style="color:inherit;opacity:.8">'
                    f'{sc if sc is not None else "–"}</span></a>' for a, label, sc in items)
    return f'<div class="toc">{links}</div>'


def report_html(r: dict) -> str:
    from . import richview as R
    rep = r["data"].get("report", "")
    score = r.get("score")
    hero = (f'<div class="hero">{R.badge(score).replace("badge ", "badge big ")}<div><div class="t">Final report</div>'
            f'<div class="s">{R.esc(r.get("mode", ""))} · {R.esc(r.get("details", ""))}</div></div></div>')
    if not rep:
        return hero + '<div class="empty">No final report was written for this interview.</div>'
    return hero + f'<div class="card">{R.md(rep)}</div>'


def report_stream_html(text: str) -> str:
    from . import richview as R
    return f'<div class="card">{R.md(text) or "<p class=muted>Writing your report…</p>"}</div>'


def history_html(r: dict) -> str:
    """Full chronological conversation as chat bubbles."""
    from . import richview as R
    d = r["data"]

    def bubble(who, text, note="", cls=None):
        cls = cls or ("arjun" if who == "Arjun" else "you" if who == "You" else "arjun")
        tag = f' <span class="tag">· {R.esc(note)}</span>' if note else ""
        return f'<div class="bubble {cls}"><div class="who">{R.esc(who)}{tag}</div>{R.esc(text)}</div>'

    def code_block(code, label):
        return f'<div class="sec info"><h4>💻 {R.esc(label)}</h4>{R.md(chr(10).join(["```", code.rstrip(), "```"]))}</div>'

    parts = []
    if r["kind"] == "loop":
        for i, rd in enumerate(d.get("rounds", []), 1):
            parts.append(f'<h2>Round {i}: {R.esc(rd.get("name", ""))} <span class="muted small">'
                         f'{R.esc(rd.get("type", ""))} · {rd.get("duration_min")} min</span></h2>')
            st = rd.get("problem", {}).get("statement", "")
            if st:
                parts.append(f'<div class="q">{R.md(st)}</div>')
            chat = []
            for ts, who, text in rd.get("log", []):
                t0 = rd.get("started") or ts
                stamp = f"{int(ts - t0) // 60:02d}:{int(ts - t0) % 60:02d}"
                w = "Arjun" if who == "Interviewer" else "You" if str(who).startswith("You") else str(who)
                chat.append(bubble(w, text, stamp))
            parts.append(f'<div class="chat">{"".join(chat)}</div>')
            if rd.get("code"):
                parts.append(code_block(rd["code"], "Your editor"))
        return "".join(parts) or '<div class="empty">No history.</div>'
    for i, t in enumerate(d.get("turns", []), 1):
        tag = {"followup": "follow-up", "wrap": "closing"}.get(t.get("kind"), f"Q{i}")
        note = " · ".join(x for x in (tag, t.get("segment", ""), t.get("topic", "")) if x)
        chat = [bubble("Arjun", t.get("question", ""), note, "qb")]
        exchanges = [(list(ex) + ["", "", ""])[:3] for ex in t.get("exchanges", [])]
        spoke = any(who == "Candidate" for who, _, _ in exchanges)
        for who, text, kind in exchanges:  # the live back-and-forth, in the order it happened
            if who == "Candidate":
                chat.append(bubble("You", text))
            elif kind != "ack":
                chat.append(bubble("Arjun", text, kind))
        if t.get("answer") and not spoke:
            chat.append(bubble("You", t["answer"]))
        for sn in t.get("screen_notes", []):
            chat.append(bubble("Arjun", sn, "looking at your screen"))
        parts.append(f'<div class="chat" style="margin-bottom:8px">{"".join(chat)}</div>')
        if t.get("code", "").strip():
            parts.append(code_block(t["code"], "Your workspace"))
        parts.append("<hr>")
    return "".join(parts) or '<div class="empty">No history.</div>'


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
    cells = "".join(f'<tr><td style="color:#8b93ab;padding:2px 14px 2px 0">{html.escape(k)}</td>'
                    f'<td style="color:#e9ecf5">{html.escape(str(v))}</td></tr>' for k, v in rows)
    return f'<div>{sc}&nbsp;&nbsp;<span style="color:#8b93ab">average score</span></div><table>{cells}</table>'


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
        self.count = QLabel(""); self.count.setStyleSheet("color:#8b93ab")
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
        from .richview import RichView
        self.fb = RichView()
        self.report = RichView()
        self.history = RichView()
        learn_box = QWidget(); lb = QVBoxLayout(learn_box); lb.setContentsMargins(0, 4, 0, 0)
        lrow = QHBoxLayout()
        self.learn_status = QLabel("")
        self.learn_status.setStyleSheet("color:#8b93ab")
        self.learn_btn = QPushButton("Generate learnings", objectName="primary")
        self.learn_btn.setToolTip("Write detailed study notes for every question: ideal answer, key points, your "
                                  "mistakes, how to say it, follow-ups and what to study")
        self.learn_btn.clicked.connect(lambda: self.current and self.generate_learnings(self.current["id"]))
        lrow.addWidget(self.learn_status, 1); lrow.addWidget(self.learn_btn)
        lb.addLayout(lrow)
        self.learn = RichView()
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
        self.fb.set_html(feedback_html(r), "top")
        self.report.set_html(report_html(r), "top")
        self.history.set_html(history_html(r), "top")
        self._render_learnings()
        self._set_buttons(True)

    # ---------------------------------------------------------------- learnings
    def _missing(self, r: dict) -> list[dict]:
        """Questions without notes, or with notes written before study links existed."""
        have = r["data"].get("learnings") or {}
        return [it for it in learning_items(r) if it["key"] not in have or "resources" not in have[it["key"]]]

    def _render_learnings(self, keep_scroll: bool = False):
        r = self.current
        if not r:
            return
        self.learn.set_html(learnings_html(r), "keep" if keep_scroll else "top")
        total = len(learning_items(r))
        missing = len(self._missing(r))
        if r["id"] in self._generating:
            done, tot = self._generating[r["id"]]
            self.learn_status.setText(f"Writing detailed notes… {done}/{tot} done")
            self.learn_btn.setEnabled(False)
            self.learn_btn.setText("Generating…")
        elif missing:
            have = r["data"].get("learnings") or {}
            noted = sum(1 for it in learning_items(r) if it["key"] in have)
            links_only = all(it["key"] in have for it in self._missing(r))
            self.learn_status.setText(f"{noted}/{total} questions have detailed notes"
                                      + (f" · {missing} need study links" if links_only else ""))
            self.learn_btn.setEnabled(True)
            self.learn_btn.setText(f"Add study links ({missing})" if links_only else f"Generate learnings ({missing})")
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
        have = r["data"].get("learnings") or {}
        total = len(todo)
        self._generating[rid] = (0, total)
        if self.current and self.current["id"] == rid:
            self._render_learnings(keep_scroll=True)

        def work():
            from concurrent.futures import ThreadPoolExecutor, as_completed
            done = 0
            err = ""
            with ThreadPoolExecutor(max_workers=3) as pool:
                futs = {(pool.submit(generate_resources, r, it, model) if it["key"] in have
                         else pool.submit(generate_learning, r, it, model)): it for it in todo}
                for fut in as_completed(futs):
                    it = futs[fut]
                    try:
                        res = fut.result()
                        note = dict(have[it["key"]], resources=res) if isinstance(res, list) else res
                        save_learning(r["path"], it["key"], note)
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
        self.overview.setText('<span style="color:#fbbf24">Scoring your answers and writing the report…</span>')
        self.fb.set_html('<div class="empty">Feedback appears here once scoring finishes.</div>', "top")
        self.history.clear()
        self.report.set_html(report_stream_html(""), "top")
        self.tabs.setCurrentWidget(self.report)
        self._set_buttons(False)

    def set_pending_report(self, text: str):
        if self._pending:
            self.report.set_html(report_stream_html(text), "follow")

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
actually answer in the interview, and connect it to real-world engineering.
""" + RICH_FORMAT


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
  "study": ["<specific topics, problems or resources to practise next>"],
  "resources": {RESOURCES_SPEC}}}"""
    note = llm.ask_json(prompt, LEARN_SYSTEM, model, timeout=300)
    note["resources"] = check_resources(note.get("resources") or [])
    return note


RESOURCES_SPEC = """[{"kind": "doc" | "article" | "practice" | "video", "title": "<what it is>", "url": "<for doc/article/practice ONLY: a URL you are certain exists>", "channel": "<for video: the YouTube channel>", "search": "<for video: the topic to search on that channel>", "why": "<one line: what exactly to learn from it for THIS question>"}]
3-6 resources so the candidate can learn exactly this properly next time. Rules:
- doc/article/practice: only canonical, stable pages you are sure exist: official docs (docs.oracle.com, docs.python.org, developer.mozilla.org, react.dev, nodejs.org, kubernetes.io/docs, docs.docker.com, postgresql.org/docs, redis.io/docs, kafka.apache.org/documentation, docs.aws.amazon.com, go.dev/doc, cppreference.com…), well-known guides (GeeksforGeeks, Baeldung, refactoring.guru, martinfowler.com, github.com/donnemartin/system-design-primer, the company engineering blog) or practice problems (leetcode.com/problems/<slug>/). Prefer the most specific page for the concept. Never guess a URL.
- video: never write a video URL or ID; give the channel and a precise search instead. Good channels: NeetCode, take U forward, Abdul Bari, ByteByteGo, Gaurav Sen, Hussein Nasser, Arpit Bhayani, Concept & Coding, TechWorld with Nana, Fireship, Jack Herrington, Web Dev Simplified, Akshay Saini, Coding with John, CodeWithHarry."""


def _yt(channel: str, search: str) -> str:
    from urllib.parse import quote_plus
    return "https://www.youtube.com/results?search_query=" + quote_plus(f"{channel} {search}".strip())


def check_resources(res: list) -> list:
    """Turn video entries into YouTube search links and verify doc links exist; a dead link becomes a search."""
    import urllib.request
    from concurrent.futures import ThreadPoolExecutor
    from urllib.parse import quote_plus, urlparse

    def fix(x: dict) -> dict | None:
        if not isinstance(x, dict) or not (x.get("title") or x.get("search")):
            return None
        x = dict(x)
        if x.get("kind") == "video" or not x.get("url"):
            x["kind"] = "video" if x.get("kind") == "video" else x.get("kind", "doc")
            x["url"] = _yt(x.get("channel", ""), x.get("search") or x.get("title", "")) if x["kind"] == "video" \
                else "https://www.google.com/search?q=" + quote_plus(x.get("title", ""))
            return x
        url = x["url"]
        if not url.startswith("http"):
            return None
        ok = False
        try:
            req = urllib.request.Request(url, method="GET", headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64)",
                                                                     "Range": "bytes=0-2048"})
            with urllib.request.urlopen(req, timeout=8) as resp:
                ok = resp.status < 400
        except urllib.error.HTTPError as e:
            ok = e.code in (401, 403, 405, 429, 999)  # exists but refuses bots
        except Exception:  # noqa: BLE001
            ok = False
        if not ok:  # broken or invented link: fall back to a search on that site
            host = urlparse(url).netloc
            x["url"] = "https://www.google.com/search?q=" + quote_plus(f"site:{host} {x.get('title', '')}")
            x["searched"] = True
        return x

    with ThreadPoolExecutor(max_workers=6) as pool:
        return [r for r in pool.map(fix, res[:8]) if r]


def generate_resources(r: dict, item: dict, model: str = "sonnet") -> list:
    """Study links only (for notes written before links existed)."""
    from . import llm
    fb = item["feedback"]
    prompt = f"""Interview question:
{item['question']}

Gaps in the candidate's answer: {json.dumps(fb.get('gaps', []))}

Recommend docs and YouTube videos to learn exactly what this question needs. Return JSON: {{"resources": {RESOURCES_SPEC}}}"""
    data = llm.ask_json(prompt, LEARN_SYSTEM, model, timeout=180)
    return check_resources(data.get("resources") or [])


def learnings_html(r: dict) -> str:
    from . import richview as R
    learn = r["data"].get("learnings") or {}
    items = learning_items(r)
    if not items:
        return '<div class="empty">No questions in this interview.</div>'
    toc, cards = [], []
    icon = {"video": "▶️", "practice": "🧩", "article": "📝"}
    for n, it in enumerate(items, 1):
        L = learn.get(it["key"])
        fb = it["feedback"]
        anchor = f"l{n}"
        toc.append((anchor, it["label"].split(" · ")[0], fb.get("score")))
        head = (f'<span class="title">{R.esc(it["label"])}</span>' + R.badge(fb.get("score")))
        body = f'<div class="q">{R.esc(it["question"])}</div>'
        yours = f'<p>{R.esc(it["answer"])}</p>' if it["answer"] else '<p class="muted">(no answer / skipped)</p>'
        if it.get("code", "").strip():
            yours += R.md("```\n" + it["code"].rstrip() + "\n```")
        body += R.details("🎙️ What you actually said", yours)
        if not L:
            body += '<div class="callout note"><div class="ct">📝 Not written yet</div><p>Press <b>Generate learnings</b> above.</p></div>'
            cards.append(R.card(head, body, anchor))
            continue
        if L.get("your_mistakes"):
            body += R.section("Where your answer fell short", R.bullet_list(L["your_mistakes"], "bad"), "⚠️", "bad")
        if L.get("key_points"):
            body += R.section("Key points to hit", R.bullet_list(L["key_points"], "check"), "🎯", "good")
        if L.get("ideal_answer"):
            body += f'<h3>✅ Ideal answer, explained</h3>{R.md(L["ideal_answer"])}'
        if L.get("how_to_say_it"):
            body += (f'<div class="callout example"><div class="ct">🗣️ How to say it in the interview (60-90 s)</div>'
                     f'<p>{R.esc(L["how_to_say_it"])}</p></div>')
        if L.get("follow_ups"):
            fus = "".join(R.details(f'🔁 {R.esc(fu.get("q", ""))}', R.md(fu.get("a", ""))) for fu in L["follow_ups"])
            body += f'<h3>Follow-ups to expect</h3>{fus}'
        if L.get("study"):
            body += R.section("Study next", "".join(R.chip(x, "info") for x in L["study"]), "📚", "info")
        if L.get("resources"):
            res = ""
            for x in L["resources"]:
                label = x.get("title") or x.get("search", "")
                if x.get("kind") == "video":
                    label = f"YouTube · {x.get('channel', '')}: {x.get('search') or label}"
                note = " <span class='muted small'>(search: exact page not verified)</span>" if x.get("searched") else ""
                why = f'<div class="rw">{R.esc(x["why"])}</div>' if x.get("why") else ""
                res += (f'<div class="res"><span class="ri">{icon.get(x.get("kind"), "📄")}</span><div>'
                        f'<a class="rt" href="{R.esc(x["url"])}">{R.esc(label)}</a>{note}{why}</div></div>')
            body += R.section("Learn more: docs & videos", res, "🔗", "cyan")
        cards.append(R.card(head, body, anchor))
    return _toc(toc) + "".join(cards)


def learnings_md(r: dict) -> str:
    """Plain markdown version (for the exported .md file)."""
    learn = r["data"].get("learnings") or {}
    md = []
    for it in learning_items(r):
        L = learn.get(it["key"]) or {}
        md += [f"## {it['label']}", "", it["question"], "", "**Your answer:** " + (it["answer"] or "(none)"), ""]
        for k, t in (("ideal_answer", "Ideal answer"), ("how_to_say_it", "How to say it")):
            if L.get(k):
                md += [f"### {t}", "", L[k], ""]
        for x in L.get("resources", []):
            md.append(f"- [{x.get('title') or x.get('search')}]({x.get('url')})")
        md.append("---")
    return "\n".join(md)


_LEARN_LOCK = threading.Lock()


def save_learning(path: Path, key: str, note: dict) -> dict:
    with _LEARN_LOCK:
        d = json.loads(Path(path).read_text())
        d.setdefault("learnings", {})[key] = note
        Path(path).write_text(json.dumps(d, indent=2))
        return d
