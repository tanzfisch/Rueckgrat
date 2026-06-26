from PySide6.QtWidgets import QTextEdit
from PySide6.QtCore import QMimeData

class PlainTextEdit(QTextEdit):
    def insertFromMimeData(self, source: QMimeData):
        if source.hasText():
            self.insertPlainText(source.text())