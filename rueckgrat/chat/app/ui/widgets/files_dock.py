"""a page's content with the FilesPanel of a contact's files (ContactFiles): docked to the right of the content on a
wide window, over all of it on a narrow one. the page attaches it when it shows (the window's resizes reach it,
chained like ChatPage's other listeners) and detaches it when it leaves"""
import flet as ft
from .files_panel import FilesPanel

# from this window width on the panel docks to the right of the content, below it covers the content.
# material's "expanded" window class: room for the panel and a conversation of about 500
WIDE_MIN_WIDTH = 840


class FilesDock(ft.Stack):
    def __init__(self, content: ft.Control):
        self._body = ft.Container(content=content, left=0, top=0, right=0, bottom=0)   # all of it, or all but the docked panel
        self._panel = FilesPanel(on_close=self.close)
        self._prev_resize = None
        super().__init__([self._body, self._panel], expand=True)

    @property
    def is_open(self) -> bool:
        return self._panel.visible

    def toggle(self, source) -> None:
        """opens the panel on source's files (ContactFiles), or closes it when it is open"""
        if self._panel.visible:
            self._panel.visible = False
        else:
            self._panel.show(source)
        self._relayout()

    def close(self) -> None:
        self._panel.visible = False
        self._relayout()

    def refresh(self) -> None:
        """the files may have changed (a reply wrote some): listed again, only when the panel is open"""
        self._panel.refresh()

    def attach(self) -> None:
        """the page shows: the dock follows the window's width"""
        page = self._page()
        if page and page.on_resize != self._on_resize:
            self._prev_resize = page.on_resize
            page.on_resize = self._on_resize
        self._layout()

    def detach(self) -> None:
        """the page leaves: the resize listener before it is given back"""
        page = self._page()
        if page and page.on_resize == self._on_resize:
            page.on_resize = self._prev_resize

    def _page(self):
        """the page, None while the dock is not on one (flet raises then)"""
        try:
            return self.page
        except RuntimeError:
            return None

    def _layout(self) -> None:
        page = self._page()
        wide = bool(page) and (page.width or 0) >= WIDE_MIN_WIDTH
        self._panel.dock(wide)
        self._body.right = FilesPanel.WIDTH if wide and self._panel.visible else 0

    def _relayout(self) -> None:
        self._layout()
        if self._page():
            self.update()

    def _on_resize(self, e) -> None:
        if self._page():
            self._relayout()
        if self._prev_resize:
            self._prev_resize(e)
