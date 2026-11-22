"""Rich reading view for feedback, reports, history and learnings.

Markdown (from Claude) is rendered to styled HTML inside a Qt WebEngine view:
cards, score badges, chips, coloured callouts (> [!TIP] / [!WARNING] / [!NOTE] / [!KEY] / [!MISTAKE]),
tables, Pygments-coloured code blocks, collapsible sections, and Mermaid diagrams (```mermaid).
Mermaid is downloaded once into the models folder; without it diagrams show as code.
Falls back to a plain QTextBrowser if WebEngine isn't available.
"""
from __future__ import annotations

import html as _html
import json
import re
import threading

from PySide6.QtCore import QTimer, QUrl
from PySide6.QtGui import QDesktopServices

from .config import MODELS_DIR

WEB_DIR = MODELS_DIR / "web"
MERMAID_JS = WEB_DIR / "mermaid.min.js"
MERMAID_URL = "https://cdn.jsdelivr.net/npm/mermaid@10.9.1/dist/mermaid.min.js"

try:  # must be imported before the QApplication exists
    from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineSettings
    from PySide6.QtWebEngineWidgets import QWebEngineView
    HAVE_WEB = True
except Exception:  # noqa: BLE001
    HAVE_WEB = False


_MERMAID_LOCK = threading.Lock()
_MERMAID_STARTED = False


def _mermaid_ok() -> bool:
    try:
        return MERMAID_JS.stat().st_size > 1_000_000 and MERMAID_JS.read_bytes()[-400:].rstrip().endswith((b")", b";", b"}"))
    except OSError:
        return False


def ensure_mermaid() -> None:
    """Download Mermaid once (all views share it; safe to call from many threads)."""
    with _MERMAID_LOCK:
        if _mermaid_ok():
            return
        try:
            import urllib.request
            WEB_DIR.mkdir(parents=True, exist_ok=True)
            tmp = MERMAID_JS.with_suffix(f".{threading.get_ident()}.part")
            urllib.request.urlretrieve(MERMAID_URL, tmp)
            if tmp.stat().st_size > 1_000_000:
                tmp.replace(MERMAID_JS)
            else:
                tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _start_mermaid_download() -> None:
    global _MERMAID_STARTED
    if _MERMAID_STARTED or _mermaid_ok():
        return
    _MERMAID_STARTED = True
    MERMAID_JS.unlink(missing_ok=True)  # drop a broken copy
    threading.Thread(target=ensure_mermaid, daemon=True).start()


# ------------------------------------------------------------------ markdown → html
_md = None


def _highlight(code: str, lang: str, _attrs) -> str:
    lang = (lang or "").strip().lower()
    if lang == "mermaid":
        return f'<pre class="mermaid">{_html.escape(code)}</pre>'
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import get_lexer_by_name, guess_lexer
        from pygments.util import ClassNotFound
        try:
            lexer = get_lexer_by_name({"c++": "cpp", "js": "javascript", "ts": "typescript", "sh": "bash",
                                       "yml": "yaml", "golang": "go"}.get(lang, lang)) if lang else guess_lexer(code)
        except ClassNotFound:
            lexer = get_lexer_by_name("text")
        body = highlight(code, lexer, HtmlFormatter(nowrap=True))
    except Exception:  # noqa: BLE001
        body = _html.escape(code)
    label = f'<span class="lang">{_html.escape(lang)}</span>' if lang and lang != "text" else ""
    return f'<div class="code">{label}<pre class="hl"><code>{body}</code></pre></div>'


def _parser():
    global _md
    if _md is None:
        from markdown_it import MarkdownIt
        _md = MarkdownIt("commonmark", {"html": True, "highlight": _highlight, "breaks": False}) \
            .enable(["table", "strikethrough"])
        try:
            from mdit_py_plugins.tasklists import tasklists_plugin
            _md.use(tasklists_plugin)
        except Exception:  # noqa: BLE001
            pass
    return _md


CALLOUTS = {
    "tip": ("💡", "Tip"), "note": ("📝", "Note"), "warning": ("⚠️", "Watch out"), "key": ("🎯", "Key point"),
    "mistake": ("❌", "Common mistake"), "important": ("❗", "Important"), "example": ("🧪", "Example"),
}


def md(text: str) -> str:
    """Markdown → HTML with highlighted code, Mermaid diagrams and callouts."""
    if not text:
        return ""
    try:
        out = _parser().render(text)
    except Exception:  # noqa: BLE001
        return f"<p>{_html.escape(text)}</p>"
    # The highlight hook output is wrapped in <pre><code>; unwrap ours.
    out = re.sub(r'<pre><code[^>]*>(<(?:div class="code"|pre class="mermaid")[\s\S]*?)</code></pre>', r"\1", out)

    def callout(m):
        kind = m.group(1).lower()
        icon, title = CALLOUTS.get(kind, ("💬", kind.title()))
        body = m.group(2).strip()
        return f'<div class="callout {kind}"><div class="ct">{icon} {title}</div><p>{body}</div>'
    return re.sub(r"<blockquote>\s*<p>\[!(\w+)\]\s*([\s\S]*?)</blockquote>", callout, out)


def esc(text) -> str:
    return _html.escape(str(text or "")).replace("\n", "<br>")


# ------------------------------------------------------------------ small building blocks
def score_class(score) -> str:
    if not isinstance(score, (int, float)):
        return "na"
    return "good" if score >= 7.5 else "mid" if score >= 6 else "bad"


def badge(score, suffix="/10") -> str:
    txt = f"{score}{suffix}" if isinstance(score, (int, float)) else "–"
    return f'<span class="badge {score_class(score)}">{txt}</span>'


def chip(text, kind="") -> str:
    return f'<span class="chip {kind}">{esc(text)}</span>'


def bullet_list(items, kind="") -> str:
    lis = "".join(f"<li>{md(str(x)).removeprefix('<p>').removesuffix(chr(10)).removesuffix('</p>')}</li>"
                  for x in items if x)
    return f'<ul class="{kind}">{lis}</ul>' if lis else ""


def meter(label, value, maxv=10) -> str:
    v = value if isinstance(value, (int, float)) else 0
    pct = max(0, min(100, v / maxv * 100))
    return (f'<div class="meter"><span class="ml">{esc(label)}</span><span class="bar"><i class="{score_class(v)}" '
            f'style="width:{pct:.0f}%"></i></span><b>{value if isinstance(value, (int, float)) else "–"}</b></div>')


def section(title, body, icon="", cls="") -> str:
    if not body:
        return ""
    return f'<div class="sec {cls}"><h4>{icon + " " if icon else ""}{esc(title)}</h4>{body}</div>'


def details(summary, body, open_=False) -> str:
    if not body:
        return ""
    return f'<details{" open" if open_ else ""}><summary>{summary}</summary><div class="dbody">{body}</div></details>'


def card(header, body, anchor="", cls="") -> str:
    a = f' id="{anchor}"' if anchor else ""
    return f'<div class="card {cls}"{a}><div class="ch">{header}</div>{body}</div>'


# ------------------------------------------------------------------ page
CSS = """
:root { color-scheme: dark; }
* { box-sizing: border-box; }
html, body { margin:0; background:#0f121b; color:#dfe3ef; }
body { font: 15.5px/1.65 "Inter","Noto Sans","Ubuntu",system-ui,sans-serif; padding: 18px 22px 40px; }
#c { max-width: 1100px; margin: 0 auto; }
h1,h2,h3,h4 { color:#f3f5fb; line-height:1.3; }
h1 { font-size: 26px; margin: 6px 0 14px; }
h2 { font-size: 21px; margin: 26px 0 10px; padding-bottom: 6px; border-bottom: 2px solid;
     border-image: linear-gradient(90deg,#8b5cf6,#22d3ee 40%,transparent 70%) 1; }
h3 { font-size: 17.5px; margin: 20px 0 8px; color:#c4b5fd; }
h4 { font-size: 15px; margin: 0 0 8px; color:#e9ecf5; letter-spacing:.2px; }
p { margin: 6px 0 10px; }
a { color:#67e8f9; text-decoration:none; border-bottom:1px dashed #2b6b78; }
a:hover { color:#a5f3fc; border-bottom-color:#a5f3fc; }
strong, b { color:#ffffff; }
em { color:#c3c8da; }
hr { border:none; height:1px; background:#222840; margin:22px 0; }
ul, ol { padding-left: 22px; margin: 6px 0 10px; }
li { margin: 4px 0; }
li::marker { color:#8b5cf6; }
ul.good li::marker { content:"✓  "; color:#34d399; }
ul.bad li::marker { content:"✗  "; color:#fb7185; }
ul.warn li::marker { content:"!  "; color:#fbbf24; font-weight:700; }
ul.check li::marker { content:"◆  "; color:#22d3ee; }
blockquote { margin:10px 0; padding:10px 16px; border-left:3px solid #8b5cf6; background:#151a2a; border-radius:0 10px 10px 0; color:#d6daea; }
code { font: 13.5px/1.5 "JetBrains Mono","Fira Code","DejaVu Sans Mono",monospace; background:#1c2133; color:#f5a97f;
       padding:1px 6px; border-radius:6px; }
.code { position:relative; margin:10px 0 14px; }
.code .lang { position:absolute; top:6px; right:10px; font-size:11px; color:#8b93ab; text-transform:uppercase; letter-spacing:1px; }
pre.hl { margin:0; background:#0b0d14; border:1px solid #232a40; border-radius:12px; padding:14px 16px; overflow-x:auto; }
pre.hl code { background:none; color:#d4d8e6; padding:0; font-size:13.5px; }
pre.mermaid { background:#111526; border:1px solid #2a2f52; border-radius:12px; padding:16px; text-align:center; margin:12px 0;
              color:#8b93ab; white-space:pre-wrap; font-size:12px; }
pre.mermaid[data-processed] { color:inherit; font-size:inherit; }
table { border-collapse: separate; border-spacing:0; width:100%; margin:10px 0 14px; border:1px solid #252b3d; border-radius:10px; overflow:hidden; }
th { background:#1a1f30; color:#c4b5fd; text-align:left; padding:8px 12px; font-weight:600; }
td { padding:8px 12px; border-top:1px solid #1f2436; vertical-align:top; }
tr:nth-child(even) td { background:#131726; }
.card { background:#141826; border:1px solid #222840; border-radius:16px; padding:16px 20px 12px; margin:0 0 18px;
        box-shadow: 0 6px 24px rgba(0,0,0,.25); }
.card .ch { display:flex; align-items:center; gap:10px; flex-wrap:wrap; margin-bottom:10px; }
.card .ch .title { font-size:18px; font-weight:700; color:#f3f5fb; flex:1; min-width:200px; }
.card .ch .sub { color:#8b93ab; font-size:13px; }
.q { background:linear-gradient(90deg,rgba(139,92,246,.14),rgba(34,211,238,.06)); border:1px solid #2d2a5a;
     border-radius:12px; padding:12px 16px; margin:4px 0 12px; color:#eef0f8; font-size:16px; }
.verdict { color:#c3c8da; font-style:italic; margin:0 0 10px; }
.badge { display:inline-block; min-width:58px; text-align:center; padding:4px 12px; border-radius:999px; font-weight:800; font-size:15px; }
.badge.good { background:rgba(52,211,153,.15); color:#34d399; border:1px solid rgba(52,211,153,.4); }
.badge.mid  { background:rgba(251,191,36,.13); color:#fbbf24; border:1px solid rgba(251,191,36,.4); }
.badge.bad  { background:rgba(251,113,133,.13); color:#fb7185; border:1px solid rgba(251,113,133,.4); }
.badge.na   { background:#1e2333; color:#8b93ab; border:1px solid #333b55; }
.badge.big { font-size:28px; padding:8px 20px; }
.chip { display:inline-block; padding:3px 10px; margin:2px 6px 2px 0; border-radius:999px; font-size:12.5px;
        background:#1e2333; color:#c3c8da; border:1px solid #2f3650; }
.chip.good { background:rgba(52,211,153,.12); color:#6ee7b7; border-color:rgba(52,211,153,.35); }
.chip.bad { background:rgba(251,113,133,.12); color:#fda4af; border-color:rgba(251,113,133,.35); }
.chip.warn { background:rgba(251,191,36,.12); color:#fcd34d; border-color:rgba(251,191,36,.35); }
.chip.info { background:rgba(139,92,246,.14); color:#c4b5fd; border-color:rgba(139,92,246,.4); }
.chip.cyan { background:rgba(34,211,238,.1); color:#67e8f9; border-color:rgba(34,211,238,.35); }
.grid2 { display:grid; grid-template-columns: 1fr 1fr; gap:14px; }
@media (max-width: 820px) { .grid2 { grid-template-columns: 1fr; } }
.sec { background:#11151f; border:1px solid #1f2436; border-radius:12px; padding:12px 16px 6px; margin:10px 0; }
.sec.good { border-left:3px solid #34d399; }
.sec.bad { border-left:3px solid #fb7185; }
.sec.warn { border-left:3px solid #fbbf24; }
.sec.info { border-left:3px solid #8b5cf6; }
.sec.cyan { border-left:3px solid #22d3ee; }
.callout { border-radius:12px; padding:10px 16px 4px; margin:12px 0; border:1px solid; }
.callout .ct { font-weight:700; margin-bottom:2px; }
.callout.tip, .callout.example { background:rgba(34,211,238,.07); border-color:rgba(34,211,238,.35); }
.callout.tip .ct, .callout.example .ct { color:#67e8f9; }
.callout.note { background:rgba(139,92,246,.08); border-color:rgba(139,92,246,.35); } .callout.note .ct { color:#c4b5fd; }
.callout.key { background:rgba(52,211,153,.07); border-color:rgba(52,211,153,.35); } .callout.key .ct { color:#6ee7b7; }
.callout.warning, .callout.important { background:rgba(251,191,36,.07); border-color:rgba(251,191,36,.35); }
.callout.warning .ct, .callout.important .ct { color:#fcd34d; }
.callout.mistake { background:rgba(251,113,133,.07); border-color:rgba(251,113,133,.35); } .callout.mistake .ct { color:#fda4af; }
details { background:#11151f; border:1px solid #232a40; border-radius:12px; margin:10px 0; }
details > summary { cursor:pointer; padding:10px 16px; font-weight:600; color:#e9ecf5; list-style:none; }
details > summary::before { content:"▸"; color:#8b5cf6; margin-right:8px; display:inline-block; transition:transform .15s; }
details[open] > summary::before { transform: rotate(90deg); }
details > .dbody { padding: 0 16px 8px; border-top:1px solid #1f2436; }
.meter { display:flex; align-items:center; gap:10px; margin:5px 0; font-size:13.5px; }
.meter .ml { width:120px; color:#c3c8da; }
.meter .bar { flex:1; height:8px; background:#1e2333; border-radius:6px; overflow:hidden; }
.meter .bar i { display:block; height:100%; border-radius:6px; }
.meter .bar i.good { background:linear-gradient(90deg,#10b981,#34d399); }
.meter .bar i.mid { background:linear-gradient(90deg,#f59e0b,#fbbf24); }
.meter .bar i.bad { background:linear-gradient(90deg,#e11d48,#fb7185); }
.meter b { width:26px; text-align:right; color:#e9ecf5; }
.toc { display:flex; flex-wrap:wrap; gap:6px; margin:0 0 16px; }
.toc a { border:1px solid #2f3650; background:#161a26; padding:4px 12px; border-radius:999px; color:#c3c8da; font-size:13px; }
.toc a:hover { border-color:#8b5cf6; color:#fff; }
.hero { display:flex; align-items:center; gap:18px; padding:16px 20px; border-radius:16px; margin-bottom:18px;
        background:linear-gradient(120deg,rgba(124,58,237,.22),rgba(8,145,178,.14)); border:1px solid #2d2a5a; }
.hero .t { font-size:20px; font-weight:800; color:#fff; } .hero .s { color:#c3c8da; }
.res { display:flex; gap:12px; align-items:flex-start; padding:10px 12px; border-radius:12px; background:#131726; border:1px solid #232a40; margin:8px 0; }
.res .ri { font-size:20px; } .res .rt { font-weight:600; } .res .rw { color:#8b93ab; font-size:13.5px; }
.chat { display:flex; flex-direction:column; gap:10px; }
.bubble { max-width:82%; padding:10px 14px; border-radius:14px; line-height:1.55; }
.bubble .who { font-size:12px; font-weight:700; margin-bottom:3px; }
.bubble.arjun { align-self:flex-start; background:#1a1736; border:1px solid #2f2a66; border-top-left-radius:4px; }
.bubble.arjun .who { color:#a78bfa; }
.bubble.you { align-self:flex-end; background:#0f2a2e; border:1px solid #1d4a50; border-top-right-radius:4px; }
.bubble.you .who { color:#5eead4; text-align:right; }
.bubble.qb { align-self:stretch; max-width:100%; background:linear-gradient(90deg,rgba(139,92,246,.16),rgba(34,211,238,.06));
             border:1px solid #2d2a5a; font-size:16px; }
.bubble .tag { color:#8b93ab; font-weight:500; }
.muted { color:#8b93ab; } .small { font-size:13px; }
.empty { color:#8b93ab; text-align:center; padding:40px; font-style:italic; }
::-webkit-scrollbar { width:10px; height:10px; } ::-webkit-scrollbar-thumb { background:#2a3148; border-radius:6px; }
::-webkit-scrollbar-track { background:transparent; }
"""


def _pygments_css() -> str:
    try:
        from pygments.formatters import HtmlFormatter
        for style in ("one-dark", "dracula", "monokai"):
            try:
                return HtmlFormatter(style=style).get_style_defs("pre.hl")
            except Exception:  # noqa: BLE001
                continue
    except Exception:  # noqa: BLE001
        pass
    return ""


def template() -> str:
    mermaid = '<script src="mermaid.min.js"></script>' if _mermaid_ok() else ""
    return f"""<!doctype html><html><head><meta charset="utf-8">
<style>{CSS}{_pygments_css()} pre.hl {{ background:#0b0d14 !important; }}</style>{mermaid}
<script>
if (window.mermaid) mermaid.initialize({{ startOnLoad:false, theme:'dark', securityLevel:'loose',
  fontFamily:'Inter, Noto Sans, sans-serif',
  themeVariables:{{ primaryColor:'#2d2160', primaryTextColor:'#eef0f8', primaryBorderColor:'#8b5cf6',
    lineColor:'#22d3ee', secondaryColor:'#12394a', tertiaryColor:'#161a26', background:'#111526',
    mainBkg:'#2d2160', nodeBorder:'#8b5cf6', clusterBkg:'#141826', clusterBorder:'#333b55',
    edgeLabelBackground:'#141826', fontSize:'14px' }} }});
window.render = function(html, mode) {{
  var y = window.scrollY;
  var atBottom = (window.innerHeight + window.scrollY) >= document.body.scrollHeight - 40;
  document.getElementById('c').innerHTML = html;
  if (window.mermaid) {{ try {{ mermaid.run({{ querySelector:'#c pre.mermaid', suppressErrors:true }}); }} catch(e) {{}} }}
  if (mode === 'top') window.scrollTo(0, 0);
  else if (mode === 'follow' && atBottom) window.scrollTo(0, document.body.scrollHeight);
  else window.scrollTo(0, y);
}};
window.jump = function(id) {{ var e = document.getElementById(id); if (e) e.scrollIntoView({{behavior:'smooth'}}); }};
</script></head><body><div id="c"></div></body></html>"""


# ------------------------------------------------------------------ widget
if HAVE_WEB:
    class _Page(QWebEnginePage):
        def acceptNavigationRequest(self, url, nav_type, is_main):  # noqa: N802
            if nav_type == QWebEnginePage.NavigationType.NavigationTypeLinkClicked:
                if url.scheme() in ("http", "https", "mailto"):
                    QDesktopServices.openUrl(url)  # open in the normal browser
                return False
            return super().acceptNavigationRequest(url, nav_type, is_main)

    class RichView(QWebEngineView):
        """Drop-in replacement for the read-only QTextBrowsers: setMarkdown(md) / setHtml(html) / clear()."""

        def __init__(self, parent=None):
            super().__init__(parent)
            self.setPage(_Page(self))
            self.page().setBackgroundColor(Qt_dark())
            s = self.settings()
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
            s.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)
            self._ready = False
            self._pending: tuple[str, str] | None = None
            self._last = ""
            self._timer = QTimer(self, singleShot=True, interval=200, timeout=self._flush)
            self.loadFinished.connect(self._on_loaded)
            WEB_DIR.mkdir(parents=True, exist_ok=True)
            super().setHtml(template(), QUrl.fromLocalFile(str(WEB_DIR) + "/"))
            _start_mermaid_download()

        def _on_loaded(self, ok: bool):
            self._ready = True
            self._flush()

        def set_html(self, body: str, scroll: str = "keep"):
            """scroll: 'top' (new content), 'keep' (refresh in place), 'follow' (streaming: stick to the bottom)."""
            if body == self._last and scroll != "top":
                return
            self._last = body
            self._pending = (body, scroll)
            if not self._timer.isActive():
                self._timer.start(0 if scroll == "top" else 200)

        def _flush(self):
            if not self._ready or not self._pending:
                return
            body, scroll = self._pending
            self._pending = None
            self.page().runJavaScript(f"window.render({json.dumps(body)}, {json.dumps(scroll)});")

        # QTextBrowser-compatible API
        def setMarkdown(self, text: str, scroll: str = "follow"):  # noqa: N802
            self.set_html(md(text) if text.strip() else "", scroll)

        def setHtml(self, body: str, scroll: str = "top"):  # noqa: N802
            self.set_html(body, scroll)

        def clear(self):
            self.set_html("", "top")
else:
    from PySide6.QtWidgets import QTextBrowser

    class RichView(QTextBrowser):  # type: ignore[no-redef]
        def __init__(self, parent=None):
            super().__init__(parent)
            self.setOpenExternalLinks(True)

        def set_html(self, body: str, scroll: str = "keep"):
            sb = self.verticalScrollBar()
            pos = sb.value()
            super().setHtml(body)
            if scroll == "keep":
                sb.setValue(pos)

        def setMarkdown(self, text: str, scroll: str = "follow"):  # noqa: N802
            self.set_html(md(text), scroll)

        def setHtml(self, body: str, scroll: str = "top"):  # noqa: N802
            self.set_html(body, scroll)


def Qt_dark():  # noqa: N802
    from PySide6.QtGui import QColor
    return QColor("#0f121b")
