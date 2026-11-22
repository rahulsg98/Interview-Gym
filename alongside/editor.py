"""Code / design workspace: one editor for notes *and* code.

- Pick a language (Notes, Java, Python, C++, JavaScript, …) for syntax colouring.
- In Notes mode you can mix prose with fenced code blocks (```java … ```); each block is coloured in its
  own language, which suits system-design rounds (components, APIs, schema, plus a bit of code).
- Auto-indent on Enter (extra level after { [ ( and after ':' in Python/YAML), Tab / Shift+Tab indent and
  dedent (also for a selection), typing a closing bracket on an empty line dedents it, line numbers.
No compiler: it only recognises code so it reads and edits like code.
"""
from __future__ import annotations

import re

from PySide6.QtCore import QRect, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontDatabase, QPainter, QSyntaxHighlighter, QTextCharFormat,
                           QTextCursor, QTextFormat)
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTextEdit,
                               QVBoxLayout, QWidget)

INDENT = "    "

# ---------------------------------------------------------------- languages
_C_LIKE_COMMON = ("if else for while do switch case default break continue return goto try catch finally throw "
                  "new delete this true false null const static")
LANGUAGES: dict[str, dict] = {
    "Notes": {"tag": "", "kw": "", "types": "", "line": None, "block": None},
    "Java": {"tag": "java", "line": "//", "block": ("/*", "*/"),
             "kw": _C_LIKE_COMMON + " class interface enum extends implements public private protected final "
                   "abstract synchronized volatile transient native package import throws instanceof super var "
                   "record sealed permits yield assert",
             "types": "int long short byte char boolean float double void String Integer Long Boolean Double "
                      "List ArrayList Map HashMap Set HashSet Queue Deque ArrayDeque PriorityQueue Optional "
                      "Object StringBuilder LinkedList TreeMap Stream"},
    "Python": {"tag": "python", "line": "#", "block": ('"""', '"""'), "colon_indent": True,
               "kw": "def class return if elif else for while in not and or is lambda try except finally raise "
                     "with as import from pass break continue yield global nonlocal async await assert del match "
                     "case True False None self",
               "types": "int str float bool list dict set tuple bytes object len range print enumerate zip map "
                        "filter sorted min max sum any all isinstance super"},
    "C++": {"tag": "cpp", "line": "//", "block": ("/*", "*/"),
            "kw": _C_LIKE_COMMON + " class struct public private protected virtual override template typename "
                  "namespace using auto inline friend operator nullptr sizeof constexpr noexcept explicit mutable "
                  "#include #define #pragma",
            "types": "int long short char bool float double void unsigned signed size_t string vector map "
                     "unordered_map set unordered_set pair queue stack deque priority_queue std"},
    "C": {"tag": "c", "line": "//", "block": ("/*", "*/"),
          "kw": _C_LIKE_COMMON + " struct union typedef enum extern sizeof #include #define #ifdef #endif",
          "types": "int long short char float double void unsigned signed size_t FILE NULL"},
    "JavaScript": {"tag": "javascript", "line": "//", "block": ("/*", "*/"), "backtick": True,
                   "kw": _C_LIKE_COMMON + " function let var class extends import export from async await "
                         "yield typeof instanceof of in undefined super",
                   "types": "Array Object Promise Map Set JSON Math console window document Number String"},
    "TypeScript": {"tag": "typescript", "line": "//", "block": ("/*", "*/"), "backtick": True,
                   "kw": _C_LIKE_COMMON + " function let var class extends implements interface type enum "
                         "import export from async await readonly public private protected abstract as keyof "
                         "typeof instanceof of in undefined super declare namespace",
                   "types": "string number boolean any unknown never void Array Record Partial Promise Map Set"},
    "Go": {"tag": "go", "line": "//", "block": ("/*", "*/"),
           "kw": "func package import return if else for range switch case default break continue go defer "
                 "select chan map struct interface type var const fallthrough goto nil true false",
           "types": "int int64 int32 uint string bool byte rune float64 error any make len cap append"},
    "Kotlin": {"tag": "kotlin", "line": "//", "block": ("/*", "*/"),
               "kw": _C_LIKE_COMMON + " fun val var class object interface data sealed open override private "
                     "public internal companion when is in as import package suspend",
               "types": "Int Long String Boolean Double List MutableList Map MutableMap Set Unit Any"},
    "SQL": {"tag": "sql", "line": "--", "block": ("/*", "*/"), "nocase": True,
            "kw": "select from where join inner left right outer full on group by order having limit offset "
                  "insert into values update set delete create table index primary key foreign references "
                  "alter drop distinct as and or not null is in exists between like union all case when then "
                  "else end with over partition window",
            "types": "int integer bigint varchar text boolean timestamp date decimal serial count sum avg min max"},
    "Bash": {"tag": "bash", "line": "#", "block": None,
             "kw": "if then else elif fi for while do done case esac function in return export local echo",
             "types": ""},
    "YAML / JSON": {"tag": "yaml", "line": "#", "block": None, "colon_indent": True,
                    "kw": "true false null yes no", "types": ""},
}
TAG_TO_LANG = {v["tag"]: k for k, v in LANGUAGES.items() if v["tag"]}
TAG_TO_LANG.update({"py": "Python", "js": "JavaScript", "ts": "TypeScript", "c++": "C++", "sh": "Bash",
                    "shell": "Bash", "json": "YAML / JSON", "yml": "YAML / JSON", "kt": "Kotlin", "golang": "Go"})
LANG_NAMES = list(LANGUAGES)

# ---------------------------------------------------------------- colours (matches the app theme)
PALETTE = {
    "keyword": "#c792ea", "type": "#7fd4ff", "string": "#c3e88d", "number": "#f78c6c", "comment": "#6b7489",
    "func": "#82aaff", "decorator": "#ffcb6b", "fence": "#5c6680", "heading": "#ffcb6b", "bullet": "#89ddff",
    "bold": "#eef1f7", "inline": "#f5a97f",
    "bg": "#12141b", "gutter_bg": "#0f1117", "gutter_fg": "#4a5068", "gutter_cur": "#a9b1d6", "line": "#1a1d27",
}


def _fmt(color: str, bold=False, italic=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    if italic:
        f.setFontItalic(True)
    return f


FENCE_RE = re.compile(r"^\s*(```|~~~)\s*([\w+#.-]*)")
_NUM_RE = re.compile(r"\b(0x[0-9a-fA-F]+|\d+(\.\d+)?([eE][+-]?\d+)?)[lLfFdD]?\b")
_FUNC_RE = re.compile(r"\b([A-Za-z_]\w*)\s*(?=\()")
_DECOR_RE = re.compile(r"@\w+")


class Highlighter(QSyntaxHighlighter):
    """Block state: low byte = language index + 1 when inside a fenced block (Notes mode),
    bit 8 = inside a multi-line comment/docstring."""
    IN_BLOCK = 1 << 8

    def __init__(self, doc, language: str = "Notes"):
        super().__init__(doc)
        self.language = language
        self.f = {k: _fmt(v) for k, v in PALETTE.items()}
        self.f["comment"] = _fmt(PALETTE["comment"], italic=True)
        self.f["keyword"] = _fmt(PALETTE["keyword"], bold=True)
        self.f["heading"] = _fmt(PALETTE["heading"], bold=True)
        self.f["bold"] = _fmt(PALETTE["bold"], bold=True)
        self._rules: dict[str, list] = {}

    def set_language(self, language: str):
        self.language = language if language in LANGUAGES else "Notes"
        self.rehighlight()

    def _lang_rules(self, name: str):
        if name not in self._rules:
            spec = LANGUAGES[name]
            flags = re.I if spec.get("nocase") else 0
            kws = [re.escape(k) for k in spec["kw"].split()]
            tys = [re.escape(k) for k in spec["types"].split()]
            kw_re = re.compile(r"(?<![\w#])(" + "|".join(kws) + r")\b", flags) if kws else None
            ty_re = re.compile(r"\b(" + "|".join(tys) + r")\b", flags) if tys else None
            self._rules[name] = (kw_re, ty_re)
        return self._rules[name]

    # ---------------------------------------------------------------- main entry
    def highlightBlock(self, text: str):
        prev = self.previousBlockState()
        prev = 0 if prev < 0 else prev
        if self.language != "Notes":
            self.setCurrentBlockState(self._code(text, self.language, bool(prev & self.IN_BLOCK)))
            return
        fence_lang = prev & 0xFF
        m = FENCE_RE.match(text)
        if m:
            self.setFormat(0, len(text), self.f["fence"])
            if fence_lang:  # closing fence
                self.setCurrentBlockState(0)
            else:
                name = TAG_TO_LANG.get(m.group(2).lower(), "Notes") if m.group(2) else "Notes"
                self.setCurrentBlockState(LANG_NAMES.index(name) + 1 if name != "Notes" else 0xFF)
            return
        if fence_lang:
            if fence_lang == 0xFF:  # untagged block: plain monospace text
                self.setCurrentBlockState(fence_lang)
                return
            name = LANG_NAMES[fence_lang - 1]
            in_block = self._code(text, name, bool(prev & self.IN_BLOCK))
            self.setCurrentBlockState(fence_lang | in_block)
            return
        self._notes(text)
        self.setCurrentBlockState(0)

    # ---------------------------------------------------------------- notes / markdown-ish
    def _notes(self, text: str):
        s = text.lstrip()
        if s.startswith("#"):
            self.setFormat(0, len(text), self.f["heading"])
            return
        m = re.match(r"^(\s*)([-*+]|\d+[.)])\s", text)
        if m:
            self.setFormat(m.start(2), len(m.group(2)), self.f["bullet"])
        for m in re.finditer(r"\*\*[^*]+\*\*", text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["bold"])
        for m in re.finditer(r"`[^`]+`", text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["inline"])
        for m in re.finditer(r"(-+>|<-+|=>|→|←|↔)", text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["keyword"])
        for m in _NUM_RE.finditer(text):
            self.setFormat(m.start(), m.end() - m.start(), self.f["number"])

    # ---------------------------------------------------------------- code
    def _code(self, text: str, name: str, in_block: bool) -> int:
        spec = LANGUAGES[name]
        kw_re, ty_re = self._lang_rules(name)
        n = len(text)
        block = spec.get("block")
        start = 0
        if in_block and block:
            end = text.find(block[1])
            if end < 0:
                self.setFormat(0, n, self.f["string" if block[0] == '"""' else "comment"])
                return self.IN_BLOCK
            start = end + len(block[1])
            self.setFormat(0, start, self.f["string" if block[0] == '"""' else "comment"])
        for m in _FUNC_RE.finditer(text, start):
            self.setFormat(m.start(1), len(m.group(1)), self.f["func"])
        if ty_re:
            for m in ty_re.finditer(text, start):
                self.setFormat(m.start(), m.end() - m.start(), self.f["type"])
        if name in ("Java", "Kotlin", "C++", "TypeScript", "Go"):
            for m in re.finditer(r"\b[A-Z][A-Za-z0-9_]*\b", text[start:]):
                self.setFormat(start + m.start(), m.end() - m.start(), self.f["type"])
        if kw_re:
            for m in kw_re.finditer(text, start):
                self.setFormat(m.start(), m.end() - m.start(), self.f["keyword"])
        for m in _NUM_RE.finditer(text, start):
            self.setFormat(m.start(), m.end() - m.start(), self.f["number"])
        if name in ("Java", "Python", "Kotlin", "TypeScript"):
            for m in _DECOR_RE.finditer(text, start):
                self.setFormat(m.start(), m.end() - m.start(), self.f["decorator"])
        if name == "YAML / JSON":
            for m in re.finditer(r'^\s*-?\s*("?[\w.-]+"?)\s*:', text):
                self.setFormat(m.start(1), len(m.group(1)), self.f["type"])
        # strings and comments last (they win), scanning left to right so quotes inside comments are ignored
        quotes = "\"'" + ("`" if spec.get("backtick") else "")
        line = spec.get("line")
        i = start
        while i < n:
            if block and text.startswith(block[0], i):
                end = text.find(block[1], i + len(block[0]))
                fmt = self.f["string" if block[0] == '"""' else "comment"]
                if end < 0:
                    self.setFormat(i, n - i, fmt)
                    return self.IN_BLOCK
                self.setFormat(i, end + len(block[1]) - i, fmt)
                i = end + len(block[1])
                continue
            if line and text.startswith(line, i) and not (line == "#" and name == "C++"):
                self.setFormat(i, n - i, self.f["comment"])
                break
            ch = text[i]
            if ch in quotes:
                j = i + 1
                while j < n and text[j] != ch:
                    j += 2 if text[j] == "\\" else 1
                self.setFormat(i, min(j + 1, n) - i, self.f["string"])
                i = j + 1
                continue
            i += 1
        return 0


# ---------------------------------------------------------------- editor
class _Gutter(QWidget):
    def __init__(self, editor: "CodeEditor"):
        super().__init__(editor)
        self.editor = editor

    def sizeHint(self):
        return QSize(self.editor.gutter_width(), 0)

    def paintEvent(self, event):
        self.editor.paint_gutter(event)


class CodeEditor(QPlainTextEdit):
    """QPlainTextEdit with line numbers, syntax colouring and IDE-like indentation."""
    def __init__(self, language: str = "Notes", parent=None):
        super().__init__(parent)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(12)
        self.setFont(mono)
        self.setTabStopDistance(4 * self.fontMetrics().horizontalAdvance(" "))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setObjectName("codeEditor")
        self.highlighter = Highlighter(self.document(), language)
        self._gutter = _Gutter(self)
        self.blockCountChanged.connect(lambda _: self._update_margins())
        self.updateRequest.connect(self._on_update_request)
        self.cursorPositionChanged.connect(self._highlight_line)
        self._update_margins()
        self._highlight_line()

    # ---- language
    @property
    def language(self) -> str:
        return self.highlighter.language

    def set_language(self, name: str):
        self.highlighter.set_language(name)
        self.setLineWrapMode(QPlainTextEdit.WidgetWidth if name == "Notes" else QPlainTextEdit.NoWrap)

    def language_at_cursor(self) -> str:
        if self.language != "Notes":
            return self.language
        state = self.textCursor().block().previous().userState()
        idx = (state & 0xFF) if state > 0 else 0
        return LANG_NAMES[idx - 1] if 0 < idx <= len(LANG_NAMES) else "Notes"

    def insert_code_block(self, lang: str):
        tag = LANGUAGES.get(lang, {}).get("tag", "")
        c = self.textCursor()
        c.beginEditBlock()
        if c.positionInBlock() > 0:
            c.movePosition(QTextCursor.EndOfBlock)
            c.insertText("\n")
        c.insertText(f"```{tag}\n")
        pos = c.position()
        c.insertText("\n```\n")
        c.setPosition(pos)
        c.endEditBlock()
        self.setTextCursor(c)
        self.setFocus()

    # ---- gutter
    def gutter_width(self) -> int:
        digits = max(2, len(str(self.blockCount())))
        return 14 + self.fontMetrics().horizontalAdvance("9") * digits

    def _update_margins(self):
        self.setViewportMargins(self.gutter_width(), 0, 0, 0)

    def _on_update_request(self, rect, dy):
        if dy:
            self._gutter.scroll(0, dy)
        else:
            self._gutter.update(0, rect.y(), self._gutter.width(), rect.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cr = self.contentsRect()
        self._gutter.setGeometry(QRect(cr.left(), cr.top(), self.gutter_width(), cr.height()))

    def paint_gutter(self, event):
        p = QPainter(self._gutter)
        p.fillRect(event.rect(), QColor(PALETTE["gutter_bg"]))
        block = self.firstVisibleBlock()
        num = block.blockNumber()
        top = round(self.blockBoundingGeometry(block).translated(self.contentOffset()).top())
        bottom = top + round(self.blockBoundingRect(block).height())
        cur = self.textCursor().blockNumber()
        h = self.fontMetrics().height()
        while block.isValid() and top <= event.rect().bottom():
            if block.isVisible() and bottom >= event.rect().top():
                p.setPen(QColor(PALETTE["gutter_cur"] if num == cur else PALETTE["gutter_fg"]))
                p.drawText(0, top, self._gutter.width() - 8, h, Qt.AlignRight, str(num + 1))
            block = block.next()
            top = bottom
            bottom = top + round(self.blockBoundingRect(block).height())
            num += 1

    def _highlight_line(self):
        sel = QTextEdit.ExtraSelection()
        sel.format.setBackground(QColor(PALETTE["line"]))
        sel.format.setProperty(QTextFormat.FullWidthSelection, True)
        sel.cursor = self.textCursor()
        sel.cursor.clearSelection()
        self.setExtraSelections([sel])
        self._gutter.update()

    # ---- indentation
    def keyPressEvent(self, e):
        key, mods = e.key(), e.modifiers()
        ctrl = bool(mods & (Qt.ControlModifier | Qt.MetaModifier))
        c = self.textCursor()
        if key in (Qt.Key_Return, Qt.Key_Enter) and not ctrl and not (mods & Qt.ShiftModifier):
            self._newline(c)
            return
        if key == Qt.Key_Tab and not ctrl:
            self._indent(c, dedent=False)
            return
        if key == Qt.Key_Backtab:
            self._indent(c, dedent=True)
            return
        if key == Qt.Key_Backspace and not c.hasSelection() and not ctrl:
            before = c.block().text()[: c.positionInBlock()]
            if before and not before.strip() and len(before) % 4 == 0:
                c.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, 4)
                c.removeSelectedText()
                return
        txt = e.text()
        lang = self.language_at_cursor()
        if txt and lang != "Notes" and not ctrl:
            if txt in "}])":
                line = c.block().text()
                if not line.strip() and c.positionInBlock() == len(line) and len(line) >= 4:
                    c.movePosition(QTextCursor.Left, QTextCursor.KeepAnchor, 4)
                    c.removeSelectedText()
        super().keyPressEvent(e)

    @staticmethod
    def _next_char(c: QTextCursor) -> str:
        line = c.block().text()
        i = c.positionInBlock()
        return line[i] if i < len(line) else ""

    def _newline(self, c: QTextCursor):
        line = c.block().text()
        before = line[: c.positionInBlock()]
        indent = re.match(r"[ \t]*", line).group(0)
        lang = self.language_at_cursor()
        stripped = before.rstrip()
        extra = ""
        if lang != "Notes" and stripped:
            if stripped[-1] in "{[(" or (LANGUAGES[lang].get("colon_indent") and stripped.endswith(":")):
                extra = INDENT
        elif lang == "Notes":
            m = re.match(r"^(\s*)([-*+])\s+\S", line)  # keep bullet lists going
            if m and c.positionInBlock() == len(line):
                extra = m.group(2) + " "
            elif re.match(r"^\s*[-*+]\s*$", line):  # empty bullet: end the list
                c.movePosition(QTextCursor.StartOfBlock, QTextCursor.KeepAnchor)
                c.removeSelectedText()
                c.insertText("\n")
                self.setTextCursor(c)
                return
        c.beginEditBlock()
        nxt = self._next_char(c)
        c.insertText("\n" + indent + extra)
        openers = {")": "(", "]": "[", "}": "{"}
        if extra == INDENT and nxt in openers and stripped[-1:] == openers[nxt]:
            # {|} -> brace on its own line below, cursor indented in between
            pos = c.position()
            c.insertText("\n" + indent)
            c.setPosition(pos)
        c.endEditBlock()
        self.setTextCursor(c)
        self.ensureCursorVisible()

    def _indent(self, c: QTextCursor, dedent: bool):
        if not c.hasSelection() and not dedent:
            col = c.positionInBlock()
            c.insertText(" " * (4 - col % 4))
            return
        start, end = sorted((c.selectionStart(), c.selectionEnd())) if c.hasSelection() else (c.position(),) * 2
        doc = self.document()
        first, last = doc.findBlock(start), doc.findBlock(end)
        if c.hasSelection() and end == last.position() and last != first:
            last = last.previous()
        c.beginEditBlock()
        block = first
        while True:
            bc = QTextCursor(block)
            if dedent:
                text = block.text()
                n = len(text) - len(text.lstrip(" "))
                n = min(4, n) if n else (1 if text.startswith("\t") else 0)
                if n:
                    bc.movePosition(QTextCursor.Right, QTextCursor.KeepAnchor, n)
                    bc.removeSelectedText()
            else:
                bc.insertText(INDENT)
            if block == last:
                break
            block = block.next()
        c.endEditBlock()


class Workspace(QWidget):
    """Toolbar (title, language, insert code block) + CodeEditor."""
    language_changed = Signal(str)

    def __init__(self, title: str = "Workspace", language: str = "Notes", parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        bar = QHBoxLayout()
        self.title = QLabel(title)
        self.title.setObjectName("paneTitle")
        bar.addWidget(self.title)
        bar.addStretch()
        bar.addWidget(QLabel("Language"))
        self.lang = QComboBox()
        self.lang.addItems(LANG_NAMES)
        self.lang.setToolTip("Colours and indents the workspace as this language. "
                             "'Notes' lets you mix text with ``` code blocks.")
        bar.addWidget(self.lang)
        self.block_btn = QPushButton("{ }  Code block")
        self.block_btn.setToolTip("Insert a fenced code block in the chosen code language")
        bar.addWidget(self.block_btn)
        v.addLayout(bar)
        self.editor = CodeEditor(language)
        v.addWidget(self.editor, 1)
        self.code_lang = "Java"  # language for inserted code blocks
        self.lang.setCurrentText(language)
        self.lang.currentTextChanged.connect(self._on_lang)
        self.block_btn.clicked.connect(lambda: self.editor.insert_code_block(self.code_lang))

    def _on_lang(self, name: str):
        if name != "Notes":
            self.code_lang = name
        self.editor.set_language(name)
        self.language_changed.emit(name)

    def set_language(self, name: str):
        if name in LANGUAGES:
            self.lang.setCurrentText(name)
