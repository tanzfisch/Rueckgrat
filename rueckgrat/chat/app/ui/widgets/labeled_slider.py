import flet as ft
from app.ui.theme import STYLES

class LabeledSlider(ft.Column):
    def __init__(
        self,
        left_text="Min",
        right_text="Max",
        range_min: int = 0,
        range_max: int = 100,
        start_value: int = 50,
        **kwargs,
    ):
        self.slider = ft.Slider(
            min=range_min,
            max=range_max,
            value=start_value,
            divisions=range_max - range_min,
        )
        super().__init__(
            controls=[
                self.slider,
                ft.Row(
                    [
                        ft.Text(left_text, style=STYLES["label_slider"]),
                        ft.Container(expand=True),
                        ft.Text(right_text, style=STYLES["label_slider"]),
                    ],
                ),
            ],
            spacing=0,
            tight=True,
            **kwargs,
        )

    def get_value(self):
        return int(self.slider.value)