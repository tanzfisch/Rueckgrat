import flet as ft


class PlainTextEdit(ft.TextField):
    def __init__(self, **kwargs):
        super().__init__(multiline=True, **kwargs)