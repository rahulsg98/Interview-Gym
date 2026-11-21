"""Round Builder: research a company's real interview loop, then run a timed, interactive mock loop."""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field

from . import llm
from .config import DATA_DIR
from .interview import COACH_SYSTEM, Profile, Session, Turn
from .knowledge import AREAS, DIFFICULTIES, HARSH_RULES, TIER_NAMES, TRAPS, calibration
from . import progress
from .soft import SOFT_JSON, SOFT_RUBRIC, camera_flags, delivery, delivery_flags, soft_prompt_block

COMPANY_DIR = DATA_DIR / "companies"
COMPANY_DIR.mkdir(parents=True, exist_ok=True)

ROUND_TYPES = ["DSA", "Machine Coding", "LLD", "HLD", "Frontend Machine Coding", "Frontend Concepts",
               "Frontend System Design", "Backend Concepts", "CS Fundamentals", "DevOps / Cloud",
               "Behavioral", "Hiring Manager"]
CODING_TYPES = {"DSA", "Machine Coding", "LLD", "Frontend Machine Coding"}

RESEARCH_SYSTEM = """You are a meticulous interview researcher. You use web search to find REAL, recent candidate \
interview experiences and compile an accurate picture of a company's interview loop. Prefer sources from the last \
2 years: LeetCode Discuss interview experiences, GeeksforGeeks interview experiences, Glassdoor, Medium/Substack \
write-ups, Blind, AmbitionBox, InterviewBit/Naukri Code360, and well-known prep blogs. Never invent sources. If \
data is thin, say so in the notes and infer from similar companies, clearly marked as inferred."""


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def cache_path(company: str, role: str, difficulty: str):
    return COMPANY_DIR / f"{_slug(company)}__{_slug(role)}__{difficulty.lower()}.json"


def cached_companies() -> list[dict]:
    out = []
    for p in sorted(COMPANY_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text())
            out.append({"path": p, "company": d.get("company", p.stem), "role": d.get("_role", ""),
                        "difficulty": d.get("_difficulty", ""), "researched": d.get("_researched", 0)})
        except Exception:  # noqa: BLE001
            continue
    return out


def research_company(company: str, role: str, difficulty: str, model: str = "sonnet",
                     on_status=None, force: bool = False) -> dict:
    """Web-research the company's interview loop for this role/level. Cached on disk."""
    path = cache_path(company, role, difficulty)
    if path.exists() and not force:
        return json.loads(path.read_text())

    def tool_status(name, inp):
        if on_status:
            if name == "WebSearch":
                on_status(f"🔎 Searching: {inp.get('query', '')}")
            elif name == "WebFetch":
                on_status(f"📄 Reading: {inp.get('url', '')[:90]}")

    years = DIFFICULTIES.get(difficulty, "")
    prompt = f"""Research the current interview process at **{company}** for the role **{role}** at level \
**{difficulty}** ({years}). Do at least 5 web searches covering: overall loop/rounds, recent interview \
experiences for this role & level, DSA/coding questions asked, machine coding / LLD problems, system design (HLD) \
problems, frontend-specific rounds if relevant, behavioral/hiring-manager themes and company values. Read the most \
useful 4-8 pages.

Then return JSON with this exact shape:
{{
 "company": "{company}",
 "tier": "<one of: {' | '.join(TIER_NAMES)}>",
 "summary": "<3-5 sentence overview of the loop and the bar for this level>",
 "rounds": [
   {{"name": "<e.g. Machine Coding>", "type": "<one of: {' | '.join(ROUND_TYPES)}>",
     "duration_min": <int>, "focus": "<what is evaluated>",
     "reported_questions": ["<actual questions/problems candidates reported for this round>", "..."]}}
 ],
 "dsa_topics": ["..."], "design_problems": ["..."], "frontend_topics": ["..."], "behavioral_themes": ["..."],
 "values": ["<company values / leadership principles if any>"],
 "tips": ["<concrete tips from candidates>"],
 "notes": "<data quality notes; mark anything inferred>",
 "sources": [{{"title": "...", "url": "..."}}]
}}
Order rounds as they happen in the real loop. Include 5-15 reported questions per round where available."""
    data = llm.ask_json(prompt, RESEARCH_SYSTEM, model, tools=("WebSearch", "WebFetch"),
                        on_tool=tool_status, timeout=900)
    data["_role"], data["_difficulty"], data["_researched"] = role, difficulty, time.time()
    for r in data.get("rounds", []):
        r["duration_min"] = int(r.get("duration_min") or 60)
        if r.get("type") not in ROUND_TYPES:
            r["type"] = "Backend Concepts"
    path.write_text(json.dumps(data, indent=2))
    return data


def research_markdown(d: dict) -> str:
    md = [f"## {d.get('company', '')}  ·  {d.get('tier', '')}", "", d.get("summary", ""), ""]
    for r in d.get("rounds", []):
        md.append(f"**{r['name']}** · {r['type']} · {r['duration_min']} min. {r.get('focus', '')}")
        md += [f"- {q}" for q in r.get("reported_questions", [])[:8]]
        md.append("")
    for key, title in (("tips", "Tips from candidates"), ("values", "Values / principles")):
        if d.get(key):
            md += [f"**{title}**"] + [f"- {x}" for x in d[key]] + [""]
    if d.get("notes"):
        md += [f"_Notes: {d['notes']}_", ""]
    if d.get("sources"):
        md += ["**Sources**"] + [f"- [{s.get('title', s.get('url'))}]({s.get('url')})" for s in d["sources"]]
    return "\n".join(md)


# --------------------------------------------------------------------------------------------- live loop

LIVE_SYSTEM = """You are Arjun, an interviewer at {company}, running the "{round}" round ({rtype}) of a realistic, \
timed mock interview for a {role} candidate at the {difficulty} level ({years}). Behave exactly like a good real \
interviewer on a video call:
- You are LISTENING most of the time. While the candidate is thinking aloud, explaining, or typing code, usually \
stay silent (action "listen"). Do not interrupt good progress.
- Speak when: the candidate asks you something; they've stated an approach and you need to probe or approve it; \
they are stuck or silent for a long time (give a small nudge, never the answer); you spot a significant bug or \
missed edge case (ask about it, don't fix it); they finished, so ask complexity/test cases/follow-ups; or time is \
nearly up.
- One or two short sentences when you speak, natural spoken English, no markdown, no code.
- For behavioral / hiring-manager rounds, ask one question at a time and dig into specifics (STAR, impact, \
conflicts, ownership), then move to the next question.
- Set move_on true only when the round's goals and follow-ups are covered, or when time is up.
- Mirror {company}'s known style and bar, but lean towards the harder end of what candidates report.
- Use the hidden traps and escalations planned for this round: when the candidate is doing well, throw an \
escalation (change a constraint, scale it up, add concurrency); when they make a claim, probe it. Never reveal traps.

{harsh}

Trap catalogue:
{traps}

Company research for this round:
{research}"""


@dataclass
class LoopRound:
    name: str
    type: str
    duration_min: int
    focus: str = ""
    reported: list[str] = field(default_factory=list)
    problem: dict = field(default_factory=dict)
    log: list[tuple[float, str, str]] = field(default_factory=list)  # (ts, who, text)
    code: str = ""
    started: float = 0.0
    ended: float = 0.0
    result: dict = field(default_factory=dict)
    audio: dict = field(default_factory=dict)     # merged speech stats for the round
    camera: dict = field(default_factory=dict)
    camera_shots: list[str] = field(default_factory=list)

    @property
    def spoken_text(self) -> str:
        return " ".join(t for _, who, t in self.log if who == "You")

    @property
    def metrics(self) -> dict:
        return delivery(self.spoken_text, self.audio)

    @property
    def is_coding(self) -> bool:
        return self.type in CODING_TYPES

    def transcript(self, limit: int = 40) -> str:
        return "\n".join(f"[{int(ts - self.started) // 60:02d}:{int(ts - self.started) % 60:02d}] {who}: {text}"
                         for ts, who, text in self.log[-limit:]) or "(nothing yet)"


@dataclass
class Loop:
    company: str
    role: str
    difficulty: str
    research: dict
    rounds: list[LoopRound]
    model: str = "sonnet"
    started: float = field(default_factory=time.time)
    report: str = ""
    resume_brief: str = ""

    @property
    def tier(self) -> str:
        t = self.research.get("tier", "")
        return t if t in TIER_NAMES else "Product unicorn"

    def _round_research(self, r: LoopRound) -> str:
        d = self.research
        extra = {"DSA": d.get("dsa_topics"), "HLD": d.get("design_problems"), "LLD": d.get("design_problems"),
                 "Machine Coding": d.get("design_problems"), "Frontend Machine Coding": d.get("frontend_topics"),
                 "Frontend Concepts": d.get("frontend_topics"), "Frontend System Design": d.get("frontend_topics"),
                 "Behavioral": d.get("behavioral_themes"), "Hiring Manager": d.get("behavioral_themes")}.get(r.type)
        parts = [f"Round focus: {r.focus}", "Questions candidates reported for this round:"]
        parts += [f"- {q}" for q in r.reported[:15]]
        if extra:
            parts.append("Related topics seen at this company: " + "; ".join(extra[:15]))
        if d.get("values") and r.type in ("Behavioral", "Hiring Manager"):
            parts.append("Company values: " + "; ".join(d["values"]))
        parts.append(calibration(self.role, self.difficulty, self.tier, self.company))
        if self.resume_brief:
            how = ("This round is the place to grill the experience section: go claim by claim, verify the work is "
                   "genuinely theirs (architecture, their exact part, how numbers were measured, failures), and "
                   "cross-check consistency." if r.type in ("Hiring Manager", "Behavioral") else
                   "Where natural, tie the problem or follow-ups to tech/claims on their resume (e.g. 'you used Redis "
                   "at X - how would that change your design here?').")
            parts.append(f"Candidate resume analysis:\n{self.resume_brief}\n{how}")
        return "\n".join(parts)

    def system_for(self, r: LoopRound) -> str:
        return LIVE_SYSTEM.format(company=self.company, round=r.name, rtype=r.type, role=self.role,
                                  difficulty=self.difficulty, years=DIFFICULTIES.get(self.difficulty, ""),
                                  research=self._round_research(r), harsh=HARSH_RULES,
                                  traps="\n".join(f"- {t}" for t in TRAPS))

    def start_round(self, r: LoopRound) -> dict:
        seen = progress.recent_questions(self.role, 40)
        prompt = f"""Create the problem for this round. It must be SIMILAR in style and domain to the reported \
questions but NOT a verbatim copy (change the domain, entities or constraints), and pitched at the HARDER end of \
what is reported. The round lasts {r.duration_min} minutes, so size it to be tight but doable for a strong candidate.
Build in at least one hidden trap (e.g. a key constraint left ambiguous, an edge case the examples don't show, a \
requirement that conflicts with the obvious approach) and plan 2-3 escalations to throw if they do well.
Do not reuse anything the candidate has already practised:
{chr(10).join(seen) or "(nothing yet)"}

Return JSON:
{{"intro": "<what you say aloud to open the round and pose the problem, max 70 words, no markdown>",
  "title": "<short problem title>",
  "statement": "<full problem statement in markdown shown on the candidate's screen: requirements, inputs/outputs, \
constraints, examples; for behavioral rounds list the first question only>",
  "inspired_by": "<which reported question(s) this mirrors>",
  "follow_ups": ["<deep follow-up questions to use later>"],
  "traps": ["<hidden traps and what a strong candidate should do>"],
  "escalations": ["<harder twists / changed constraints>"],
  "rubric": ["<what a strong answer at this level must show>"],
  "area": "<one of: {' | '.join(AREAS)}>"}}"""
        r.problem = llm.ask_json(prompt, self.system_for(r), self.model)
        r.started = time.time()
        r.log.append((r.started, "Interviewer", r.problem.get("intro", "")))
        return r.problem

    def react(self, r: LoopRound, event: str, remaining_sec: int, images=()) -> dict:
        """Decide whether the interviewer speaks now. event: 'utterance' | 'code' | 'silence' | 'typed'."""
        elapsed = int(time.time() - r.started)
        prompt = f"""Problem on screen: {r.problem.get('title')}
{r.problem.get('statement', '')[:2500]}

Follow-ups you planned: {json.dumps(r.problem.get('follow_ups', []))}
Hidden traps: {json.dumps(r.problem.get('traps', []))}
Escalations available: {json.dumps(r.problem.get('escalations', []))}

Time: {elapsed // 60} min elapsed, {max(remaining_sec, 0) // 60} min {max(remaining_sec, 0) % 60} s remaining of \
{r.duration_min} min.

Conversation so far (candidate speech is from speech-to-text):
{r.transcript()}

{"Candidate's code editor right now:" if r.is_coding else "Candidate's notes/editor right now:"}
```
{r.code[-6000:] or '(empty)'}
```

Trigger: {{"utterance": "the candidate just finished speaking", "code": "the candidate has been typing and paused", \
"silence": "the candidate has been quiet for a while", "typed": "the candidate typed a message to you", "screen": "periodic look at the candidate's screen (attached)"}}[{event!r}]

Return JSON: {{"action": "listen" | "speak", "say": "<if speak: what you say>", "move_on": <true|false>}}"""
        return llm.ask_json(prompt, self.system_for(r), self.model, images)

    def evaluate_round(self, r: LoopRound) -> dict:
        r.ended = r.ended or time.time()
        from pathlib import Path
        cams = [Path(p) for p in r.camera_shots[-2:] if Path(p).exists()]
        prompt = f"""Evaluate this completed "{r.name}" round ({r.type}) at {self.company} for a {self.role} \
at {self.difficulty} level. Use {self.company}'s bar.

Problem: {r.problem.get('title')}
{r.problem.get('statement', '')[:3000]}
Rubric: {json.dumps(r.problem.get('rubric', []))}
Hidden traps: {json.dumps(r.problem.get('traps', []))}
Time used: {int((r.ended - r.started) // 60)} of {r.duration_min} min.

Transcript:
{r.transcript(limit=200)}

Final code / notes:
```
{r.code[-8000:] or '(none)'}
```

{soft_prompt_block(r.metrics, r.camera, 0, len(cams))}
{SOFT_RUBRIC}

Return JSON:
{{"score": <0-10; 7 = would pass this round at {self.company}>, "verdict": "<one line>",
  "decision": "strong hire | hire | lean hire | lean no hire | no hire",
  "strengths": ["..."], "gaps": ["specific gaps"],
  "model_answer": "<ideal approach in markdown, with code/design sketch where relevant>",
  "trap_results": ["<for each trap: caught / fell for it + what they should have done>"],
  "tip": "<one tip for next time>", "area": "<one of: {' | '.join(AREAS)}>",
  {SOFT_JSON}}}"""
        r.result = llm.ask_json(prompt, COACH_SYSTEM, self.model, cams)
        r.result["delivery_flags"] = delivery_flags(r.metrics) + camera_flags(r.camera)
        return r.result

    def final_report(self, on_text=None) -> str:
        rows = [{"round": r.name, "type": r.type, "score": r.result.get("score"), "decision": r.result.get("decision"),
                 "gaps": r.result.get("gaps", []), "trap_results": r.result.get("trap_results"), "soft_skills": r.result.get("soft_skills"),
                 "delivery_flags": r.result.get("delivery_flags")} for r in self.rounds if r.result]
        prompt = f"""Mock {self.company} loop for {self.role} ({self.difficulty}). Round results:
{json.dumps(rows, indent=1)}

Write the debrief in markdown, like a {self.company} hiring committee:
1. Final decision (hire/no hire) and level fit, with reasoning against {self.company}'s bar.
2. Table: round, score, decision, one-line reason.
3. What would have changed the decision.
4. The 5 most important things to fix before the real {self.company} interview, each with concrete prep \
(specific problems/topics).
5. **Communication & confidence**: how you came across (clarity, structure, confidence, presence, thinking aloud), \
what's lacking, and drills to fix it.
6. A 10-day plan targeted at {self.company}."""
        self.report = llm.ask(prompt, COACH_SYSTEM, self.model, on_text=on_text)
        return self.report

    @property
    def id(self) -> str:
        return f"{time.strftime('%Y%m%d-%H%M%S', time.localtime(self.started))}_{_slug(self.company)}-loop"

    def save_round(self, r: LoopRound) -> None:
        """Store the round in the progress DB / history so it shows up on the dashboard."""
        if not r.result:
            return
        s = Session(profile=Profile(role=self.role, difficulty=self.difficulty, tier=self.tier,
                                    company=self.company, round=f"{self.company} · {r.name}", questions=1),
                    model=self.model)
        s.started = r.started
        s.ended = r.ended or time.time()
        s.loop_id = self.id
        s.kind = "loop-round"
        said = " ".join(t for _, who, t in r.log if who == "You")
        turn = Turn(question=f"{r.problem.get('title', r.name)}\n\n{r.problem.get('statement', '')}",
                    topic=r.type, area=r.result.get("area") if r.result.get("area") in AREAS else r.problem.get("area", ""),
                    answer=said + (f"\n\nCode:\n{r.code}" if r.code.strip() else ""), ts=r.started)
        turn.feedback = r.result
        turn.metrics, turn.camera, turn.camera_shots = r.metrics, r.camera, r.camera_shots
        s.turns.append(turn)
        if r is self.rounds[-1] and self.report:
            s.report = self.report
        s.save()

    def save_report(self) -> None:
        path = DATA_DIR / "sessions" / f"{self.id}.md"
        rounds = [{"name": r.name, "type": r.type, "duration_min": r.duration_min, "started": r.started,
                   "ended": r.ended, "problem": r.problem, "log": r.log, "code": r.code, "result": r.result}
                  for r in self.rounds]
        path.with_suffix(".json").write_text(json.dumps({
            "kind": "loop", "id": self.id, "company": self.company, "role": self.role,
            "difficulty": self.difficulty, "tier": self.tier, "started": self.started, "ended": time.time(),
            "report": self.report, "rounds": rounds, "research_summary": self.research.get("summary", "")},
            indent=2))
        md = [f"# {self.company} mock loop · {self.role} · {self.difficulty}", ""]
        for r in self.rounds:
            if not r.result:
                continue
            md += [f"## {r.name} ({r.type}) · {r.result.get('score')}/10 · {r.result.get('decision', '')}",
                   f"**Problem:** {r.problem.get('title', '')}", "", r.problem.get("statement", ""), "",
                   "**Transcript**", "", "```", r.transcript(limit=500), "```", "",
                   "**Your code**", "", "```", r.code or "(none)", "```", "",
                   "**Gaps:** " + "; ".join(r.result.get("gaps", [])), "",
                   "**Model answer**", "", r.result.get("model_answer", ""), ""]
        md += ["---", "# Debrief", self.report]
        path.write_text("\n".join(md))
