"""Progress tracking: SQLite store of every scored answer, plus dashboard queries."""
from __future__ import annotations

import json
import re
import sqlite3
import time
from contextlib import closing
from dataclasses import dataclass

from .config import DATA_DIR

DB_PATH = DATA_DIR / "progress.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY, started REAL, role TEXT, difficulty TEXT, tier TEXT, company TEXT,
  round TEXT, avg_score REAL, answered INTEGER, report_path TEXT
);
CREATE TABLE IF NOT EXISTS answers (
  session_id TEXT, idx INTEGER, ts REAL, role TEXT, difficulty TEXT, tier TEXT, area TEXT, topic TEXT,
  question TEXT, answer TEXT, score REAL, strengths TEXT, gaps TEXT,
  PRIMARY KEY (session_id, idx)
);
CREATE TABLE IF NOT EXISTS soft (
  session_id TEXT, idx INTEGER, ts REAL, role TEXT, difficulty TEXT, tier TEXT, dims TEXT,
  wpm REAL, filler_rate REAL, hedge_rate REAL, longest_pause REAL, eye_contact REAL, presence REAL,
  fidget REAL, lacking TEXT, good TEXT, flags TEXT,
  PRIMARY KEY (session_id, idx)
);
CREATE TABLE IF NOT EXISTS plans (
  role TEXT, created REAL, text TEXT
);
"""


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)
    return con


def record_session(session, session_id: str, report_path: str = "") -> None:
    p = session.profile
    scored = [t for t in session.turns if isinstance(t.feedback.get("score"), (int, float))]
    avg = sum(t.feedback["score"] for t in scored) / len(scored) if scored else None
    with closing(connect()) as con, con:
        con.execute("INSERT OR REPLACE INTO sessions VALUES (?,?,?,?,?,?,?,?,?,?)",
                    (session_id, session.started, p.role, p.difficulty, p.tier, p.company, p.round,
                     avg, len(scored), report_path))
        con.execute("DELETE FROM answers WHERE session_id=?", (session_id,))
        con.execute("DELETE FROM soft WHERE session_id=?", (session_id,))
        for i, t in enumerate(session.turns):
            if t in scored:
                fb = t.feedback
                con.execute("INSERT INTO answers VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
                            (session_id, i, t.ts or session.started, p.role, p.difficulty, p.tier,
                             t.area or "Other", t.topic, t.question, t.answer, float(fb["score"]),
                             json.dumps(fb.get("strengths", [])), json.dumps(fb.get("gaps", []))))
                soft = fb.get("soft_skills") or {}
                dims = {k: v for k, v in soft.items() if isinstance(v, (int, float))}
                if dims or fb.get("delivery_flags"):
                    m, c = getattr(t, "metrics", {}) or {}, getattr(t, "camera", {}) or {}
                    con.execute("INSERT INTO soft VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                                (session_id, i, t.ts or session.started, p.role, p.difficulty, p.tier,
                                 json.dumps(dims), m.get("wpm"), m.get("filler_rate") if m.get("spoken") else None,
                                 m.get("hedge_rate") if m.get("spoken") else None, m.get("longest_pause"),
                                 c.get("eye_contact"), c.get("presence"), c.get("fidget"),
                                 json.dumps(soft.get("lacking", [])), json.dumps(soft.get("good", [])),
                                 json.dumps(fb.get("delivery_flags", []))))


@dataclass
class Filter:
    role: str = ""        # "" = all
    difficulty: str = ""  # "" = all

    def where(self) -> tuple[str, list]:
        clauses, args = [], []
        if self.role:
            clauses.append("role=?"); args.append(self.role)
        if self.difficulty:
            clauses.append("difficulty=?"); args.append(self.difficulty)
        return (" WHERE " + " AND ".join(clauses)) if clauses else "", args


def readiness_label(avg: float | None, n: int) -> str:
    if n < 5 or avg is None:
        return "Not enough data"
    if avg >= 7.5:
        return "Ready"
    if avg >= 6:
        return "Close"
    return "Needs work"


def summary(f: Filter) -> dict:
    where, args = f.where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT score FROM answers{where} ORDER BY ts DESC", args).fetchall()
        sessions = con.execute(f"SELECT COUNT(*) FROM sessions{where} AND answered>0" if where
                               else "SELECT COUNT(*) FROM sessions WHERE answered>0", args).fetchone()[0]
    scores = [r["score"] for r in rows]
    recent, prev = scores[:20], scores[20:40]
    avg = lambda xs: sum(xs) / len(xs) if xs else None  # noqa: E731
    return {"sessions": sessions, "answers": len(scores), "recent_avg": avg(recent),
            "prev_avg": avg(prev), "readiness": readiness_label(avg(scores[:15]), len(scores[:15]))}


def timeline(f: Filter) -> list[tuple[float, float]]:
    where, args = f.where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT session_id, MIN(ts) ts, AVG(score) s FROM answers{where} "
                           "GROUP BY session_id ORDER BY ts", args).fetchall()
    return [(r["ts"], r["s"]) for r in rows]


def by_area(f: Filter) -> list[dict]:
    """Per area: count, avg of last 10 answers, overall avg; weakest first."""
    where, args = f.where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT area, score, ts FROM answers{where} ORDER BY ts DESC", args).fetchall()
    areas: dict[str, list[float]] = {}
    for r in rows:
        areas.setdefault(r["area"], []).append(r["score"])
    out = [{"area": a, "count": len(s), "recent": sum(s[:10]) / len(s[:10]), "avg": sum(s) / len(s)}
           for a, s in areas.items()]
    return sorted(out, key=lambda d: d["recent"])


def readiness_matrix(role: str = "") -> dict[tuple[str, str], tuple[float | None, int]]:
    """(difficulty, tier) -> (avg of last 15, count)."""
    where, args = Filter(role=role).where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT difficulty, tier, score FROM answers{where} ORDER BY ts DESC", args).fetchall()
    cells: dict[tuple[str, str], list[float]] = {}
    for r in rows:
        cells.setdefault((r["difficulty"], r["tier"]), []).append(r["score"])
    return {k: (sum(v[:15]) / len(v[:15]), len(v)) for k, v in cells.items()}


def recent_gaps(f: Filter, area: str, limit: int = 6) -> list[str]:
    where, args = f.where()
    where = (where + " AND area=?") if where else " WHERE area=?"
    with closing(connect()) as con:
        rows = con.execute(f"SELECT gaps FROM answers{where} ORDER BY ts DESC LIMIT 15", args + [area]).fetchall()
    seen, out = set(), []
    for r in rows:
        for g in json.loads(r["gaps"] or "[]"):
            key = g.lower()[:60]
            if key not in seen:
                seen.add(key); out.append(g)
            if len(out) >= limit:
                return out
    return out


def recent_questions(role: str = "", limit: int = 80) -> list[str]:
    """Questions/problems already asked (newest first), so the interviewer can avoid repeating them."""
    where, args = Filter(role=role).where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT question, topic FROM answers{where} ORDER BY ts DESC LIMIT ?",
                           args + [limit]).fetchall()
    return [f"[{r['topic']}] {r['question'].splitlines()[0][:140]}" for r in rows]


def strong_areas(role: str = "", min_count: int = 3, min_avg: float = 7.5) -> list[str]:
    return [a["area"] for a in by_area(Filter(role=role)) if a["count"] >= min_count and a["recent"] >= min_avg]


def roles_with_data() -> list[str]:
    with closing(connect()) as con:
        return [r[0] for r in con.execute("SELECT DISTINCT role FROM answers ORDER BY role")]


def save_plan(role: str, text: str) -> None:
    with closing(connect()) as con, con:
        con.execute("INSERT INTO plans VALUES (?,?,?)", (role or "All", time.time(), text))


def latest_plan(role: str) -> tuple[float, str] | None:
    with closing(connect()) as con:
        r = con.execute("SELECT created, text FROM plans WHERE role=? ORDER BY created DESC LIMIT 1",
                        (role or "All",)).fetchone()
    return (r["created"], r["text"]) if r else None


def suggest_next(role: str, difficulty: str, tier: str) -> str:
    """Rule-based recommendation: what to practise next."""
    from .knowledge import DIFFICULTIES, TIER_NAMES
    f = Filter(role=role, difficulty=difficulty)
    areas = by_area(f)
    cell = readiness_matrix(role).get((difficulty, tier))
    msg = []
    if cell and cell[1] >= 10 and cell[0] >= 7.5:
        diffs, tiers = list(DIFFICULTIES), TIER_NAMES
        if tier != tiers[-1]:
            msg.append(f"You're consistently scoring {cell[0]:.1f} at {difficulty} / {tier}. "
                       f"Move up to **{tiers[tiers.index(tier) + 1]}** companies.")
        elif difficulty != diffs[-1]:
            msg.append(f"You've cleared the top tier at {difficulty}. Try **{diffs[diffs.index(difficulty) + 1]}**.")
    elif cell and cell[1] >= 5 and cell[0] < 6:
        msg.append(f"Average {cell[0]:.1f} at {difficulty} / {tier}. Stay here until it's above 7.5.")
    weak = [a for a in areas if a["count"] >= 2][:3]
    if weak:
        msg.append("Weakest areas: " + ", ".join(f"**{a['area']}** ({a['recent']:.1f})" for a in weak) + ".")
    return " ".join(msg) or "Do a few more sessions to unlock recommendations."


# ------------------------------------------------------------------------------------ soft skills

def soft_summary(f: Filter, last: int = 20) -> dict:
    """Averages over the last N soft-skill records."""
    where, args = f.where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT * FROM soft{where} ORDER BY ts DESC LIMIT ?", args + [last]).fetchall()
        prev = con.execute(f"SELECT dims FROM soft{where} ORDER BY ts DESC LIMIT ? OFFSET ?",
                           args + [last, last]).fetchall()
    if not rows:
        return {}

    def avg(col):
        xs = [r[col] for r in rows if r[col] is not None]
        return round(sum(xs) / len(xs), 1) if xs else None

    def dim_avgs(rs):
        acc: dict[str, list[float]] = {}
        for r in rs:
            for k, v in json.loads(r["dims"] or "{}").items():
                acc.setdefault(k, []).append(v)
        return {k: round(sum(v) / len(v), 1) for k, v in acc.items()}

    dims, prev_dims = dim_avgs(rows), dim_avgs(prev)
    overall = round(sum(dims.values()) / len(dims), 1) if dims else None
    prev_overall = round(sum(prev_dims.values()) / len(prev_dims), 1) if prev_dims else None
    return {"n": len(rows), "dims": dims, "overall": overall, "prev_overall": prev_overall,
            "wpm": avg("wpm"), "filler_rate": avg("filler_rate"), "hedge_rate": avg("hedge_rate"),
            "eye_contact": avg("eye_contact"), "presence": avg("presence"), "fidget": avg("fidget"),
            "longest_pause": avg("longest_pause")}


def soft_timeline(f: Filter) -> list[tuple[float, float]]:
    where, args = f.where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT session_id, MIN(ts) ts, GROUP_CONCAT(dims, '|') d FROM soft{where} "
                           "GROUP BY session_id ORDER BY ts", args).fetchall()
    out = []
    for r in rows:
        vals = [v for d in r["d"].split("|") for v in json.loads(d or "{}").values()]
        if vals:
            out.append((r["ts"], sum(vals) / len(vals)))
    return out


def soft_lacking(f: Filter, limit: int = 10) -> list[str]:
    where, args = f.where()
    with closing(connect()) as con:
        rows = con.execute(f"SELECT lacking, flags FROM soft{where} ORDER BY ts DESC LIMIT 25", args).fetchall()
    counts: dict[str, list] = {}
    for r in rows:
        for g in json.loads(r["lacking"] or "[]") + json.loads(r["flags"] or "[]"):
            key = re.sub(r"[\d.]+", "#", g.lower())[:50]  # '18.2 fillers' and '6.0 fillers' are the same issue
            counts.setdefault(key, [g, 0])[1] += 1
    ranked = sorted(counts.values(), key=lambda x: -x[1])
    return [f"{g}" + (f"  (×{n})" if n > 1 else "") for g, n in ranked[:limit]]
