"""Claude access through the local Claude Code CLI (uses your Pro/Max login, no API key)."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Callable, Iterable

from .config import TMP_DIR


class ClaudeError(RuntimeError):
    pass


def claude_path() -> str:
    path = shutil.which("claude") or str(Path.home() / ".local/bin/claude")
    if not Path(path).exists():
        raise ClaudeError("Claude Code CLI not found. Install it and run `claude` once to log in.")
    return path


def ask(
    prompt: str,
    system: str,
    model: str = "sonnet",
    images: Iterable[Path] = (),
    on_text: Callable[[str], None] | None = None,
    timeout: int = 180,
    tools: Iterable[str] = (),
    on_tool: Callable[[str, dict], None] | None = None,
) -> str:
    """Send one stateless request to Claude, streaming text chunks to on_text. Returns full text."""
    images = [Path(p).resolve() for p in images]
    if images:
        listing = "\n".join(f"- {p}" for p in images)
        prompt = (
            f"First use the Read tool to view these screenshot(s) of the candidate's screen:\n{listing}\n\n"
            + prompt
        )

    cmd = [
        claude_path(), "-p",
        "--model", model,
        "--system-prompt", system,
        "--output-format", "stream-json", "--verbose", "--include-partial-messages",
        "--no-session-persistence",
        "--setting-sources", "",
        "--strict-mcp-config",
    ]
    tool_list = list(tools) + (["Read"] if images else [])
    if tool_list:
        cmd += ["--tools", ",".join(tool_list), "--allowedTools", *tool_list]
        if images:
            cmd += ["--add-dir", str(images[0].parent)]
    else:
        cmd += ["--tools", ""]

    proc = subprocess.Popen(
        cmd, cwd=TMP_DIR, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
        stderr=subprocess.PIPE, text=True, bufsize=1,
    )
    assert proc.stdin and proc.stdout
    proc.stdin.write(prompt)
    proc.stdin.close()

    chunks: list[str] = []
    final: str | None = None
    error: str | None = None
    for line in proc.stdout:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = msg.get("type")
        if kind == "stream_event":
            ev = msg.get("event", {})
            delta = ev.get("delta", {})
            if ev.get("type") == "content_block_delta" and delta.get("type") == "text_delta":
                chunks.append(delta["text"])
                if on_text:
                    on_text(delta["text"])
            elif ev.get("type") == "message_start" and chunks:
                # A new assistant turn after a tool call: separate it from earlier text.
                chunks.append("\n\n")
        elif kind == "assistant" and on_tool:
            for block in msg.get("message", {}).get("content", []) or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    on_tool(block.get("name", ""), block.get("input", {}) or {})
        elif kind == "result":
            if msg.get("is_error") or msg.get("subtype") != "success":
                error = msg.get("result") or msg.get("terminal_reason") or "unknown error"
            else:
                final = msg.get("result")
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise ClaudeError("Claude timed out")

    text = (final if final is not None else "".join(chunks)).strip()
    if error or (proc.returncode and not text):
        err = error or (proc.stderr.read().strip() if proc.stderr else "") or f"exit code {proc.returncode}"
        if not text or "authenticate" in str(err).lower():
            raise ClaudeError(
                f"Claude request failed: {err}\nIf you are logged out, run `claude` in a terminal and log in."
            )
    if not text:
        # Synthetic/empty reply usually means an auth problem.
        raise ClaudeError("Claude returned nothing. Run `claude` in a terminal to check you are logged in.")
    return text


def ask_json(prompt: str, system: str, model: str = "sonnet", images: Iterable[Path] = (), **kw) -> dict:
    """Ask for a JSON object; tolerant of code fences and prose around it."""
    text = ask(prompt + "\n\nYour final message must be ONLY a JSON object, no prose.", system, model, images, **kw)
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ClaudeError(f"Expected JSON, got: {text[:300]}")
    return json.loads(text[start : end + 1])
