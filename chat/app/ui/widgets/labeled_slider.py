from PySide6.QtWidgets import (
    QWidget,
    QLabel,
    QSlider,
    QVBoxLayout,
    QHBoxLayout,
)
from PySide6.QtCore import Qt

class LabeledSlider(QWidget):
    def __init__(self, left_text="Min", right_text="Max", range_min: int = 0, range_max: int = 100, start_value:int = 50, parent=None,):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0,0,0,0)

        # Slider
        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(range_min, range_max)
        self.slider.setValue(start_value)   
        layout.addWidget(self.slider)

        # bottom label row
        labels_bottom = QHBoxLayout()

        self.left_label = QLabel(left_text)
        self.left_label.setObjectName("label_slider")
        labels_bottom.addWidget(self.left_label)

        labels_bottom.addStretch()
            
        self.right_label = QLabel(right_text)
        self.right_label.setObjectName("label_slider")        
        labels_bottom.addWidget(self.right_label)        
        layout.addLayout(labels_bottom)

    def get_value(self):
        return self.slider.value()