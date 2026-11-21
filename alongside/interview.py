"""Mock interview engine: profile, transcript, prompts, persistence."""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import llm, progress
from . import resume as resume_mod
from .knowledge import AREAS, DIFFICULTY_LABELS, HARSH_RULES, TIER_NAMES, TRAPS, calibration
from .soft import SOFT_JSON, SOFT_RUBRIC, camera_flags, delivery_flags, soft_prompt_block
from .config import SESSIONS_DIR

ROLES = [
    "Software Developer", "Frontend Developer", "Backend Developer", "Full Stack Developer",
    "DevOps / Cloud Engineer", "System Design - LLD", "System Design - HLD", "DSA / Coding",
]
ROUNDS = ["Full loop (auto mix)", "Mixed technical", "Concepts deep-dive", "Coding (watch my screen)",
          "System design", "Resume / project grill", "Behavioral", "Rapid-fire"]
DURATIONS = [15, 30, 45, 60, 90, 120]

# Agenda segment kinds. "code" kinds expect work in the code pad.
SEGMENTS = {
    "resume": "Resume & experience deep-dive",
    "theory": "Concepts / theory",
    "coding": "DSA coding (write code in the pad)",
    "machine_coding": "Machine coding / LLD (write code in the pad)",
    "design": "System design (explain + draw / outline in the pad)",
    "behavioral": "Behavioral / hiring manager",
}
CODE_SEGMENTS = {"coding", "machine_coding", "design"}

AGENDA_GUIDE = """Rules of thumb for splitting interview time (adapt to role, level and round type):
- 15 min: resume 5, rapid theory 10 (no full coding problem; at most a tiny snippet).
- 30 min: resume 6-7, theory 8, one DSA coding problem 15.
- 45 min: resume 8, theory 12, one DSA coding problem 25.
- 60 min: resume 10, theory 12, coding 25, then LLD or HLD 13 (design only for Medium/Hard; Easy gets more coding).
- 90 min: resume 12, theory 15, coding 28, design or machine coding 30, behavioral 5.
- 120 min: resume 15, theory 15, coding 30, machine coding/LLD 30, HLD 25, behavioral 5.
Role tweaks: Frontend -> coding is JS/DOM/React (polyfills, components), machine coding is a UI widget, design is \
frontend system design. DevOps -> coding is scripting/troubleshooting scenarios, design is infra/platform design. \
LLD/HLD roles -> most time in design. DSA role -> most time coding.
Round-type overrides: "Coding" -> mostly coding; "System design" -> mostly design; "Resume / project grill" -> mostly \
resume; "Behavioral" -> mostly behavioral; "Concepts deep-dive" -> mostly theory; "Rapid-fire" -> many short theory \
questions. If a resume is provided, ALWAYS include a resume segment (at least 3 minutes, ~12-20% of time)."""
DIFFICULTIES = ["Easy", "Medium", "Hard"]

INTERVIEWER_SYSTEM = """You are Arjun, a senior engineer and bar-raiser at a top product company in India, running \
a realistic, tough mock interview. You speak naturally, like a real interviewer on a call: short, clear, one \
question at a time, no markdown in what you say aloud.

""" + HARSH_RULES + """

Trap catalogue (pick what fits; vary them):
""" + "\n".join(f"- {t}" for t in TRAPS) + """

Rules:
- Ask exactly one question per turn. Keep the spoken part under 60 words.
- Tailor questions to the role, level, round type, resume and job description you are given.
- Mix question styles real Indian product/service companies use: fundamentals, "how would you", \
debugging scenarios, trade-offs, and resume-based probing ("you used Kafka at X, why not RabbitMQ?").
- Follow-ups go deeper on the same topic (max 4 per main question); move to a new main question only when the topic \
is exhausted or the candidate hit their ceiling.
- Never repeat a question from this or previous sessions; prefer less-common angles.
- For coding/system design rounds, give a concrete problem and tell the candidate to write or draw it on screen.
- Never answer your own question in what you say aloud.
- Calibrate to the difficulty band and company tier, remembering there are no easy interviews any more: even \
Easy means today's tough fresher bar (LC medium floor, fundamentals down to internals, resume grilled). Top tier \
should feel like a senior Google loop."""

COACH_SYSTEM = """You are an expert interview coach for IT roles (software, frontend, backend, full stack, \
DevOps/cloud, LLD/HLD system design, DSA). You grade like a harsh bar-raiser in today's tough market: a 7 means \
'would pass a strict panel today', vague or surface-level answers get 4 or less, textbook answers without depth or \
real-world grounding get 5 at most, and falling for an interview trap is a major deduction. Be specific and honest, \
then teach the ideal answer. Answers came from speech-to-text, so ignore minor transcription errors when judging \
content (but do judge delivery from the measured delivery data)."""


@dataclass
class Profile:
    name: str = "Default"
    role: str = ROLES[0]
    difficulty: str = "Medium"
    tier: str = "Product unicorn"
    company: str = ""
    round: str = ROUNDS[0]
    resume: str = ""
    jd: str = ""
    focus: str = ""
    questions: int = 6
    duration_min: int = 45

    def describe(self) -> str:
        parts = [f"Role: {self.role}", f"Round type: {self.round}", f"Interview length: {self.duration_min} minutes",
                 calibration(self.role, self.difficulty, self.tier, self.company)]
        if self.focus.strip():
            parts.append(f"Topics to focus on: {self.focus.strip()}")
        if self.jd.strip():
            parts.append(f"Job description:\n{self.jd.strip()[:6000]}")
        info = resume_mod.cached(self.resume) if self.resume.strip() else None
        if info:
            parts.append("Candidate resume - analysed experience claims (verify these!):\n" + resume_mod.brief(info))
        elif self.resume.strip():
            parts.append(f"Candidate resume:\n{self.resume.strip()[:8000]}")
        return "\n\n".join(parts)


@dataclass
class Turn:
    question: str
    topic: str = ""
    area: str = ""
    kind: str = "question"
    trap: str = ""
    depth: int = 1
    segment: str = ""
    claim: str = ""                                   # resume claim being verified, if any
    code: str = ""                                    # code / design pad contents at submit
    exchanges: list = field(default_factory=list)     # live back-and-forth within this question [who, text, kind]
    ts: float = field(default_factory=time.time)
    answer: str = ""
    screenshots: list[str] = field(default_factory=list)
    screen_notes: list[str] = field(default_factory=list)
    feedback: dict = field(default_factory=dict)
    metrics: dict = field(default_factory=dict)       # speech delivery (wpm, fillers, pauses…)
    camera: dict = field(default_factory=dict)        # webcam presence / eye contact / fidget
    camera_shots: list[str] = field(default_factory=list)


@dataclass
class Session:
    profile: Profile
    turns: list[Turn] = field(default_factory=list)
    started: float = field(default_factory=time.time)
    report: str = ""
    model: str = "sonnet"
    agenda: list[dict] = field(default_factory=list)  # [{kind, title, minutes, focus}]
    clock_start: float = 0.0
    aborted: bool = False   # ended early by the candidate: never scored, saved or analysed
    ended: float = 0.0
    loop_id: str = ""       # set when this session is one round of a Round Builder loop
    kind: str = "interview"

    COMPLETE_FRACTION = 0.9  # ending after 90% of the time still counts as a completed interview

    @property
    def mostly_done(self) -> bool:
        return bool(self.clock_start) and self.elapsed() >= self.duration_sec * self.COMPLETE_FRACTION

    # ---------- time & agenda ----------
    @property
    def duration_sec(self) -> int:
        return int(self.profile.duration_min * 60)

    def elapsed(self) -> float:
        return time.time() - self.clock_start if self.clock_start else 0.0

    def remaining(self) -> float:
        return self.duration_sec - self.elapsed()

    def segment_at(self, elapsed: float | None = None) -> tuple[int, float]:
        """(index of current agenda segment, seconds left in it)."""
        t = self.elapsed() if elapsed is None else elapsed
        acc = 0.0
        for i, seg in enumerate(self.agenda):
            acc += seg["minutes"] * 60
            if t < acc:
                return i, acc - t
        return len(self.agenda) - 1, 0.0

    def agenda_text(self) -> str:
        if not self.agenda:
            return "(no agenda)"
        cur, left = self.segment_at()
        lines = []
        for i, s in enumerate(self.agenda):
            state = "done" if i < cur else f"CURRENT, {left / 60:.1f} min left in it" if i == cur else "upcoming"
            lines.append(f"{i + 1}. {s['title']} - {s['minutes']} min - {s.get('focus', '')} [{state}]")
        return "\n".join(lines)

    def make_agenda(self) -> list[dict]:
        p = self.profile
        has_resume = bool(p.resume.strip())
        prompt = f"""{p.describe()}

Plan the agenda for this {p.duration_min}-minute interview. Leave ~1 minute for intro/close inside the first and last \
segments. Segment kinds: {json.dumps(SEGMENTS)}.
{AGENDA_GUIDE}
Resume provided: {"yes" if has_resume else "no"}.

Return JSON: {{"agenda": [{{"kind": "<one of {list(SEGMENTS)}>", "minutes": <int>, \
"focus": "<what this segment will test for this candidate, e.g. 'Kafka claims at Paytm' or 'graphs/DP medium-hard'>"}}]}}"""
        try:
            data = llm.ask_json(prompt, INTERVIEWER_SYSTEM, self.model)
            agenda = [s for s in data.get("agenda", []) if s.get("kind") in SEGMENTS and int(s.get("minutes", 0)) > 0]
        except Exception:  # noqa: BLE001
            agenda = []
        if not agenda:
            agenda = default_agenda(p.duration_min, p.round, has_resume)
        if has_resume and not any(s["kind"] == "resume" for s in agenda):
            agenda.insert(0, {"kind": "resume", "minutes": max(3, round(p.duration_min * 0.15)),
                              "focus": "verify experience claims"})
        # Scale to the exact duration.
        total = sum(int(s["minutes"]) for s in agenda)
        for s in agenda:
            s["minutes"] = max(2, round(int(s["minutes"]) * p.duration_min / total))
            s["title"] = SEGMENTS[s["kind"]]
        agenda[-1]["minutes"] += p.duration_min - sum(s["minutes"] for s in agenda)
        self.agenda = agenda
        return agenda

    # ---------- helpers ----------
    def transcript(self, limit: int = 12) -> str:
        if not self.turns:
            return "(no questions asked yet)"
        lines = []
        for i, t in enumerate(self.turns[-limit:], 1):
            lines.append(f"Q{i} [{t.kind}, topic: {t.topic}]: {t.question}")
            for who, text, kind in t.exchanges[-8:]:
                if who == "Interviewer":
                    lines.append(f"   (interviewer {kind}: {text})")
            lines.append(f"A{i}: {t.answer or '(not answered)'}")
            if t.code.strip():
                lines.append(f"Code pad:\n{t.code.strip()[-1500:]}")
            if t.screen_notes:
                lines.append(f"Screen observations: {' | '.join(t.screen_notes)}")
            if t.feedback:
                lines.append(f"Score: {t.feedback.get('score')}/10")
        return "\n".join(lines)

    @property
    def main_questions_asked(self) -> int:
        return sum(1 for t in self.turns if t.kind == "question")

    @property
    def current(self) -> Turn | None:
        return self.turns[-1] if self.turns else None

    # ---------- LLM steps ----------
    def next_question(self) -> Turn:
        if not self.clock_start:
            self.clock_start = time.time()
        done = self.remaining() < 75 if self.agenda else self.main_questions_asked >= self.profile.questions
        seg_i, seg_left = self.segment_at()
        seg = self.agenda[seg_i] if self.agenda else {"kind": "theory", "title": "Questions", "minutes": 0}
        prev_seg = self.turns[-1].segment if self.turns else ""
        probed = [t.claim for t in self.turns if t.claim]
        history = progress.recent_questions(self.profile.role, 60)
        strong = progress.strong_areas(self.profile.role)
        followups = 0
        for t in reversed(self.turns):
            if t.kind != "followup":
                break
            followups += 1
        prompt = f"""{self.profile.describe()}

Questions asked in the candidate's PREVIOUS sessions (do not repeat these or close variants; if a topic must come \
back, ask a harder, deeper angle):
{chr(10).join(history[:60]) or "(none yet)"}

Areas the candidate is already strong in (escalate difficulty here, no basics): {", ".join(strong) or "(none yet)"}
Follow-ups already asked on the current topic: {followups} (max 4).

TIME: {int(self.elapsed() // 60)} min elapsed, {max(0, int(self.remaining() // 60))} min left of \
{self.profile.duration_min}.
AGENDA:
{self.agenda_text()}
Current segment: {seg["title"]} ({seg_left / 60:.1f} min left in it).{" This is a NEW segment: open with a one-line transition." if prev_seg and prev_seg != seg["kind"] else ""}
Segment rules:
- Ask questions that belong to the CURRENT segment only.
- resume: go claim by claim through the priority list; verify the work is genuinely theirs: drill 3-4 levels \
(architecture -> their exact part -> how they measured the numbers -> hardest bug/failure -> what they'd change), \
cross-check numbers, timeline and tech against each other and against earlier answers, and catch "we did" vs "I did". \
Already probed: {" | ".join(probed) or "nothing yet"}.
- coding / machine_coding: pose ONE problem sized to fit the time left in the segment; tell them to write it in the \
code pad; then follow-ups on complexity, edge cases, tests, optimisation. Don't pose a new problem with <8 min left.
- design: ask them to outline components, APIs, data model and scale numbers in the pad (or draw in a whiteboard \
and press 'Review my screen'), then attack the weak points.
- theory: deep concept questions tied to the role and, where possible, to tech on their resume.

Interview so far:
{self.transcript()}

{"Time is up. Close the interview politely in one or two sentences and set kind to 'wrap'." if done else
 "Greet the candidate briefly and ask the first question." if not self.turns else
 "Decide whether a follow-up on the last answer is warranted, then ask the next question."}

Return JSON: {{"say": "<what you say aloud>", "kind": "question" | "followup" | "wrap", "topic": "<short topic>", \
"segment": "<one of {list(SEGMENTS)}>", \
"claim": "<if verifying a resume claim: 'Company: claim', else ''>", \
"depth": <1=concept, 2=internals, 3=edge cases/failure, 4=scale/trade-offs, 5=real-world>, \
"trap": "<'none' or: which trap you set and what a strong candidate should do; this is hidden from the candidate>", \
"area": "<exactly one of: {' | '.join(AREAS)}>", \
"needs_screen": <true if the candidate should write code or draw on screen>}}"""
        data = llm.ask_json(prompt, INTERVIEWER_SYSTEM, self.model)
        area = data.get("area", "")
        turn = Turn(question=data.get("say", "").strip(), topic=data.get("topic", ""),
                    area=area if area in AREAS else "Behavioral & Projects" if "behav" in area.lower() else area,
                    kind=data.get("kind", "question"), trap=str(data.get("trap", "") or ""),
                    depth=int(data.get("depth") or 1) if str(data.get("depth", "1")).isdigit() else 1,
                    segment=data.get("segment") if data.get("segment") in SEGMENTS else seg["kind"],
                    claim=str(data.get("claim", "") or ""))
        if turn.segment == "resume" and turn.area not in AREAS:
            turn.area = "Resume & Experience"
        turn.feedback = {}
        self.turns.append(turn)
        return turn

    def evaluate(self, turn: Turn) -> dict:
        screens = [Path(p) for p in turn.screenshots[-2:] if Path(p).exists()]
        cams = [Path(p) for p in turn.camera_shots[-1:] if Path(p).exists()]
        images = screens + cams
        prompt = f"""{self.profile.describe()}

Question asked: {turn.question}
Hidden trap set by the interviewer: {turn.trap or "none"}
Candidate's spoken/typed answer: {turn.answer or '(no verbal answer)'}
{("Live back-and-forth during this question (hints given count against the candidate; clarifying questions asked "
  "by the candidate count in their favour):" + chr(10) + chr(10).join(f"- {w} [{k}]: {t}" for w, t, k in turn.exchanges))
 if turn.exchanges else ""}
{f"Code / design pad:{chr(10)}```{chr(10)}{turn.code[-6000:]}{chr(10)}```" if turn.code.strip() else ""}
{f"This question verifies the resume claim: {turn.claim}. Judge authenticity: does the answer show first-hand depth \
(specific numbers, decisions, trade-offs, failures, their own part) or is it vague, generic, team-credit or \
inconsistent with the resume/earlier answers?" if turn.segment == "resume" or turn.claim else ""}
{"The attached screenshots show what the candidate wrote on screen; evaluate that too." if screens else ""}

{soft_prompt_block(turn.metrics, turn.camera, len(screens), len(cams))}
{SOFT_RUBRIC}
Judge soft skills like a real interviewer forming an impression; be specific and honest.

Score against the bar for the stated difficulty band and company tier (a 7 means 'would pass this round at \
that level and tier'; 9-10 is exceptional; 4-5 is a likely reject). Evaluate the answer. Return JSON:
{{"score": <0-10 integer>,
  "verdict": "<one line, e.g. 'Good, but missed X'>",
  "strengths": ["..."],
  "gaps": ["specific missing or wrong points"],
  "model_answer": "<an ideal, concise interview-ready answer in markdown, with code if relevant>",
  "tip": "<one delivery/communication tip>",
  "trap_result": "<if a trap was set: 'Caught it' or 'Fell for it', plus one line on what they should have done; else ''>",
  "authenticity": "<resume questions only: 'Convincing' | 'Shaky' | 'Likely inflated' + why; else ''>",
  {SOFT_JSON}}}"""
        fb = llm.ask_json(prompt, COACH_SYSTEM, self.model, images)
        fb["delivery_flags"] = delivery_flags(turn.metrics) + camera_flags(turn.camera)
        turn.feedback = fb
        # Not persisted here: only completed interviews are saved/analysed (see Session.save at the end).
        return fb

    def react(self, turn: Turn, event: str) -> dict:
        """Live interviewer reaction while the candidate is answering the current question."""
        seg_i, seg_left = self.segment_at() if self.agenda else (0, 0)
        seg = self.agenda[seg_i]["title"] if self.agenda else ""
        coding = turn.segment in ("coding", "machine_coding", "design")
        convo = "\n".join(f"{w} [{k}]: {t}" for w, t, k in turn.exchanges[-20:]) or "(nothing yet)"
        prompt = f"""You are mid-interview, on this question:
"{turn.question}"
Segment: {seg} ({seg_left / 60:.1f} min left in it; {max(0, self.remaining()) / 60:.1f} min left in the interview).
Time on this question so far: {(time.time() - turn.ts) / 60:.1f} min.
{"Hidden trap you set: " + turn.trap if turn.trap and turn.trap.lower() != "none" else ""}

What has been said on this question (candidate speech is speech-to-text):
{convo}

{"Candidate's code / design pad right now:" + chr(10) + "```" + chr(10) + (turn.code[-5000:] or "(empty)") + chr(10) + "```" if coding or turn.code.strip() else ""}

Trigger: {{"utterance": "the candidate just finished speaking", "code": "the candidate paused after typing in the pad", \
"silence": "the candidate has been silent for a while", "typed": "the candidate typed a message"}}[{event!r}]

Behave like a real interviewer on a call. Decide ONE action:
- "listen": they're mid-explanation, thinking aloud, or coding productively; don't interrupt.
- "speak": short (1-2 sentences, spoken English, no markdown): answer a clarifying question without giving the \
solution away; push back on a wrong or vague claim ("Are you sure?", "Why?"); quick probe on a missing piece; nudge \
if stuck or silent ("Talk me through what you're thinking."); a small hint ONLY if they're clearly stuck for a long \
time or ask for one (kind "hint"); remind about time if the segment is nearly over.
- "next": the answer is complete (they finished and paused, said they're done, or for coding they've explained the \
solution and you've covered complexity/edge cases), OR the segment time is up. Optionally add a brief neutral \
transition in "say" (no praise). The system will then score this answer and ask the next/follow-up question.
Never give the full answer. Stay neutral-to-skeptical.

Return JSON: {{"action": "listen" | "speak" | "next", "say": "<text or ''>", \
"kind": "clarify | probe | pushback | nudge | hint | time | transition"}}"""
        return llm.ask_json(prompt, INTERVIEWER_SYSTEM, self.model)

    def hint(self, turn: Turn, on_text=None) -> str:
        prompt = (f"Question: {turn.question}\nCandidate's partial answer so far: {turn.answer or '(nothing yet)'}\n"
                  + (f"Their code/design pad:\n{turn.code[-4000:]}\n" if turn.code.strip() else "") + "\n"
                  "Give ONE short nudge (max 2 sentences) that points them in the right direction without "
                  "giving the answer away.")
        return llm.ask(prompt, COACH_SYSTEM, self.model, on_text=on_text)

    def review_screen(self, turn: Turn, shot: Path, on_text=None) -> str:
        prompt = f"""Question being worked on: {turn.question}
What the candidate has said so far: {turn.answer or '(nothing yet)'}

Look at the candidate's screen (code editor, whiteboard or diagram). React like the interviewer watching them: \
in 2-4 short sentences, note what looks right, point out a bug, missed edge case or complexity issue if any, and ask \
one probing question. Do not write the full solution. No markdown."""
        note = llm.ask(prompt, INTERVIEWER_SYSTEM, self.model, [shot], on_text=on_text)
        turn.screenshots.append(str(shot))
        turn.screen_notes.append(note)
        return note

    def final_report(self, on_text=None) -> str:
        scored = [t for t in self.turns if t.feedback.get("score") is not None]
        prompt = f"""{self.profile.describe()}

Full interview with per-answer scores:
{self.transcript(limit=50)}

Per-answer soft skills (0-10) and delivery issues:
{json.dumps([{"q": t.question[:80], "soft": t.feedback.get("soft_skills"), "flags": t.feedback.get("delivery_flags"),
              "wpm": t.metrics.get("wpm"), "eye_contact": t.camera.get("eye_contact")} for t in scored], indent=1)[:5000]}

Agenda used: {json.dumps([(s["title"], s["minutes"]) for s in self.agenda])}
Resume claim checks: {json.dumps([{"claim": t.claim, "authenticity": t.feedback.get("authenticity")} for t in scored if t.claim or t.segment == "resume"])[:3000]}

Per-answer gaps:
{json.dumps([{"q": t.question, "gaps": t.feedback.get("gaps", [])} for t in scored], indent=1)[:8000]}

Write the final feedback report in markdown:
1. Overall score /10 and a hire / lean hire / lean no-hire / no-hire verdict with one-line reason.
1b. **Resume credibility**: which claims held up, which looked shaky/inflated, and how to present them honestly with \
real depth (only if a resume segment happened).
2. Scores by topic (markdown table).
3. Top 3 strengths.
4. Top 5 gaps, most important first, each with what to study.
5. A focused 7-day practice plan.
6. **Soft skills & confidence**: score each of clarity, structure, conciseness, confidence, presence, listening \
(table), then the 3 most important things you are lacking in communication/confidence with a concrete drill for each."""
        self.report = llm.ask(prompt, COACH_SYSTEM, self.model, on_text=on_text)
        return self.report

    # ---------- persistence ----------
    @property
    def id(self) -> str:
        stamp = time.strftime("%Y%m%d-%H%M%S", time.localtime(self.started))
        return f"{stamp}_{self.profile.role.split()[0].lower()}"

    def save(self) -> Path:
        if not self.ended:
            self.ended = time.time()
        base = SESSIONS_DIR / self.id
        base.with_suffix(".json").write_text(json.dumps(asdict(self), indent=2))
        progress.record_session(self, self.id, str(base.with_suffix(".md")))
        md = [f"# Mock interview: {self.profile.role} ({self.profile.round})",
              f"{self.profile.difficulty} · {self.profile.tier}"
              + (f" · {self.profile.company}" if self.profile.company else ""),
              time.strftime("%d %b %Y %H:%M", time.localtime(self.started)), ""]
        for i, t in enumerate(self.turns, 1):
            fb = t.feedback
            md += [f"## Q{i}. {t.question}", f"**Your answer:** {t.answer or '_none_'}", ""]
            if fb:
                md += [f"**Score:** {fb.get('score')}/10 - {fb.get('verdict', '')}", "",
                       "**Gaps:** " + "; ".join(fb.get("gaps", [])), "",
                       "**Model answer:**", "", fb.get("model_answer", ""), ""]
        if self.report:
            md += ["---", "# Final report", self.report]
        base.with_suffix(".md").write_text("\n".join(md))
        return base.with_suffix(".md")


def default_agenda(duration: int, round_type: str, has_resume: bool) -> list[dict]:
    r = round_type.lower()
    if "coding" in r:
        plan = [("coding", 0.8), ("theory", 0.2)]
    elif "system design" in r:
        plan = [("design", 0.8), ("theory", 0.2)]
    elif "resume" in r:
        plan = [("resume", 0.7), ("theory", 0.3)]
    elif "behavioral" in r:
        plan = [("behavioral", 0.8), ("resume", 0.2)]
    elif "concept" in r or "rapid" in r:
        plan = [("theory", 1.0)]
    elif duration <= 15:
        plan = [("theory", 1.0)]
    elif duration <= 45:
        plan = [("theory", 0.4), ("coding", 0.6)]
    elif duration <= 60:
        plan = [("theory", 0.25), ("coding", 0.45), ("design", 0.3)]
    else:
        plan = [("theory", 0.2), ("coding", 0.3), ("machine_coding", 0.25), ("design", 0.25)]
    out = [{"kind": k, "minutes": max(2, round(duration * f)), "focus": ""} for k, f in plan]
    if has_resume and not any(s["kind"] == "resume" for s in out):
        out.insert(0, {"kind": "resume", "minutes": max(3, round(duration * 0.15)), "focus": "verify experience"})
    return out


def improvement_plan(role: str, areas: list[dict], gaps: dict[str, list[str]], difficulty: str, tier: str,
                     model: str = "sonnet", on_text=None, soft: dict | None = None,
                     soft_lacking: list[str] | None = None) -> str:
    """Turn dashboard stats into a concrete improvement plan."""
    stats = "\n".join(f"- {a['area']}: recent avg {a['recent']:.1f}/10 over {a['count']} answers" for a in areas)
    gap_txt = "\n".join(f"{area}:\n" + "\n".join(f"  - {g}" for g in gs) for area, gs in gaps.items() if gs)
    prompt = f"""Candidate target: {role or 'mixed IT roles'}, currently practising {difficulty or 'all levels'} at \
{tier or 'mixed'} companies. They have ~2+ years of experience and target product-based companies.

{calibration(role or "Software Developer", difficulty or "Medium", tier or "Product unicorn")}

Per-area scores (weakest first):
{stats}

Recent specific gaps from their answers:
{gap_txt[:6000]}

Soft skills (communication & confidence, last answers): {json.dumps(soft or {})}
Recurring communication/confidence problems:
{chr(10).join("- " + x for x in (soft_lacking or [])) or "(none recorded)"}

Write a concise improvement plan in markdown:
1. **Where you stand** - 2-3 lines, honest, relative to the bar for this level/tier.
2. **Fix first** - the 3 weakest areas; for each: what exactly is missing (use the gaps), 3-5 concrete things to \
study or practise (name specific LeetCode patterns/problems, design problems, concepts), and how to know it's fixed.
3. **Communication & confidence** - the 2-3 biggest soft-skill problems with a daily drill for each (e.g. \
answer-first structure, filler-word drill, recording yourself, STAR stories, camera eye-contact practice).
4. **Keep sharp** - strong areas and a light maintenance routine.
5. **Next 2 weeks** - day-by-day schedule mixing study and AlongSide mock sessions (say which role/round/difficulty).
6. **When to level up** - criteria to move to the next difficulty or company tier."""
    return llm.ask(prompt, COACH_SYSTEM, model, on_text=on_text)
