import math
import random
from PySide6.QtWidgets import QWidget, QPushButton
from PySide6.QtCore import Signal, QTimer

class BubbleSelector(QWidget):
    selection_changed = Signal(str)

    def __init__(self, options, parent=None):
        super().__init__(parent)
        self.setMinimumSize(500, 400)

        self.buttons = []
        self.selected = None
        self.initial_pos = {}
        self.time = 0        

        n = len(options)
        if n == 0:
            return

        center_x, center_y = 250, 200
        radius_x = 320
        radius_y = 250

        rings = max(1, int(math.sqrt(n)))
        idx = 0

        for ring in range(1, rings + 1):
            r_x = (ring / rings) * radius_x
            r_y = (ring / rings) * radius_y
            
            buttons_in_ring = max(3, int(2 * math.pi * ring * 0.9))
            if idx + buttons_in_ring > n:
                buttons_in_ring = n - idx

            for i in range(buttons_in_ring):
                angle = 2 * math.pi * i / buttons_in_ring
                
                offset_r = random.uniform(-18, 18)
                offset_a = random.uniform(-0.12, 0.12)
                
                r = (ring / rings) * max(radius_x, radius_y) + offset_r
                a = angle + offset_a + 0.3
                
                x = center_x + r_x * math.cos(a) - 55
                y = center_y + r_y * math.sin(a) - 25
                
                btn = QPushButton(options[idx], self)
                btn.setCheckable(True)
                btn.move(int(x), int(y))
                #btn.resize(button_width, button_height)
                
                btn.clicked.connect(self.make_handler(btn))
                self.buttons.append(btn)
                idx += 1
                if idx >= n:
                    break
            if idx >= n:
                break

        # After creating all buttons:
        for btn in self.buttons:
            self.initial_pos[btn] = btn.pos()
        
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.animate)
        self.timer.start(50)  # ~20 FPS            

    def make_handler(self, btn):
        def handler():
            for b in self.buttons:
                if b != btn:
                    b.setChecked(False)
            new_value = btn.text()
            if new_value != self.selected:
                self.selected = new_value
                self.selection_changed.emit(new_value)
        return handler
    
    def unselect(self):
        for b in self.buttons:
            b.setChecked(False)

    def animate(self):
        self.time += 0.08
        for btn in self.buttons:
            if btn in self.initial_pos:
                ix, iy = self.initial_pos[btn].x(), self.initial_pos[btn].y()
                offset_x = math.sin(self.time + id(btn)) * 6
                offset_y = math.cos(self.time * 1.1 + id(btn) * 0.7) * 4
                btn.move(int(ix + offset_x), int(iy + offset_y))    