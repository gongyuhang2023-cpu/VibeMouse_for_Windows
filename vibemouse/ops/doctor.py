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
    checks.append(_check_vocabulary(config))

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


# faster-whisper truncates the prompt and the hotword string to
# WhisperModel.max_length // 2 - 1 tokens each, silently, in get_prompt().
_PROMPT_TOKEN_BUDGET = 448 // 2 - 1

# Measured on this project's own test sets: term recall keeps degrading as
# unrelated terms are added long before the token budget runs out, because every
# extra term dilutes the bias on the rest. Going from 8 relevant terms to 29
# cost 41/42 -> 37/42 on the audio the 8 were chosen for. Terms still earn their
# place when they are actually spoken (0 -> 38/38 on tooling audio), so this is a
# nudge to prune what you no longer say, not a hard ceiling.
_TERM_COUNT_ADVISORY = 30


def _check_vocabulary(config: AppConfig | None) -> DoctorCheck:
    if config is None:
        return DoctorCheck(
            name="vocabulary",
            status="warn",
            detail="skipped: config did not load",
        )

    terms = config.vocabulary_terms
    corrections = config.corrections
    if not terms and not corrections:
        return DoctorCheck(
            name="vocabulary",
            status="ok",
            detail="no vocabulary configured",
        )

    summary = f"{len(terms)} terms, {len(corrections)} corrections"

    if terms and config.transcriber_backend != "faster_whisper":
        return DoctorCheck(
            name="vocabulary",
            status="warn",
            detail=(
                f"{summary}; backend {config.transcriber_backend!r} ignores "
                "vocabulary.terms (only faster_whisper can bias decoding). "
                "corrections still apply."
            ),
        )

    tokens = _count_prompt_tokens(config)
    if tokens is None:
        budget = f"prompt budget unverified (tokenizer unavailable)"
    elif tokens > _PROMPT_TOKEN_BUDGET:
        return DoctorCheck(
            name="vocabulary",
            status="fail",
            detail=(
                f"{summary}; prompt is {tokens} tokens but faster-whisper "
                f"truncates at {_PROMPT_TOKEN_BUDGET} -- terms are being dropped "
                "silently. Move terms whose mis-transcription is not a real word "
                "into vocabulary.corrections, which has no size limit."
            ),
        )
    else:
        budget = f"prompt {tokens}/{_PROMPT_TOKEN_BUDGET} tokens"

    if len(terms) > _TERM_COUNT_ADVISORY:
        return DoctorCheck(
            name="vocabulary",
            status="warn",
            detail=(
                f"{summary}; {budget}. Above ~{_TERM_COUNT_ADVISORY} terms the "
                "prompt dilutes: every term weakens the bias on the others. "
                "Prune terms you no longer say."
            ),
        )

    return DoctorCheck(name="vocabulary", status="ok", detail=f"{summary}; {budget}")


def _count_prompt_tokens(config: AppConfig) -> int | None:
    """Token cost of the vocabulary prompt, or None if it cannot be measured."""
    from vibemouse.core.transcriber import build_vocabulary_prompt

    prompt = build_vocabulary_prompt(config.vocabulary_terms, config.language)
    if not prompt:
        return 0

    try:
        hub = importlib.import_module("huggingface_hub")
        tokenizers = importlib.import_module("tokenizers")
        model_dir = hub.snapshot_download(
            _tokenizer_repo(config.model_name),
            allow_patterns=["tokenizer.json"],
            local_files_only=True,
        )
        tokenizer = tokenizers.Tokenizer.from_file(f"{model_dir}/tokenizer.json")
    except Exception:
        return None

    return len(tokenizer.encode(" " + prompt.strip(), add_special_tokens=False).ids)


def _tokenizer_repo(model_name: str) -> str:
    from faster_whisper.utils import _MODELS

    return _MODELS.get(model_name, f"Systran/faster-whisper-{model_name}")


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
