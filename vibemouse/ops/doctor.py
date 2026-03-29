from __future__ import annotations

import importlib
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from vibemouse.config import AppConfig, load_config


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    status: str
    detail: str


def run_doctor(*, apply_fixes: bool = False) -> int:
    checks: list[DoctorCheck] = []

    config_check, config = _check_config_load()
    checks.append(config_check)
    checks.append(_check_audio_input(config))
    checks.append(_check_pynput())

    _print_checks(checks)

    fail_count = sum(1 for check in checks if check.status == "fail")
    warn_count = sum(1 for check in checks if check.status == "warn")
    print(f"Doctor summary: {len(checks)} checks, {fail_count} fail, {warn_count} warn")
    return 1 if fail_count else 0


def _check_config_load() -> tuple[DoctorCheck, AppConfig | None]:
    try:
        config = load_config()
    except Exception as error:
        return (
            DoctorCheck(
                name="config",
                status="fail",
                detail=f"failed to load config: {error}",
            ),
            None,
        )

    return (
        DoctorCheck(
            name="config",
            status="ok",
            detail=(
                "loaded "
                + f"front={config.front_button}, rear={config.rear_button}"
            ),
        ),
        config,
    )


def _check_audio_input(config: AppConfig | None) -> DoctorCheck:
    try:
        sounddevice = importlib.import_module("sounddevice")
    except Exception as error:
        return DoctorCheck(
            name="audio-input",
            status="fail",
            detail=f"cannot import sounddevice: {error}",
        )

    query_devices = getattr(sounddevice, "query_devices", None)
    if not callable(query_devices):
        return DoctorCheck(
            name="audio-input",
            status="fail",
            detail="sounddevice.query_devices is unavailable",
        )

    try:
        devices_obj = query_devices()
    except Exception as error:
        return DoctorCheck(
            name="audio-input",
            status="fail",
            detail=f"failed to query audio devices: {error}",
        )

    device_entries = _coerce_device_entries(devices_obj)
    if device_entries is None:
        return DoctorCheck(
            name="audio-input",
            status="warn",
            detail="unexpected audio device payload shape",
        )

    input_devices: list[Mapping[str, object]] = []
    for item in device_entries:
        max_inputs = _to_float(item.get("max_input_channels", 0.0))
        if max_inputs > 0:
            input_devices.append(item)
    if not input_devices:
        return DoctorCheck(
            name="audio-input",
            status="fail",
            detail="no input-capable microphone device detected",
        )

    default_index = _read_default_input_device_index(sounddevice)
    check_input_settings = getattr(sounddevice, "check_input_settings", None)
    if default_index is not None and callable(check_input_settings):
        sample_rate = float(config.sample_rate) if config is not None else 16000.0
        channels = config.channels if config is not None else 1
        try:
            _ = check_input_settings(
                device=default_index,
                channels=max(1, int(channels)),
                samplerate=sample_rate,
            )
        except Exception as error:
            return DoctorCheck(
                name="audio-input",
                status="warn",
                detail=f"default input exists but validation failed: {error}",
            )

    return DoctorCheck(
        name="audio-input",
        status="ok",
        detail=f"detected {len(input_devices)} input-capable device(s)",
    )


def _check_pynput() -> DoctorCheck:
    try:
        importlib.import_module("pynput.mouse")
        importlib.import_module("pynput.keyboard")
    except Exception as error:
        return DoctorCheck(
            name="pynput",
            status="fail",
            detail=f"cannot import pynput: {error}",
        )
    return DoctorCheck(
        name="pynput",
        status="ok",
        detail="pynput mouse and keyboard modules loaded",
    )


def _read_default_input_device_index(sounddevice: object) -> int | None:
    default_obj = getattr(sounddevice, "default", None)
    if default_obj is None:
        return None

    device_attr = getattr(default_obj, "device", None)
    if not isinstance(device_attr, tuple | list) or len(device_attr) < 1:
        return None

    raw_input_index = device_attr[0]
    if not isinstance(raw_input_index, int):
        return None
    if raw_input_index < 0:
        return None
    return raw_input_index


def _coerce_device_entries(devices_obj: object) -> list[Mapping[str, object]] | None:
    if isinstance(devices_obj, list):
        return [entry for entry in devices_obj if isinstance(entry, Mapping)]

    if isinstance(devices_obj, Iterable):
        entries: list[Mapping[str, object]] = []
        for entry in devices_obj:
            if isinstance(entry, Mapping):
                entries.append(entry)
        return entries

    return None


def _to_float(value: object) -> float:
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return 0.0
    return 0.0


def _print_checks(checks: list[DoctorCheck]) -> None:
    for check in checks:
        badge = {
            "ok": "[OK]",
            "warn": "[WARN]",
            "fail": "[FAIL]",
        }.get(check.status, "[INFO]")
        print(f"{badge} {check.name}: {check.detail}")
