"""Resume upload + analysis: extract experience, list every claim, and plan questions that verify it's genuine."""
from __future__ import annotations

import hashlib
import json
import re
import zipfile
from pathlib import Path

from . import llm
from .config import DATA_DIR

RESUME_DIR = DATA_DIR / "resumes"
RESUME_DIR.mkdir(parents=True, exist_ok=True)

ANALYST_SYSTEM = """You are a sharp technical hiring manager who has read thousands of Indian software resumes. You \
extract exactly what the candidate claims, notice vague, inflated or inconsistent claims, and plan probing \
questions that reveal whether the candidate really did the work (first-hand detail, numbers, decisions, failures)."""


def extract_text(path: str | Path) -> str:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        from PySide6.QtPdf import QPdfDocument
        doc = QPdfDocument()
        doc.load(str(path))
        text = "\n".join(doc.getAllText(i).text() for i in range(doc.pageCount()))
    elif suffix == ".docx":
        with zipfile.ZipFile(path) as z:
            xml = z.read("word/document.xml").decode("utf8", "ignore")
        xml = re.sub(r"</w:p>", "\n", xml)
        xml = re.sub(r"<w:tab/>", "\t", xml)
        text = re.sub(r"<[^>]+>", "", xml)
        text = re.sub(r"&amp;", "&", re.sub(r"&lt;", "<", re.sub(r"&gt;", ">", text)))
    else:
        text = path.read_text(errors="ignore")
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def _key(text: str) -> str:
    return hashlib.sha256(text.strip().encode()).hexdigest()[:16]


def cached(text: str) -> dict | None:
    p = RESUME_DIR / f"{_key(text)}.json"
    return json.loads(p.read_text()) if p.exists() else None


def analyze(text: str, model: str = "sonnet") -> dict:
    """Structured analysis of the resume, cached by content hash."""
    if not text.strip():
        return {}
    hit = cached(text)
    if hit:
        return hit
    prompt = f"""Analyse this resume. Focus on the EXPERIENCE section (jobs, internships) and major projects.

Resume:
{text[:12000]}

Return JSON:
{{"name": "<candidate name or ''>",
  "total_years": <number, estimated from dates>,
  "current_role": "<title @ company>",
  "experiences": [
    {{"company": "...", "title": "...", "period": "<as written>", "months": <int estimate>,
      "claims": [
        {{"claim": "<one concrete thing they say they did, close to the original wording>",
          "tech": ["..."], "metrics": ["<numbers they claim, e.g. 'reduced latency 40%'>"],
          "risk": "low | medium | high  (how likely it is inflated / team work claimed as own)",
          "verify": ["<3-4 probing questions, increasingly deep: architecture, their exact part, how they measured \
the number, a hard problem/failure, what they'd change; questions only a person who did it can answer>"]}}
      ]}}
  ],
  "projects": [{{"name": "...", "claims": ["..."], "tech": ["..."], "verify": ["..."]}}],
  "skills": ["..."],
  "red_flags": ["<vague claims, buzzword lists without evidence, impossible metrics, timeline gaps/overlaps, \
seniority mismatch>"],
  "probe_order": ["<the 6-10 claims most worth grilling, most important first, as 'Company: claim'>"]}}"""
    data = llm.ask_json(prompt, ANALYST_SYSTEM, model)
    (RESUME_DIR / f"{_key(text)}.json").write_text(json.dumps(data, indent=2))
    return data


def claim_count(a: dict) -> int:
    return sum(len(e.get("claims", [])) for e in a.get("experiences", [])) + len(a.get("projects", []))


def brief(a: dict, probed: list[str] | None = None) -> str:
    """Compact text for prompts: experience claims with their verification questions."""
    if not a:
        return ""
    lines = [f"Candidate: {a.get('name', '')} · ~{a.get('total_years', '?')} yrs · {a.get('current_role', '')}"]
    for e in a.get("experiences", []):
        lines.append(f"\n{e.get('title')} @ {e.get('company')} ({e.get('period')})")
        for c in e.get("claims", []):
            lines.append(f"  - CLAIM [{c.get('risk', '?')} risk]: {c.get('claim')}"
                         + (f" | metrics: {', '.join(c.get('metrics', []))}" if c.get("metrics") else "")
                         + (f" | tech: {', '.join(c.get('tech', []))}" if c.get("tech") else ""))
            for q in c.get("verify", [])[:4]:
                lines.append(f"      verify: {q}")
    for p in a.get("projects", []):
        lines.append(f"\nProject {p.get('name')}: {'; '.join(p.get('claims', []))} ({', '.join(p.get('tech', []))})")
    if a.get("red_flags"):
        lines.append("\nRed flags to probe: " + "; ".join(a["red_flags"]))
    if a.get("probe_order"):
        lines.append("Priority claims to grill: " + " | ".join(a["probe_order"]))
    if probed:
        lines.append("Already probed in this interview: " + " | ".join(probed))
    return "\n".join(lines)


def markdown(a: dict) -> str:
    if not a:
        return "_No resume analysed._"
    md = [f"## Resume analysis: {a.get('name', '')}",
          f"~{a.get('total_years', '?')} years · {a.get('current_role', '')}", ""]
    for e in a.get("experiences", []):
        md.append(f"### {e.get('title')} @ {e.get('company')}  ·  {e.get('period')}")
        for c in e.get("claims", []):
            risk = {"high": "🔴", "medium": "🟠", "low": "🟢"}.get(str(c.get("risk")).lower(), "⚪")
            md.append(f"- {risk} **{c.get('claim')}**")
            md += [f"    - _{q}_" for q in c.get("verify", [])[:3]]
        md.append("")
    if a.get("red_flags"):
        md += ["### Red flags an interviewer will probe"] + [f"- {x}" for x in a["red_flags"]]
    return "\n".join(md)
