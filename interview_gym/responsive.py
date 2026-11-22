"""Small helpers so panels reflow instead of clipping when they get narrow.

- reflow(layout): a row of widgets that stacks vertically when it no longer fits side by side.
- make_responsive(root): dropdowns can shrink (long text is elided) and form labels move above their
  fields when a row is too narrow.
"""
from __future__ import annotations

from PySide6.QtWidgets import QBoxLayout, QComboBox, QFormLayout, QLayout, QLineEdit, QSizePolicy, QWidget


class ReflowRow(QWidget):
    """Horizontal row that switches to a vertical stack when there isn't room for its widgets."""

    def __init__(self, layout: QBoxLayout, parent=None):
        super().__init__(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        # Don't let the row force its minimum width to "everything side by side"; it stacks instead.
        layout.setSizeConstraint(QLayout.SetNoConstraint)
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

    def _needed(self) -> int:
        lay: QBoxLayout = self.layout()
        widths = []
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None and not w.isHidden():
                widths.append(max(w.minimumSizeHint().width(), min(w.sizeHint().width(), 90)))
        return sum(widths) + lay.spacing() * max(0, len(widths) - 1)

    def minimumSizeHint(self):  # noqa: N802
        size = super().minimumSizeHint()
        lay: QBoxLayout = self.layout()
        widest = 0
        for i in range(lay.count()):
            w = lay.itemAt(i).widget()
            if w is not None and not w.isHidden():
                widest = max(widest, w.minimumSizeHint().width())
        size.setWidth(widest)  # never force the panel wider than the widest single item
        return size

    def minimumSize(self):  # noqa: N802
        return self.minimumSizeHint()

    def resizeEvent(self, e):  # noqa: N802
        lay: QBoxLayout = self.layout()
        want = QBoxLayout.LeftToRight if e.size().width() >= self._needed() else QBoxLayout.TopToBottom
        if lay.direction() != want:
            lay.setDirection(want)
            self.updateGeometry()
        super().resizeEvent(e)


def reflow(layout: QBoxLayout) -> ReflowRow:
    return ReflowRow(layout)


def make_responsive(root: QWidget, min_chars: int = 8) -> None:
    for combo in root.findChildren(QComboBox):
        combo.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        combo.setMinimumContentsLength(min_chars)
        combo.setSizePolicy(QSizePolicy.Expanding, combo.sizePolicy().verticalPolicy())
        # Keep the full text visible in the drop-down list even when the box itself is narrow.
        combo.view().setMinimumWidth(combo.view().sizeHintForColumn(0) + 30)
    for edit in root.findChildren(QLineEdit):
        edit.setMinimumWidth(80)
    for form in root.findChildren(QFormLayout):
        form.setRowWrapPolicy(QFormLayout.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
