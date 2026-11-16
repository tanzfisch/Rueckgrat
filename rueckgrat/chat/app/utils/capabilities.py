import weakref
from typing import Callable

import flet as ft

from app.common import get_logger
logger = get_logger()


class Capabilities:
    """
    What the system can do right now, as the hub tells it with every heartbeat (its /health, every 10 s): "llm", "tts",
    "stt", "image", "decision", "embedding", "internet" -> bool. Only the llm is mandatory, the app shows a feature only
    while what it needs is there. Unknown (not asked yet, an older hub) counts as there, so nothing is hidden by mistake.

    bind(control, "tts") keeps a control visible only while tts is there, live. A page that has to do more when something
    goes away (switch the mic off, stop speaking) listens: listener(lost) with the names that are gone.

    expected: what the system is set up for (configured on the hub, the internet always). missing() are the expected ones
    that are not available now (the connection banner shows them), a capability that is not installed is never missing.
    """
    _state: dict[str, bool] = {}
    _expected: list[str] = []
    _bound: "weakref.WeakKeyDictionary[ft.Control, tuple]" = weakref.WeakKeyDictionary()   # control -> (names, shown_when)
    _listeners: list[Callable[[set], None]] = []

    @classmethod
    def has(cls, *names: str) -> bool:
        return all(cls._state.get(name, True) for name in names)

    @classmethod
    def missing(cls) -> list[str]:
        """the expected capabilities that are not available now, in the hub's order"""
        return [name for name in cls._expected if not cls.has(name)]

    @classmethod
    def bind(cls, control: ft.Control, *names: str, available: bool = True) -> ft.Control:
        """control is visible while all names are there. available=False: while one of them is missing (a notice). returns control"""
        cls._bound[control] = (names, available)
        control.visible = cls.has(*names) == available
        return control

    @classmethod
    def listen(cls, listener: Callable[[set], None]):
        if listener not in cls._listeners:
            cls._listeners.append(listener)

    @classmethod
    def unlisten(cls, listener: Callable[[set], None]):
        if listener in cls._listeners:
            cls._listeners.remove(listener)

    @classmethod
    def update(cls, state, expected=None) -> None:
        """the hub's capabilities (None, e.g. an older hub: nothing changes) and the expected ones (None: unknown, nothing
        counts as missing). shows / hides the bound controls and tells the listeners what is gone"""
        if not isinstance(state, dict):
            return
        state = {str(name): ok for name, ok in state.items() if isinstance(ok, bool)}    # other keys are not capabilities
        expected = [str(name) for name in expected] if isinstance(expected, list) else []
        if state == cls._state and expected == cls._expected:
            return
        cls._expected = expected
        had = {name for name in set(cls._state) | set(state) if cls.has(name)}
        cls._state = state
        lost = {name for name in had if not cls.has(name)}
        logger.info(f"capabilities: not available {sorted(name for name, ok in state.items() if not ok) or 'none'}")
        for control, (names, available) in list(cls._bound.items()):
            visible = cls.has(*names) == available
            if control.visible != visible:
                control.visible = visible
                try:
                    control.update()
                except Exception:
                    pass    # not on a page (anymore), it shows the right state when it is
        for listener in list(cls._listeners):
            try:
                listener(lost)
            except Exception as e:
                logger.error(f"capability listener {listener!r} failed: {e!r}")
