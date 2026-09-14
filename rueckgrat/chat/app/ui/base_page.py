import flet as ft


class BasePage(ft.Column):
    """
    Base class for all pages.
    """

    def __init__(self, navigator):
        super().__init__(expand=True, spacing=0)
        self._navigator = navigator

    @property
    def navigator(self):
        return self._navigator

    def on_enter(self, **kwargs):
        """
        Called whenever this page becomes active.
        Override in subclasses.
        """
        pass

    def on_leave(self):
        """
        Called whenever this page is left.
        Override in subclasses.
        """
        pass        