"""#198 the recording of the transcribe app, from the record button until stop"""
import asyncio
from datetime import datetime, timezone
from typing import Callable, Optional

import flet as ft

from app.common import get_logger
from .audio_streamer import AudioStreamer
from .hub import Hub
from .transcript import Transcript, Bookmark
logger = get_logger()


class TranscriptRecording:
    """
    The mic streams to the hub's /ws/audio with the transcript's id: the hub transcribes utterance by utterance, stores
    each final text in the transcript and sends it back with its times, which go into the transcript here. a bookmark is
    the recording's time (AudioStreamer.position, the same clock as the hub's times) when it was tapped.

    Continuing an earlier transcript records into it: the clock starts at its end (AudioStreamer start_offset), so the new
    texts and bookmarks come after the stored ones and the hub's dedupe of replayed audio keeps working.

    It outlives its page (pages are rebuilt on every visit): leaving the transcribe page keeps it recording, in the
    background too (AudioStreamer runs the KeepAlive microphone service). one at a time, the running one is current.
    """
    current: Optional["TranscriptRecording"] = None

    def __init__(self, page: ft.Page, transcript: Transcript):
        self.page = page
        self.transcript = transcript
        self.partial = ""           # the words of the utterance still going on, replaced by its final text
        self.stopping = False
        self.error = ""             # why the hub could not transcribe (speech recognition down), the recording stopped
        self.streamer: AudioStreamer | None = None
        self._listener: Callable[[], None] | None = None

    @classmethod
    async def start(cls, page: ft.Page, language: str = "", transcript: Transcript | None = None) -> "TranscriptRecording":
        """the mic on, into transcript (continued, it keeps its language) or a new one on the hub. raises if it failed"""
        if cls.current:
            raise RuntimeError("a recording is running already")
        if transcript is None:
            transcript_id = await asyncio.to_thread(Hub.create_transcript, language)
            if not transcript_id:
                raise RuntimeError("the hub could not create a transcript")
            created_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
            transcript = Transcript(id=transcript_id, language=language, created_at=created_at)
        language = transcript.language
        recording = cls(page, transcript)
        recording.streamer = AudioStreamer(
            uri=Hub.uri.replace("/ws", "/ws/audio"),
            token=Hub.access_token,
            cert=Hub.server_cert,
            on_message=lambda payload: page.run_task(recording._on_audio, payload),
            language=language,
            transcript_id=transcript.id,
            start_offset=transcript.resume_at,
        )
        try:
            recording.streamer.attach(page)
            await recording.streamer.start()
        except Exception:
            await recording.streamer.stop()
            raise
        cls.current = recording
        return recording

    def listen(self, listener: Callable[[], None] | None):
        """listener() after every change (text, bookmark, stopped), None: nobody listens"""
        self._listener = listener

    def _changed(self):
        if self._listener:
            try:
                self._listener()
            except Exception as e:
                logger.error(f"transcript listener failed: {e!r}")

    @property
    def recording(self) -> bool:
        return self.streamer is not None and not self.stopping

    @property
    def elapsed(self) -> float:
        return self.streamer.position if self.streamer else self.transcript.end

    def bookmark(self) -> Bookmark | None:
        """a bookmark now, stored on the hub in the background"""
        if not self.recording:
            return None
        bookmark = self.transcript.add_bookmark(self.elapsed, label=self.transcript.next_label())
        self._changed()
        self.page.run_task(self._store_bookmarks)
        return bookmark

    async def _store_bookmarks(self):
        """every bookmark the hub has not got yet (it was not reachable when it was tapped)"""
        for bookmark in [b for b in self.transcript.bookmarks if not b.id]:
            bookmark.id = -1        # on its way, a second call does not send it again
            label = bookmark.label
            bookmark.id = await asyncio.to_thread(Hub.add_transcript_bookmark, self.transcript.id, bookmark.at, label)
            if bookmark.id and bookmark.label != label:      # renamed while it was on its way
                await asyncio.to_thread(Hub.rename_transcript_bookmark, self.transcript.id, bookmark.id, bookmark.label)

    async def stop(self):
        """mic off, the hub transcribes what is left (AudioStreamer.finish), then the hub's copy is taken"""
        if not self.streamer or self.stopping:
            return
        self.stopping = True
        self._changed()
        try:
            await self.streamer.finish()
            self.transcript.duration = max(self.transcript.duration, self.streamer.position)
            await self._store_bookmarks()
            # settled: the hub's copy, with the ids the edits need. not reachable: the live copy stays
            data = await asyncio.to_thread(Hub.get_transcript, self.transcript.id)
            if data:
                self.transcript.settle(data)
        finally:
            self.streamer = None
            self.stopping = False
            self.partial = ""
            if TranscriptRecording.current is self:
                TranscriptRecording.current = None
            self._changed()

    async def _on_audio(self, payload: dict):
        kind = payload.get("type")
        if kind == "mic.off":       # the buffer ran full while the hub was not reachable
            await self.stop()
            return
        if kind == "error":         # the hub can't transcribe (speech recognition down): what was said is not stored, stop
            logger.error(f"recording stopped: {payload.get('text')}")
            if not self.stopping:   # stopping already (by hand, or the capability went away): said once
                self.error = payload.get("text") or "speech recognition failed"
                await self.stop()
            return
        if kind == "partial":
            self.partial = (payload.get("text") or "").strip()
        elif kind == "final":
            self.partial = ""
            if "start" in payload:
                self.transcript.add_segment(payload["start"], payload["end"], payload.get("text") or "", payload.get("id", 0))
            bookmark = payload.get("bookmark")      # "bookmark <label>" said: the hub stored it
            if bookmark and bookmark.get("id") and all(b.id != bookmark["id"] for b in self.transcript.bookmarks):
                self.transcript.add_bookmark(bookmark["at"], bookmark["id"], bookmark.get("label", ""))
            if any(not b.id for b in self.transcript.bookmarks):
                self.page.run_task(self._store_bookmarks)     # the hub answers again
        else:
            return
        self._changed()
