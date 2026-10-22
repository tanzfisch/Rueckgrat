import base64
import io
import json
import os
import platform
import queue
import re
import shlex
import ssl
import subprocess
import tempfile
import threading
import time
import uuid
import wave
from pathlib import Path
from threading import Lock

import flet as ft

from app.utils import Hub
from app.common import get_logger, Utils
logger = get_logger()


class Text_To_Speech:
    """fetches speech from the hub and plays it, in a background thread"""

    _current_proc = None  # running aplay process, if any
    _generation = 0       # bumped on every speak/kill, stale threads skip playback
    _proc_lock = Lock()
    _page = None          # flet page, needed for in-app playback on mobile
    _current_audio = None # running flet Audio service on mobile, if any
    _audio_done = None    # set when in-app playback ends
    _sample_id = None     # predefined voice whose sample is playing, None for speech
    _tts_ws = None        # (websocket, reply_id) of the reply streaming from the hub, if any
    state = "idle"        # "idle" / "generating" / "playing", written by the speech thread, polled by the chat page

    @classmethod
    def attach(cls, page: ft.Page):
        cls._page = page

    @classmethod
    def _is_mobile(cls) -> bool:
        p = getattr(cls._page, "platform", None) if cls._page else None
        return bool(p and getattr(p, "is_mobile", lambda: False)())

    @classmethod
    def kill_current_speech(cls):
        with cls._proc_lock:
            cls._generation += 1
            cls.state = "idle"
            cls._sample_id = None
            proc = cls._current_proc
            cls._current_proc = None
            audio, done = cls._current_audio, cls._audio_done
            tts, cls._tts_ws = cls._tts_ws, None
        if tts:
            ws, reply_id = tts
            try:
                ws.send(json.dumps({"stop": reply_id}))  # the hub drops the rest of the reply
                ws.close()
            except Exception:
                pass
        if audio and cls._page and cls._is_attached(audio):
            cls._page.run_task(audio.pause)
        if done:
            done.set()
        if proc and proc.poll() is None:
            proc.kill()
            proc.wait()
        if platform.system() == "Windows":
            import winsound
            winsound.PlaySound(None, 0)

    @classmethod
    def speak(cls, text: str, voice: str = "", message_id: int | None = None, language: str = ""):
        """language: code for the multilingual tts, "" = the node detects it from the text"""
        if not text.strip():
            return

        logger.info(f"prep speech \"{Utils.shorten(text)}\" with voice \"{voice or 'default'}\"")
        text = cls._cleanup_for_speech(text)
        cls._start(lambda generation, put: cls._receive_reply(text, voice, message_id, generation, put, language))

    @classmethod
    def play_voice_sample(cls, predefined_id: str):
        """plays the sample of a predefined voice, calling it again for the same voice while it plays stops it"""
        if cls.state != "idle" and cls._sample_id == predefined_id:
            cls.kill_current_speech()
            return
        cls._start(lambda generation, put: put(Hub.get_predefined_voice_sample(predefined_id)), sample_id=predefined_id)

    @classmethod
    def _start(cls, produce, sample_id: str | None = None):
        """stops what is playing and plays, in a background thread, the wavs produce(generation, put) hands to put()"""
        try:
            cls.kill_current_speech()
            with cls._proc_lock:
                generation = cls._generation
                cls.state = "generating"
                cls._sample_id = sample_id
            if cls._page and cls._is_mobile():
                # run_thread sets flet's page context, so services like flet_audio.Audio register themselves.
                # mobile only: run_thread workers are not daemon threads, on desktop they would block
                # interpreter exit until aplay finished, so the atexit kill_current_speech came too late
                cls._page.run_thread(cls._run_speech, produce, generation)
            else:
                threading.Thread(target=cls._run_speech, args=(produce, generation), daemon=True).start()
        except Exception as e:
            cls.state = "idle"
            logger.error(f"failed to run speech generation {e}")

    @staticmethod
    def _cleanup_for_speech(text: str) -> str:
        text = text.replace("*", "")
        text = re.sub(r"\*[^*]+\*|\([^)]*\)|\[[^\]]+\]", "", text)
        text = re.sub(r'https?://\S+|www\.\S+', '', text).strip()
        return re.sub(r'\[IMAGE:[^\]]*\]', '', text).strip()

    @classmethod
    def _is_current(cls, generation: int) -> bool:
        with cls._proc_lock:
            return generation == cls._generation

    @classmethod
    def _set_state(cls, generation: int, state: str):
        """only the current speech may change the state, a killed one must not overwrite its successor"""
        with cls._proc_lock:
            if generation == cls._generation:
                cls.state = state

    @classmethod
    def _run_speech(cls, produce, generation: int):
        """a second thread produces the wavs, this one plays each as soon as it is there,
        so the next chunk is generated while the current one plays"""
        wavs = queue.Queue()

        def run_produce():
            try:
                produce(generation, lambda wav: wavs.put(wav or b""))
            except Exception as e:
                logger.error(f"failed to get speech: {e!r}")
            finally:
                wavs.put(None)

        threading.Thread(target=run_produce, daemon=True).start()
        try:
            while (wav := wavs.get()) is not None:
                if not cls._is_current(generation):
                    return  # a newer speak() or a kill happened while we waited for the hub
                if not wav:
                    logger.error("failed to get speech from hub")
                    continue
                cls._play_wav(wav, generation)
                cls._set_state(generation, "generating")  # until the next chunk plays
        finally:
            cls._set_state(generation, "idle")

    @classmethod
    def _receive_reply(cls, text: str, voice: str, message_id, generation: int, put, language: str = ""):
        """streams the speech of a reply from the hub's /ws/tts in 1 s pieces, a wav per text chunk goes to put().
        every piece is acknowledged, after a dropped connection the hub resends from the last one received,
        so nothing is lost and nothing played twice"""
        from websockets.sync.client import connect
        from websockets.exceptions import InvalidStatus

        reply_id = uuid.uuid4().hex
        uri = Hub.uri.replace("/ws", "/ws/tts")
        ctx = ssl.create_default_context(cafile=Hub.server_cert) if uri.startswith("wss") else None
        last_seq, pcm, delay = -1, bytearray(), 0.5
        while cls._is_current(generation):
            try:
                with connect(uri, additional_headers={"Authorization": f"Bearer {Hub.access_token}"}, ssl=ctx,
                             open_timeout=10, ping_interval=5, ping_timeout=5) as ws:
                    with cls._proc_lock:
                        if generation != cls._generation:
                            return
                        cls._tts_ws = (ws, reply_id)
                    delay = 0.5
                    # nothing received yet: (re)start the reply, otherwise continue after the last piece
                    ws.send(json.dumps({"speak": {"reply_id": reply_id, "text": text, "voice": voice, "message_id": message_id, "language": language}}
                                       if last_seq < 0 else {"resume": {"reply_id": reply_id, "last_seq": last_seq}}))
                    for message in ws:
                        data = json.loads(message)
                        if data.get("gone") == reply_id:
                            logger.warning("the hub dropped the speech of this reply")
                            return
                        piece = data.get("piece")
                        if data.get("reply_id") != reply_id or not piece or piece["seq"] <= last_seq:
                            continue  # not this reply, or already received
                        last_seq = piece["seq"]
                        if not piece.get("end"):
                            pcm += base64.b64decode(piece["data"])
                            if piece["last"]:
                                put(cls._to_wav(pcm, piece))
                                pcm = bytearray()
                        ws.send(json.dumps({"ack": last_seq}))
                        if piece.get("end"):
                            return
            except InvalidStatus as e:
                if e.response.status_code in (401, 403):
                    logger.error("tts ws rejected the token")
                    return
                logger.error(f"tts ws error: {e}")
            except Exception as e:
                if cls._is_current(generation):
                    logger.error(f"tts ws error: {e!r}")
            finally:
                with cls._proc_lock:
                    if cls._tts_ws and cls._tts_ws[1] == reply_id:
                        cls._tts_ws = None
            if cls._is_current(generation):
                logger.info(f"tts ws down, resuming after piece {last_seq} in {delay:.1f}s")
                end = time.monotonic() + delay
                while cls._is_current(generation) and time.monotonic() < end:
                    time.sleep(0.05)
                delay = min(delay * 2, 2)

    @staticmethod
    def _to_wav(pcm: bytes, params: dict) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as w:
            w.setnchannels(params["channels"])
            w.setsampwidth(params["width"])
            w.setframerate(params["rate"])
            w.writeframes(bytes(pcm))
        return buffer.getvalue()

    @classmethod
    def _play_wav(cls, wav: bytes, generation: int):
        if cls._is_mobile():
            try:
                cls._play_in_app(wav, generation)
            except Exception as e:
                logger.error(f"failed to playback speech: {e}")
            return

        output_file = os.path.join(tempfile.gettempdir(), f"chat_speech_{uuid.uuid4()}.wav")
        try:
            Path(output_file).write_bytes(wav)
            cls._play(output_file, generation)
        except Exception as e:
            logger.error(f"failed to playback speech: {e}")
        finally:
            logger.debug("delete speech")
            Path(output_file).unlink(missing_ok=True)

    @classmethod
    def _play(cls, wav_file: str, generation: int):
        logger.debug("playback speech")
        if platform.system() == "Windows":
            import winsound
            if not cls._is_current(generation):
                return
            cls._set_state(generation, "playing")
            winsound.PlaySound(wav_file, winsound.SND_FILENAME)
            return

        command_aplay = ["aplay", wav_file]
        logger.debug(f"run: {shlex.join(command_aplay)}")
        with cls._proc_lock:
            if generation != cls._generation:
                return
            proc = subprocess.Popen(command_aplay, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            cls._current_proc = proc
            cls.state = "playing"
        proc.wait()
        with cls._proc_lock:
            if cls._current_proc is proc:
                cls._current_proc = None

    @classmethod
    def _play_in_app(cls, wav: bytes, generation: int):
        """mobile has no aplay, play the wav bytes with flet's Audio service instead"""
        import flet_audio as fta

        logger.debug("playback speech in app")
        done = threading.Event()

        def on_state_change(e):
            if e.state in (fta.AudioState.COMPLETED, fta.AudioState.STOPPED):
                done.set()

        audio = fta.Audio(src=wav, autoplay=True, on_state_change=on_state_change)
        with cls._proc_lock:
            if generation != cls._generation:
                return
            cls._current_audio, cls._audio_done = audio, done
            cls.state = "playing"
        try:
            done.wait(timeout=600)  # blocks only this background thread
        finally:
            with cls._proc_lock:
                if cls._current_audio is audio:
                    cls._current_audio, cls._audio_done = None, None
            if cls._is_attached(audio):
                cls._page.run_task(audio.release)

    @staticmethod
    def _is_attached(audio) -> bool:
        try:
            return audio.page is not None
        except RuntimeError:
            return False
