import asyncio
import flet as ft
from app.ui import theme

from app.ui import BasePage
from app.ui.widgets.files_dock import WIDE_MIN_WIDTH
from app.ui.widgets import Header, LanguagePicker, MessageBox, flag_text
from app.utils import Hub, Capabilities
from app.utils.transcript import Transcript, Bookmark, Segment, Item, clock, local_time
from app.common.transcript_command import TranscriptCommand
from app.utils.transcript_recording import TranscriptRecording
from app.common import get_logger
from app.common.languages import language_name

logger = get_logger()

AT_END_PX = 40      # this close to the bottom the text follows what arrives
SIDE_WIDTH = 260    # the bookmark list on a wide window
NEW_HEADING = "Heading"
NO_STT = "Speech recognition not available"     # the record button's tooltip without stt


def _update(control: ft.Control):
    try:
        control.update()
    except RuntimeError:
        pass  # not on the page (anymore)


class TranscribePage(BasePage):
    """#198 transcribe app: record, the text grows below while the hub transcribes it, a bookmark button marks the moment.
    the bookmarks are listed above the text, a tap scrolls to the marker. export saves it as a markdown file with links to the bookmarks.
    the recording (TranscriptRecording) goes on when the page is left, coming back shows it again.
    the hub stores every transcript, the history button opens an earlier one. record continues the transcript shown,
    new clears the page for a new one. a bookmark is one tap while recording, named Bookmark n: tap its marker or
    long press its chip to rename or delete it. the voice commands (new paragraph, heading ..., bookmark ..., scratch that)
    are shown interpreted (Transcript.blocks). once the recording has stopped and settled, edit shows each utterance as a
    field: a change is stored on the hub when the field is left, the bookmark button then sets a bookmark at the cursor,
    the heading button adds a heading there, or makes the marked text of an utterance one (emptied it is gone). on a wide window the bookmarks are listed on the right
    (like the files panel of the chat page), on a narrow one as chips above the text.
    opening the page shows the newest transcript (a running recording first). summary shows a few sentences the hub's
    llm writes (not stored), enhance makes a cleaned up copy (filler words out, grammar fixed) and opens it.
    a button that does nothing at the moment is hidden"""
    _language = ""      # whisper language of the next recording, "" = detected. kept while the app runs

    def __init__(self, navigator):
        super().__init__(navigator)
        self.language_btn = ft.IconButton(tooltip="language", on_click=lambda e: self.page.run_task(self._pick_language),
                                          width=40, height=40, style=theme.STYLES["icon_button"]["style"])
        self.history_btn = ft.IconButton(icon=ft.Icons.HISTORY, tooltip="earlier transcripts", on_click=self._open_history,
                                         width=40, height=40, style=theme.STYLES["icon_button"]["style"])
        self.new_btn = ft.IconButton(icon=ft.Icons.ADD, tooltip="new transcript", visible=False, on_click=self._on_new,
                                     width=40, height=40, style=theme.STYLES["icon_button"]["style"])
        # shown only while the text can be edited: the theme draws a disabled icon button like an enabled one
        self.edit_btn = ft.IconButton(icon=ft.Icons.EDIT, tooltip="edit the text", visible=False,
                                      on_click=lambda e: self.page.run_task(self._toggle_edit),
                                      width=40, height=40, style=theme.STYLES["icon_button"]["style"])
        self.export_btn = ft.IconButton(icon=ft.Icons.DOWNLOAD, tooltip="export as markdown", visible=False,
                                        on_click=lambda e: self.page.run_task(self._export),
                                        width=40, height=40, style=theme.STYLES["icon_button"]["style"])
        self.summary_btn = ft.IconButton(icon=ft.Icons.SUMMARIZE, tooltip="summary", visible=False,
                                         on_click=lambda e: self.page.run_task(self._summarize),
                                         width=40, height=40, style=theme.STYLES["icon_button"]["style"])
        self.enhance_btn = ft.IconButton(icon=ft.Icons.AUTO_FIX_HIGH, tooltip="enhanced copy: filler words out, grammar fixed",
                                         visible=False, on_click=lambda e: self.page.run_task(self._enhance),
                                         width=40, height=40, style=theme.STYLES["icon_button"]["style"])
        self.header = Header(navigator, selected_contact=False, actions=[self.language_btn, self.new_btn, self.history_btn, self.edit_btn,
                                                                         self.summary_btn, self.enhance_btn, self.export_btn])
        self.header.on_go_back = self.on_go_back
        self._show_language()

        self._active = False
        self.transcript: Transcript | None = None
        self.recording: TranscriptRecording | None = None
        self._editing = False
        self._fields: dict[int, ft.TextField] = {}      # id(segment) -> its field while editing, kept so the focus stays
        self._cursor: tuple[Segment, int] | None = None   # the field the cursor was in last and its offset
        self._selection: tuple[Segment, int, int] | None = None     # the text marked there: start, end in its field
        self._hub_lock = asyncio.Lock()     # a field's save on blur and a split of it reach the hub one after the other
        self._at_end = True
        self._wide = False          # the bookmarks on the right instead of above the text
        self._prev_resize = None
        self._file_picker = None    # like FileCard: a flet 1.0 service, made on the first save
        self._busy = ""             # what the llm is doing for the page (summary, enhance), "": nothing

        self.title = ft.Text("", weight=ft.FontWeight.BOLD, color=theme.TEXT, expand=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.bookmark_bar = ft.Row(scroll=ft.ScrollMode.AUTO, spacing=6, visible=False)
        self.partial = ft.Text("", italic=True, color=theme.TEXT_DIM, selectable=False)
        self.hint = ft.Text("Tap the record button to start. The text shows up here while you record.", color=theme.TEXT_DIM)
        self.text = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=8, on_scroll=self._on_scroll,
                              scroll_interval=200, controls=[self.hint])
        self.record_btn = ft.IconButton(icon=ft.Icons.FIBER_MANUAL_RECORD, icon_color=theme.ERROR, icon_size=40, tooltip="record",
                                        on_click=lambda e: self.page.run_task(self._toggle_record))
        self.bookmark_btn = ft.IconButton(icon=ft.Icons.BOOKMARK_ADD, icon_size=36, tooltip="bookmark", visible=False,
                                          on_click=self._on_bookmark)
        self.busy_text = ft.Text("", color=theme.TEXT_DIM)
        self.busy_row = ft.Row(visible=False, spacing=8, controls=[ft.ProgressRing(width=16, height=16, stroke_width=2), self.busy_text])
        self.summary_text = ft.Text("", color=theme.TEXT, selectable=True)
        self.summary_box = ft.Container(
            visible=False,
            bgcolor=theme.SURFACE_3,
            border_radius=theme.RADIUS // 2,
            padding=ft.Padding(left=12, top=4, right=4, bottom=12),
            content=ft.Column(spacing=4, controls=[
                ft.Row(controls=[ft.Text("Summary", weight=ft.FontWeight.BOLD, color=theme.TEXT, expand=True),
                                 ft.IconButton(icon=ft.Icons.CLOSE, icon_size=16, tooltip="close the summary",
                                               on_click=lambda e: self._show_summary(""))]),
                self.summary_text,
            ]),
        )
        self.heading_btn = ft.IconButton(icon=ft.Icons.TITLE, icon_size=36, tooltip="add a heading at the cursor or make the marked text one", visible=False,
                                         on_click=lambda e: self.page.run_task(self._add_heading))
        self.bookmark_list = ft.Column(scroll=ft.ScrollMode.AUTO, spacing=4, expand=True)
        self.bookmark_side = ft.Container(
            width=SIDE_WIDTH,
            visible=False,
            padding=ft.Padding(left=12, top=0, right=0, bottom=0),
            content=ft.Column(spacing=8, controls=[
                ft.Text("Bookmarks", weight=ft.FontWeight.BOLD, color=theme.TEXT), self.bookmark_list]),
        )
        self.elapsed = ft.Text("", color=theme.TEXT, size=16)
        bar = ft.Container(
            border_radius=20,
            bgcolor=theme.INPUT_BAR,
            padding=8,
            content=ft.Row(alignment=ft.MainAxisAlignment.SPACE_EVENLY,
                           controls=[self.record_btn, self.elapsed, self.bookmark_btn, self.heading_btn]),
        )
        self.controls = [
            ft.Container(
                expand=True,
                margin=20,
                content=ft.Column(expand=True, controls=[
                    self.header, ft.Row([self.title]), self.busy_row, self.summary_box, self.bookmark_bar,
                    ft.Row(expand=True, vertical_alignment=ft.CrossAxisAlignment.STRETCH, controls=[self.text, self.bookmark_side]),
                    bar,
                ]),
            ),
        ]

    def on_go_back(self, e=None):
        self.navigator.back()

    def on_enter(self, **kwargs):
        self._active = True
        Capabilities.listen(self._on_capabilities)
        self._prev_resize = self.page.on_resize       # like ChatPage: chained, given back on leave
        self.page.on_resize = self._on_resize
        self._layout()
        if TranscriptRecording.current:
            self._attach(TranscriptRecording.current)
        else:
            self._show_buttons()
            self.page.run_task(self._open_latest)
        self.page.run_task(self._clock_loop)

    def on_leave(self):
        self._active = False
        Capabilities.unlisten(self._on_capabilities)
        if self.page and self.page.on_resize == self._on_resize:
            self.page.on_resize = self._prev_resize
        if self.recording:
            self.recording.listen(None)     # it keeps recording, the next visit shows it again

    def _layout(self) -> bool:
        """wide or narrow for the page's width, True if it changed"""
        wide = bool(self.page) and (self.page.width or 0) >= WIDE_MIN_WIDTH
        changed, self._wide = wide != self._wide, wide
        return changed

    def _on_resize(self, e):
        if self.page and self._layout():
            self._render()
        if self._prev_resize:
            self._prev_resize(e)

    ########### recording
    def _attach(self, recording: TranscriptRecording):
        self.recording = recording
        self._show(recording.transcript)
        recording.listen(self._on_change)

    async def _toggle_record(self):
        if self.recording:
            await self.recording.stop()
            return
        if not Capabilities.has("stt"):     # the button shows it already (mic off), a tap says it
            MessageBox.show(self.page, NO_STT + ". The saved transcripts can still be opened, edited and exported.", title="Recording")
            return
        if self._editing:           # continuing: the edits first, the new text comes after them
            await self._toggle_edit()
        self.record_btn.visible = False     # starting
        _update(self.record_btn)
        try:
            recording = await TranscriptRecording.start(self.page, self._language, self.transcript)
        except Exception as e:      # no mic permission, no audio device, hub not reachable
            logger.error(f"failed to start the recording: {e!r}")
            MessageBox.error(self.page, f"The recording could not be started: {e}")
            self._show_buttons()
            return
        if not self._active:        # left meanwhile: it records, the next visit shows it
            return
        self._attach(recording)

    def _on_new(self, e=None):
        if not self.recording and not self._editing:
            self.transcript = None
            self._render()

    def _on_bookmark(self, e=None):
        if self.recording:
            self.recording.bookmark()
        elif self._editing:
            self.page.run_task(self._bookmark_at_cursor)

    def _on_capabilities(self, lost: set):
        """speech recognition went away: a running recording stops (what was transcribed is kept), record shows the mic off"""
        if "stt" in lost and self.recording and self.recording.recording:
            self.recording.error = "speech recognition is not available right now"
            self.page.run_task(self.recording.stop)
        self._show_buttons()

    def _on_change(self):
        if not self._active:
            return
        if self.recording and self.recording.error:
            MessageBox.error(self.page, f"{self.recording.error.capitalize()}. The recording stopped, the text so far is kept.",
                             title="Recording stopped")
            self.recording.error = ""
        if self.recording and not self.recording.streamer and not self.recording.stopping:
            self.recording.listen(None)     # stopped: the transcript stays on the page
            if self.recording.discarded:    # it got no text and is gone: an empty new one again
                self.transcript = None
            self.recording = None
        self._render()

    async def _clock_loop(self):
        while self._active:
            if self.recording and self.recording.recording:
                self.elapsed.value = clock(self.recording.elapsed)
                _update(self.elapsed)
            await asyncio.sleep(0.5)

    ########### showing a transcript
    def _show(self, transcript: Transcript):
        self.transcript = transcript
        self._editing = False
        self._fields.clear()
        self._cursor = self._selection = None
        self._at_end = True
        self._show_summary("")
        self._render()

    async def _open_latest(self):
        """the newest transcript when the page opens, unless something else is shown meanwhile"""
        transcripts = await asyncio.to_thread(Hub.get_transcripts)
        if not transcripts or not self._active or self.recording or self.transcript:
            return
        data = await asyncio.to_thread(Hub.get_transcript, transcripts[0]["id"])
        if data and self._active and not self.recording and not self.transcript:
            self._show(Transcript.from_dict(data))
            self._at_end = False

    def can_edit(self) -> bool:
        """not recording and there is text: edit is offered. the fields need the hub's ids (editable), _toggle_edit
        fetches the hub's copy when they are missing"""
        return self.recording is None and self.transcript is not None and bool(self.transcript.segments)

    def editable(self) -> bool:
        """the text can be edited once the recording has stopped and settled (TranscriptRecording.stop took the hub's copy)"""
        return self.can_edit() and any(s.id > 0 for s in self.transcript.segments)

    def _show_buttons(self):
        """only the buttons that do something now are shown"""
        recording = self.recording is not None
        stopping = recording and self.recording.stopping
        busy = bool(self._busy)
        idle = not recording and not self._editing and not busy      # a transcript (or none) shown, nothing going on
        has_text = bool(self.transcript and self.transcript.segments)
        # without speech recognition (and not recording) the button stays, greyed with the mic off: it can't record now.
        # not disabled: the theme draws a disabled icon button like an enabled one, a tap says why instead
        no_stt = not recording and not Capabilities.has("stt")
        self.record_btn.icon = ft.Icons.STOP if recording else ft.Icons.MIC_OFF if no_stt else ft.Icons.FIBER_MANUAL_RECORD
        self.record_btn.icon_color = theme.TEXT_DIM if no_stt else theme.ERROR
        self.record_btn.tooltip = "stop" if recording else NO_STT if no_stt else "continue recording" if self.transcript else "record"
        self.record_btn.visible = not stopping and not busy
        self.bookmark_btn.visible = recording and not stopping or self._editing
        self.bookmark_btn.tooltip = "bookmark at the cursor" if self._editing else "bookmark"
        self.heading_btn.visible = self._editing
        # a continued transcript keeps its language
        self.language_btn.visible = idle and self.transcript is None
        self.new_btn.visible = idle and self.transcript is not None
        self.history_btn.visible = idle
        self.edit_btn.visible = not busy and (self._editing or self.can_edit())
        self.edit_btn.selected = self._editing
        self.edit_btn.icon = ft.Icons.CHECK if self._editing else ft.Icons.EDIT
        self.edit_btn.tooltip = "done editing" if self._editing else "edit the text"
        self.export_btn.visible = self.summary_btn.visible = self.enhance_btn.visible = idle and has_text
        if not recording:
            self.elapsed.value = clock(self.transcript.end) if self.transcript else ""
        elif stopping:
            self.elapsed.value = "finishing…"
        for control in (self.record_btn, self.bookmark_btn, self.heading_btn, self.language_btn, self.new_btn, self.history_btn,
                        self.edit_btn, self.summary_btn, self.enhance_btn, self.export_btn, self.elapsed):
            _update(control)

    def _show_language(self):
        """the flag of the chosen language, the globe while whisper detects it"""
        self.language_btn.icon = flag_text(self._language) if self._language else ft.Icons.LANGUAGE
        self.language_btn.tooltip = f"language: {language_name(self._language)}" if self._language else "language: auto-detect"

    async def _pick_language(self):
        code = await LanguagePicker.open(self.page, self._language, auto=True)
        if code:    # "" = dismissed, AUTO = back to detected
            TranscribePage._language = "" if code == LanguagePicker.AUTO else code
            self._show_language()
            _update(self.language_btn)

    def _render(self):
        transcript = self.transcript
        self.title.value = transcript.title() if transcript else ""
        if not transcript:
            controls = []
        elif self._editing:
            controls = self._edit_controls()
        else:
            controls = [self._block_control(block) for block in transcript.blocks()]
        partial = self.recording.partial if self.recording else ""
        self.partial.value = partial
        if partial:
            controls.append(self.partial)
        self.text.controls = controls or [self.hint]
        bookmarks = transcript.bookmarks if transcript else []
        self.bookmark_bar.controls = [] if self._wide else [self._bookmark_chip(b) for b in bookmarks]
        self.bookmark_bar.visible = bool(self.bookmark_bar.controls)
        self.bookmark_list.controls = [self._bookmark_entry(b) for b in bookmarks] if self._wide else []
        self.bookmark_side.visible = bool(self.bookmark_list.controls)
        for control in (self.title, self.text, self.bookmark_bar, self.bookmark_side):
            _update(control)
        self._show_buttons()
        if self._at_end and self.recording:
            self.page.run_task(self._scroll_to_end)

    def _block_control(self, block) -> ft.Control:
        if block.kind == TranscriptCommand.BOOKMARK:
            return self._marker(block.bookmark)
        if block.kind == TranscriptCommand.HEADING:
            return ft.Text(block.text, color=theme.TEXT, selectable=True, size=18, weight=ft.FontWeight.BOLD)
        return ft.Text(block.text, color=theme.TEXT, selectable=True)

    def _marker(self, bookmark: Bookmark) -> ft.Control:
        """its label can change (rename, an earlier one deleted), so the marker is made anew each time"""
        return ft.Container(
            key=ft.ScrollKey(f"bookmark-{id(bookmark)}"),
            bgcolor=theme.BLOCKQUOTE,
            border_radius=theme.RADIUS // 2,
            padding=ft.Padding(left=8, top=2, right=8, bottom=2),
            ink=True,
            on_click=lambda e, b=bookmark: self.page.run_task(self._edit_bookmark, b),
            content=ft.Row(tight=True, spacing=4, controls=[
                ft.Icon(ft.Icons.BOOKMARK, size=16, color=theme.TEXT),
                ft.Text(self.transcript.name(bookmark), size=12, color=theme.TEXT),
            ]),
        )

    ########### editing (after the recording)
    def _edit_controls(self) -> list[ft.Control]:
        """a field per shown utterance or heading, in reading order, the bookmarks in front of the piece they are at
        (one inside an utterance below its field), a paragraph break as a line"""
        transcript = self.transcript
        items = transcript.items()
        before: dict[int, list[Bookmark]] = {}
        inside: dict[int, list[Bookmark]] = {}
        for bookmark in transcript.bookmarks:
            i, k = transcript.anchor(bookmark, items)
            (inside if k else before).setdefault(i, []).append(bookmark)
        controls = []
        for i, item in enumerate(items + [None]):
            controls += [self._marker(b) for b in before.get(i, [])]
            if item is None:
                break
            if item.kind == TranscriptCommand.PARAGRAPH:
                controls.append(ft.Divider(height=8, color=theme.SURFACE_3))
                continue
            controls.append(ft.Row([self._field(item)]))    # a row: the field takes the whole width
            controls += [self._marker(b) for b in inside.get(i, [])]
        return controls

    def _field(self, item: Item) -> ft.TextField:
        segment = item.segment
        field = self._fields.get(id(segment))
        if field is None:
            field = ft.TextField(
                value=segment.shown,
                expand=True,
                multiline=True,
                min_lines=1,
                max_lines=None,     # grows with its text, no scrolling inside
                read_only=segment.id <= 0,      # the hub's id is missing (not reachable when it stopped)
                text_size=18 if item.kind == TranscriptCommand.HEADING else None,
                text_style=ft.TextStyle(weight=ft.FontWeight.BOLD) if item.kind == TranscriptCommand.HEADING else None,
                border=ft.UnderlineInputBorder(),
                on_focus=lambda e, s=segment: self._set_cursor(s, None),
                on_selection_change=lambda e, s=segment: self._on_selection(s, e.selection),
                on_blur=lambda e, s=segment: self.page.run_task(self._save_edit, s),
            )
            self._fields[id(segment)] = field
        return field

    def _on_selection(self, segment: Segment, selection: ft.TextSelection):
        self._set_cursor(segment, selection.extent_offset)
        self._selection = (segment, selection.start, selection.end) if selection.start != selection.end else None

    def _set_cursor(self, segment: Segment, offset: int | None):
        if self._selection and self._selection[0] is not segment:
            self._selection = None
        if offset is None:      # focused: the cursor is where it was in this field, else at its end
            offset = self._cursor[1] if self._cursor and self._cursor[0] is segment else len(segment.shown)
        self._cursor = (segment, offset)

    async def _save_edit(self, segment: Segment) -> bool:
        """the field's text to the hub, if it changed. emptied: the utterance is not shown any more. False if it failed"""
        field = self._fields.get(id(segment))
        if field is None or segment.id <= 0:
            return True
        async with self._hub_lock:
            if segment not in self.transcript.segments:
                return True     # split meanwhile (marked text made a heading): its parts have the text
            text = " ".join((field.value or "").split())
            if text == segment.shown:
                return True
            if not await asyncio.to_thread(Hub.edit_transcript_segment, self.transcript.id, segment.id, text):
                MessageBox.error(self.page, "The change could not be saved.")
                return False
        segment.edited = text
        if not text:
            self._fields.pop(id(segment), None)
            self._render()
        return True

    async def _toggle_edit(self):
        if not self._editing:
            if not self.can_edit():
                return
            if not self.editable():     # the live copy without the hub's ids (it was not reachable after stop): fetch it
                data = await asyncio.to_thread(Hub.get_transcript, self.transcript.id)
                if data and self.can_edit():
                    self.transcript.settle(data)
                if not self.editable():
                    MessageBox.error(self.page, "The text can not be edited: the hub's copy of this transcript could not be loaded.")
                    self._render()
                    return
            self._editing = True
            self._fields.clear()
            self._cursor = self._selection = None
        else:
            for segment in [s for s in self.transcript.segments if id(s) in self._fields]:
                if not await self._save_edit(segment):
                    return      # stays in the editor with the text that was not saved
            self._editing = False
            self._fields.clear()
        self._render()

    async def _add_heading(self):
        """a heading where the cursor is (in front of the utterance with the cursor at its start, else behind it),
        stored on the hub, its field focused with its text selected to type over. text marked in an utterance becomes
        the heading instead (_heading_from_selection)"""
        if self._selection and await self._heading_from_selection(*self._selection):
            return
        transcript = self.transcript
        segment, offset = self._cursor if self._cursor else (None, 0)
        at = transcript.heading_time(segment, offset)
        segment_id = await asyncio.to_thread(Hub.add_transcript_heading, transcript.id, at, NEW_HEADING)
        if not segment_id:
            MessageBox.error(self.page, "The heading could not be saved.")
            return
        heading = transcript.add_segment(at, at, NEW_HEADING, segment_id, TranscriptCommand.HEADING)
        self._render()
        field = self._fields.get(id(heading))
        if field is None:
            return
        try:
            await field.focus()
            field.selection = ft.TextSelection(base_offset=0, extent_offset=len(NEW_HEADING))
            field.update()
        except Exception:
            pass    # not on the page (anymore)

    async def _heading_from_selection(self, segment: Segment, start: int, end: int) -> bool:
        """the marked text [start, end) of an utterance's field becomes a heading: the hub splits the segment into the
        text before, the heading and the text after in one call (Transcript.split_parts). False if there is nothing
        to split (a heading's field, only spaces marked): then a heading is added at the cursor"""
        transcript = self.transcript
        if segment not in transcript.segments or segment.command is not None or segment.id <= 0:
            return False
        field = self._fields.get(id(segment))
        parts = transcript.split_parts(segment, field.value if field else segment.shown, start, end)
        if not parts:
            return False
        self._cursor = self._selection = None
        async with self._hub_lock:
            ids = await asyncio.to_thread(Hub.split_transcript_segment, transcript.id, segment.id, parts)
            if len(ids) != len(parts):
                MessageBox.error(self.page, "The heading could not be made.")
                return True
            transcript.replace_segment(segment, parts, ids)
        self._fields.pop(id(segment), None)
        self._render()
        return True

    async def _bookmark_at_cursor(self):
        """a bookmark where the cursor is: its time is the cursor's share of the utterance, Transcript.anchor puts it there"""
        if self._cursor is None:
            MessageBox.show(self.page, "Tap into the text where the bookmark should go.", "Bookmark")
            return
        segment, offset = self._cursor
        transcript = self.transcript
        at = Transcript.time_at(segment, offset)
        label = transcript.next_label()
        bookmark_id = await asyncio.to_thread(Hub.add_transcript_bookmark, transcript.id, at, label)
        if not bookmark_id:
            MessageBox.error(self.page, "The bookmark could not be saved.")
            return
        transcript.add_bookmark(at, bookmark_id, label)
        self._render()

    def _bookmark_chip(self, bookmark: Bookmark) -> ft.Control:
        return ft.Container(
            bgcolor=theme.SURFACE_3,
            border_radius=theme.RADIUS // 2,
            padding=ft.Padding(left=8, top=4, right=8, bottom=4),
            ink=True,
            tooltip=self.transcript.preview(bookmark) or None,
            on_click=lambda e, b=bookmark: self.page.run_task(self._scroll_to, b),
            on_long_press=lambda e, b=bookmark: self.page.run_task(self._edit_bookmark, b),
            content=ft.Row(tight=True, spacing=4, controls=[
                ft.Icon(ft.Icons.BOOKMARK, size=16, color=theme.TEXT),
                ft.Text(self.transcript.name(bookmark), size=12, color=theme.TEXT, max_lines=1,
                        overflow=ft.TextOverflow.ELLIPSIS),
            ]),
        )

    def _bookmark_entry(self, bookmark: Bookmark) -> ft.Control:
        """the bookmark in the list on the right: its label and first words, a tap scrolls there, the pencil or a long
        press renames or deletes it"""
        preview = self.transcript.preview(bookmark)
        return ft.Container(
            bgcolor=theme.SURFACE_3,
            border_radius=theme.RADIUS // 2,
            padding=ft.Padding(left=8, top=4, right=0, bottom=4),
            ink=True,
            on_click=lambda e, b=bookmark: self.page.run_task(self._scroll_to, b),
            on_long_press=lambda e, b=bookmark: self.page.run_task(self._edit_bookmark, b),
            content=ft.Row(spacing=6, controls=[
                ft.Icon(ft.Icons.BOOKMARK, size=16, color=theme.TEXT),
                ft.Column(expand=True, spacing=0, controls=[
                    ft.Text(self.transcript.name(bookmark), size=13, color=theme.TEXT, weight=ft.FontWeight.BOLD,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(preview, size=12, color=theme.TEXT_DIM, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
                            visible=bool(preview)),
                ]),
                ft.IconButton(icon=ft.Icons.EDIT, icon_size=16, tooltip="rename or delete",
                              on_click=lambda e, b=bookmark: self.page.run_task(self._edit_bookmark, b)),
            ]),
        )

    def _on_scroll(self, e: ft.OnScrollEvent):
        self._at_end = e.max_scroll_extent - e.pixels < AT_END_PX

    async def _scroll_to_end(self):
        try:
            await self.text.scroll_to(offset=-1, duration=200)
        except Exception:
            pass    # not on the page (anymore)

    async def _scroll_to(self, bookmark: Bookmark):
        self._at_end = False
        try:
            await self.text.scroll_to(scroll_key=f"bookmark-{id(bookmark)}", duration=300)
        except Exception as e:
            logger.error(f"scrolling to bookmark failed: {e!r}")

    async def _edit_bookmark(self, bookmark: Bookmark):
        """a dialog to rename the bookmark (save) or delete it"""
        transcript, page = self.transcript, self.page
        if transcript is None or bookmark not in transcript.bookmarks:
            return
        done = asyncio.get_running_loop().create_future()

        def close(action: str):
            page.pop_dialog()
            if not done.done():
                done.set_result(action)

        field = ft.TextField(value=transcript.name(bookmark), autofocus=True, max_length=200, on_submit=lambda e: close("save"))
        page.show_dialog(ft.AlertDialog(
            modal=True,
            title=ft.Text("Bookmark"),
            content=ft.Container(width=320, content=field),
            actions=[
                ft.TextButton("Delete", on_click=lambda e: close("delete"), style=theme.STYLES["button"]["style"]),
                ft.TextButton("Cancel", on_click=lambda e: close(""), style=theme.STYLES["button"]["style"]),
                ft.TextButton("Save", on_click=lambda e: close("save"), style=theme.STYLES["button"]["style"]),
            ],
        ))
        action = await done
        if action == "save":
            await self._rename_bookmark(bookmark, (field.value or "").strip())
        elif action == "delete":
            await self._delete_bookmark(bookmark)

    async def _rename_bookmark(self, bookmark: Bookmark, label: str):
        transcript = self.transcript
        if not label or label == bookmark.label:
            return
        # not stored yet (recording, hub not reached): TranscriptRecording sends the new label along
        if bookmark.id > 0 and not await asyncio.to_thread(Hub.rename_transcript_bookmark, transcript.id, bookmark.id, label):
            MessageBox.error(self.page, "The bookmark could not be renamed.")
            return
        bookmark.label = label
        self._render()

    async def _delete_bookmark(self, bookmark: Bookmark):
        transcript = self.transcript
        if not await MessageBox.open(self.page, f"Delete {transcript.name(bookmark)}?", "Delete bookmark"):
            return
        if bookmark.id > 0 and not await asyncio.to_thread(Hub.delete_transcript_bookmark, transcript.id, bookmark.id):
            MessageBox.error(self.page, "The bookmark could not be deleted.")
            return
        if bookmark in transcript.bookmarks:
            transcript.remove_bookmark(bookmark)
        self._render()

    ########### summary, enhanced copy (the hub's llm, slow)
    def _set_busy(self, text: str):
        """text with a spinner while the llm works, the buttons that would interfere hidden. "": done"""
        self._busy = text
        self.busy_text.value = text
        self.busy_row.visible = bool(text)
        _update(self.busy_row)
        self._show_buttons()

    def _show_summary(self, summary: str):
        self.summary_text.value = summary
        self.summary_box.visible = bool(summary)
        _update(self.summary_box)

    async def _summarize(self):
        transcript = self.transcript
        if not transcript or self._busy:
            return
        self._set_busy("Writing a summary…")
        try:
            summary = await asyncio.to_thread(Hub.summarize_transcript, transcript.id, transcript.plain_text())
        finally:
            self._set_busy("")
        if transcript is not self.transcript or not self._active:
            return      # another one shown meanwhile, or left
        if not summary:
            MessageBox.error(self.page, "The summary could not be made. Is the language model running?")
            return
        self._show_summary(summary)

    async def _enhance(self):
        transcript = self.transcript
        if not transcript or self._busy:
            return
        if not await MessageBox.open(self.page, "Make a copy without filler words (ehm, hmm, …) and with the grammar fixed? "
                                                "The original stays as it is. This can take a few minutes.", "Enhanced copy"):
            return
        self._set_busy("Making the enhanced copy… this can take a few minutes")
        try:
            copy_id = await asyncio.to_thread(Hub.enhance_transcript, transcript.id, transcript.enhanced_title())
            data = await asyncio.to_thread(Hub.get_transcript, copy_id) if copy_id else None
        finally:
            self._set_busy("")
        if not data:
            if self._active:
                MessageBox.error(self.page, "The enhanced copy could not be made. Is the language model running?")
            return
        if self._active and not self.recording:     # left meanwhile: the next visit opens it (the newest)
            self._show(Transcript.from_dict(data))
            self._at_end = False

    ########### export
    async def _export(self):
        if not self.transcript:
            return
        if self._file_picker is None:
            self._file_picker = ft.FilePicker()
        try:
            # android needs the bytes, on desktop flet writes them to the chosen path
            await self._file_picker.save_file(dialog_title="Export transcript", file_name=self.transcript.file_name(),
                                              src_bytes=self.transcript.to_markdown().encode("utf-8"))
        except Exception as e:
            logger.error(f"exporting transcript {self.transcript.id} failed: {e}")

    ########### earlier transcripts
    def _open_history(self, e=None):
        self.page.run_task(self._show_history)

    async def _show_history(self):
        transcripts = await asyncio.to_thread(Hub.get_transcripts)
        if transcripts is None:
            MessageBox.error(self.page, "The transcripts could not be loaded.")
            return
        page = self.page
        tiles = ft.ListView(spacing=4)

        async def pick(transcript_id: int):
            page.pop_dialog()
            data = await asyncio.to_thread(Hub.get_transcript, transcript_id)
            if data is None:
                MessageBox.error(page, "The transcript could not be loaded.")
                return
            if self._active and not self.recording:
                self._show(Transcript.from_dict(data))
                self._at_end = False

        async def delete(item: dict, tile: ft.Control):
            if not await MessageBox.open(page, "Delete this transcript with its bookmarks?", "Delete transcript"):
                return
            if not await asyncio.to_thread(Hub.delete_transcript, item["id"]):
                MessageBox.error(page, "The transcript could not be deleted.")
                return
            if tile in tiles.controls:
                tiles.controls.remove(tile)
                _update(tiles)
            if self.transcript and self.transcript.id == item["id"]:
                self.transcript = None
                self._render()

        for item in transcripts:
            local = local_time(item.get("created_at", ""))
            info = f"{clock(item.get('duration') or 0)} · {item.get('bookmarks', 0)} bookmarks"
            tile = ft.ListTile(
                title=ft.Text(item.get("title") or (f"{local:%Y-%m-%d %H:%M}" if local else f"#{item['id']}")),
                subtitle=ft.Text(f"{info}\n{item.get('preview') or ''}", max_lines=2, overflow=ft.TextOverflow.ELLIPSIS),
                on_click=lambda e, i=item["id"]: page.run_task(pick, i),
            )
            tile.trailing = ft.IconButton(icon=ft.Icons.DELETE, on_click=lambda e, i=item, t=tile: page.run_task(delete, i, t))
            tiles.controls.append(tile)
        if not tiles.controls:
            tiles.controls.append(ft.Text("No transcripts yet.", color=theme.TEXT_DIM))
        page.show_dialog(ft.AlertDialog(
            modal=False,
            title=ft.Text("Transcripts"),
            content=ft.Container(width=400, height=500, content=tiles),
        ))
