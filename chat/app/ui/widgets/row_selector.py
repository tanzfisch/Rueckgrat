import random
from typing import Dict, Any
from PySide6.QtWidgets import QWidget, QPushButton, QHBoxLayout, QVBoxLayout
from PySide6.QtCore import Signal, QSize
from PySide6.QtGui import QIcon

from common import Logger
logger = Logger(__name__).get_logger()

class RowSelector(QWidget):
    selection_changed = Signal(str)

    def __init__(self, options: Dict[str, Any], image_only: bool = True, max_columns = 5, parent=None):
        super().__init__(parent)

        self.buttons = []
        self.selected = None
        column = max_columns

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

        for name, image in options.items():
            if column >= max_columns:
                container = QWidget()
                layout.addWidget(container)
                row = QHBoxLayout(container)
                row.setContentsMargins(0,0,0,0)
                column = 0

            button = QPushButton()

            if image != "":
                button.setIcon(QIcon(image))
                button.setIconSize(QSize(40, 40))
                if not image_only:
                    button.setText(name)
            else:
                button.setText(name)

            button.setProperty("value", name)


            button.setCheckable(True)
                
            button.clicked.connect(self.make_handler(button))
            self.buttons.append(button)

            row.addWidget(button)

            column += 1

    def update_images(self, options: Dict[str, Any]):
        for name, image in options.items():
            for button in self.buttons:
                if button.property("value") == name:                    
                    button.setIcon(QIcon(image))
       
    def make_handler(self, btn):
        def handler():
            for button in self.buttons:
                if button != btn:
                    button.setChecked(False)

            new_value = btn.property("value")
            if new_value != self.selected:
                self.selected = new_value
                self.selection_changed.emit(new_value)
        return handler
    
    def select_random(self):
        index = random.randint(0, len(self.buttons)-1)
        counter = 0
        for button in self.buttons:
            if index == counter:
                button.setChecked(True)
                self.selected = button.property("value")
            else:
                button.setChecked(False)
            counter += 1

    def select(self, key: str):
        self.selected = key
        for button in self.buttons:
            button.setChecked(button.property("value") == key)
    
    def unselect(self):
        for button in self.buttons:
            button.setChecked(False)

        self.selected = None

    def get_selected(self):
        return self.selected
