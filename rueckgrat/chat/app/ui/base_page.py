from PySide6.QtWidgets import QWidget

class BasePage(QWidget):
    """
    Base class for all pages.
    """

    def __init__(self, navigator, parent=None):
        super().__init__(parent)
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