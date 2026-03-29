from __future__ import annotations

import importlib
import logging
import sys
import time
from typing import Protocol, cast

import pyperclip

_LOG = logging.getLogger(__name__)


class TextOutput:
    def __init__(self) -> None:
        try:
            keyboard_module = importlib.import_module("pynput.keyboard")
        except Exception as error:
            raise RuntimeError(
                f"Failed to load keyboard control dependencies: {error}"
            ) from error

        controller_ctor = cast(
            _ControllerCtor,
            getattr(cast(object, keyboard_module), "Controller"),
        )
        key_holder = cast(
            _KeyHolder,
            getattr(cast(object, keyboard_module), "Key"),
        )
        self._kb: _KeyboardController = controller_ctor()
        self._enter_key: object = key_holder.enter
        self._ctrl_key: object = key_holder.ctrl
        self._shift_key: object = key_holder.shift
        self._alt_key: object = key_holder.alt

    def send_enter(self, *, mode: str = "enter") -> None:
        normalized = mode.strip().lower()
        if normalized == "none":
            return
        if normalized == "enter":
            self._tap_key(self._enter_key)
            return
        if normalized == "ctrl_enter":
            self._tap_modified_key(self._ctrl_key, self._enter_key)
            return
        if normalized == "shift_enter":
            self._tap_modified_key(self._shift_key, self._enter_key)
            return
        raise ValueError(f"Unsupported enter mode: {mode!r}")

    def inject_or_clipboard(self, text: str, *, auto_paste: bool = False) -> str:
        normalized = text.strip()
        if not normalized:
            return "empty"

        pyperclip.copy(normalized)

        if sys.platform == "win32" or auto_paste:
            try:
                self._safe_paste()
                return "pasted"
            except Exception as error:
                _LOG.warning("Paste failed, text is in clipboard: %s", error)
                return "clipboard"

        return "clipboard"

    def _safe_paste(self) -> None:
        """Simulate Ctrl+V with aggressive modifier key cleanup."""
        # Step 1: Release ALL modifier keys first to ensure clean state
        self._release_all_modifiers()
        time.sleep(0.05)

        # Step 2: Press Ctrl+V
        try:
            self._kb.press(self._ctrl_key)
            time.sleep(0.03)
            self._kb.press("v")
            time.sleep(0.03)
            self._kb.release("v")
            time.sleep(0.03)
            self._kb.release(self._ctrl_key)
        except Exception:
            pass

        # Step 3: Force release ALL modifiers again to prevent stuck keys
        time.sleep(0.05)
        self._release_all_modifiers()

    def _release_all_modifiers(self) -> None:
        """Force release all modifier keys to prevent stuck key state."""
        for key in (self._ctrl_key, self._shift_key, self._alt_key):
            try:
                self._kb.release(key)
            except Exception:
                pass

    def _tap_key(self, key: object) -> None:
        self._kb.press(key)
        time.sleep(0.012)
        self._kb.release(key)

    def _tap_modified_key(self, modifier: object, key: object) -> None:
        self._release_all_modifiers()
        try:
            self._kb.press(modifier)
            time.sleep(0.02)
            self._kb.press(key)
            time.sleep(0.02)
            self._kb.release(key)
            time.sleep(0.02)
            self._kb.release(modifier)
        except Exception:
            pass
        self._release_all_modifiers()


class _KeyboardController(Protocol):
    def press(self, key: object) -> None: ...

    def release(self, key: object) -> None: ...

    def type(self, text: str) -> None: ...


class _ControllerCtor(Protocol):
    def __call__(self) -> _KeyboardController: ...


class _KeyHolder(Protocol):
    enter: object
    ctrl: object
    shift: object
    alt: object
