from __future__ import annotations

import os
import sys
from collections.abc import Mapping
from typing import Protocol


_TERMINAL_CLASS_HINTS: set[str] = {
    "foot",
    "kitty",
    "alacritty",
    "wezterm",
    "ghostty",
    "gnome-terminal",
    "gnome-terminal-server",
    "konsole",
    "tilix",
    "xterm",
    "terminator",
    "xfce4-terminal",
    "urxvt",
    "st",
    "tabby",
    "hyper",
    "warp",
    "windowsterminal",
    "wt",
}

_TERMINAL_TITLE_HINTS: set[str] = {
    "terminal",
    "tmux",
    "bash",
    "zsh",
    "fish",
    "powershell",
    "cmd.exe",
}


def is_terminal_window_payload(payload: Mapping[str, object]) -> bool:
    window_class = str(payload.get("class", "")).lower()
    initial_class = str(payload.get("initialClass", "")).lower()
    title = str(payload.get("title", "")).lower()

    if any(
        hint in window_class or hint in initial_class for hint in _TERMINAL_CLASS_HINTS
    ):
        return True

    return any(hint in title for hint in _TERMINAL_TITLE_HINTS)


def is_browser_window_payload(payload: Mapping[str, object]) -> bool:
    return False


class SystemIntegration(Protocol):
    @property
    def is_hyprland(self) -> bool: ...

    def send_shortcut(self, *, mod: str, key: str) -> bool: ...

    def active_window(self) -> dict[str, object] | None: ...

    def cursor_position(self) -> tuple[int, int] | None: ...

    def move_cursor(self, *, x: int, y: int) -> bool: ...

    def switch_workspace(self, direction: str) -> bool: ...

    def is_text_input_focused(self) -> bool | None: ...

    def send_enter_via_accessibility(self) -> bool | None: ...

    def is_terminal_window_active(self) -> bool | None: ...

    def paste_shortcuts(
        self, *, terminal_active: bool
    ) -> tuple[tuple[str, str], ...]: ...


class NoopSystemIntegration:
    @property
    def is_hyprland(self) -> bool:
        return False

    def send_shortcut(self, *, mod: str, key: str) -> bool:
        return False

    def active_window(self) -> dict[str, object] | None:
        return None

    def cursor_position(self) -> tuple[int, int] | None:
        return None

    def move_cursor(self, *, x: int, y: int) -> bool:
        return False

    def switch_workspace(self, direction: str) -> bool:
        return False

    def is_text_input_focused(self) -> bool | None:
        return None

    def send_enter_via_accessibility(self) -> bool | None:
        return None

    def is_terminal_window_active(self) -> bool | None:
        return None

    def paste_shortcuts(self, *, terminal_active: bool) -> tuple[tuple[str, str], ...]:
        return ()


class WindowsSystemIntegration:
    """Minimal Windows platform integration.

    On Windows we always assume text input is focused and use pynput for
    keyboard simulation. No Hyprland, no AT-SPI.
    """

    @property
    def is_hyprland(self) -> bool:
        return False

    def send_shortcut(self, *, mod: str, key: str) -> bool:
        return False

    def active_window(self) -> dict[str, object] | None:
        return None

    def cursor_position(self) -> tuple[int, int] | None:
        return None

    def move_cursor(self, *, x: int, y: int) -> bool:
        return False

    def switch_workspace(self, direction: str) -> bool:
        return False

    def is_text_input_focused(self) -> bool | None:
        # On Windows, always assume text input is focused.
        # We use clipboard paste as the primary injection method anyway.
        return True

    def send_enter_via_accessibility(self) -> bool | None:
        return None

    def is_terminal_window_active(self) -> bool | None:
        return None

    def paste_shortcuts(self, *, terminal_active: bool) -> tuple[tuple[str, str], ...]:
        return (("CTRL", "V"),)


def create_system_integration(
    *,
    env: Mapping[str, str] | None = None,
    platform_name: str | None = None,
) -> SystemIntegration:
    platform = platform_name if platform_name is not None else sys.platform

    if platform == "win32":
        return WindowsSystemIntegration()

    # On Linux, check for Hyprland
    source = env if env is not None else os.environ
    desktop = source.get("XDG_CURRENT_DESKTOP", "")
    if "hyprland" in desktop.lower() or source.get("HYPRLAND_INSTANCE_SIGNATURE"):
        # Hyprland integration not supported in this Windows-focused fork
        pass

    return NoopSystemIntegration()


def load_atspi_module() -> object | None:
    """AT-SPI is Linux-only; return None on Windows."""
    if sys.platform == "win32":
        return None
    try:
        import importlib
        gi = importlib.import_module("gi")
        getattr(gi, "require_version")("Atspi", "2.0")
        atspi_repo = importlib.import_module("gi.repository")
        return getattr(atspi_repo, "Atspi")
    except Exception:
        return None


def probe_text_input_focus_via_atspi(*, timeout_s: float = 1.5) -> bool:
    """AT-SPI probe — always returns False on Windows."""
    return False


def probe_send_enter_via_atspi(
    *, atspi_module: object | None = None, lazy_load: bool = True
) -> bool:
    """AT-SPI enter — always returns False on Windows."""
    return False
