from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QSizePolicy,
    QStackedLayout,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


class CollapsibleSection(QWidget):
    """Compact disclosure section used for secondary interface controls."""

    expanded_changed = Signal(bool)

    def __init__(
        self,
        title: str,
        *,
        expanded: bool = True,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.toggle_button = QToolButton()
        self.toggle_button.setText(title)
        self.toggle_button.setCheckable(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.toggle_button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.toggle_button.setStyleSheet(
            "QToolButton { border: 0; font-weight: 600; padding: 4px 2px; "
            "text-align: left; }"
        )

        self.content = QWidget()
        self.content_layout = QVBoxLayout(self.content)
        self.content_layout.setContentsMargins(18, 2, 0, 4)
        self.content_layout.setSpacing(6)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.toggle_button)
        layout.addWidget(self.content)

        self.toggle_button.toggled.connect(self.set_expanded)
        self.set_expanded(expanded)

    def is_expanded(self) -> bool:
        return self.toggle_button.isChecked()

    def set_expanded(self, expanded: bool) -> None:
        self.toggle_button.blockSignals(True)
        self.toggle_button.setChecked(expanded)
        self.toggle_button.blockSignals(False)
        self.toggle_button.setArrowType(Qt.DownArrow if expanded else Qt.RightArrow)
        self.content.setVisible(expanded)
        self.expanded_changed.emit(expanded)


class EmptyStateTable(QWidget):
    """Switch between a table and a centered, informative empty state."""

    def __init__(
        self,
        table: QWidget,
        empty_text: str,
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.table = table
        self.empty_label = QLabel(empty_text)
        self.empty_label.setAlignment(Qt.AlignCenter)
        self.empty_label.setWordWrap(True)
        self.empty_label.setStyleSheet("QLabel { color: #66717d; padding: 24px; }")

        self.stack = QStackedLayout(self)
        self.stack.setContentsMargins(0, 0, 0, 0)
        self.stack.addWidget(self.empty_label)
        self.stack.addWidget(self.table)
        self.show_empty(empty_text)

    def show_empty(self, message: str | None = None) -> None:
        if message is not None:
            self.empty_label.setText(message)
        self.stack.setCurrentWidget(self.empty_label)

    def show_table(self) -> None:
        self.stack.setCurrentWidget(self.table)
