from __future__ import annotations

import importlib
import logging
import os
import re
import site
import sys
from collections.abc import Iterable
from pathlib import Path
from threading import Lock
from typing import Protocol, cast

from vibemouse.config import AppConfig

_LOG = logging.getLogger(__name__)

_SUPPORTED_BACKENDS = ("funasr_onnx", "faster_whisper")


class Transcriber:
    def __init__(self, config: AppConfig) -> None:
        self._config: AppConfig = config
        self._transcriber: _TranscriberProtocol | None = None
        self._transcriber_lock: Lock = Lock()
        self.device_in_use: str = config.device
        self.backend_in_use: str = "unknown"

    def transcribe(self, audio_path: Path) -> str:
        self._ensure_transcriber_loaded()
        if self._transcriber is None:
            raise RuntimeError("Transcriber is not initialized")
        text = self._transcriber.transcribe(audio_path)
        return apply_corrections(text, self._config.corrections)

    def prewarm(self) -> None:
        self._ensure_transcriber_loaded()

    def _ensure_transcriber_loaded(self) -> None:
        if self._transcriber is not None:
            return

        with self._transcriber_lock:
            if self._transcriber is not None:
                return

            backend = self._config.transcriber_backend
            if backend in {"auto", "funasr"}:
                _LOG.warning(
                    "Backend %r is deprecated; using 'funasr_onnx' instead", backend
                )
                backend = "funasr_onnx"

            if backend == "funasr_onnx":
                self._build_funasr_onnx_backend()
                return
            if backend == "faster_whisper":
                self._build_faster_whisper_backend()
                return

            options = ", ".join(_SUPPORTED_BACKENDS)
            raise RuntimeError(
                f"Unsupported backend {backend!r}. Use one of: {options}."
            )

    def _build_funasr_onnx_backend(self) -> None:
        backend = _FunASRONNXBackend(self._config)
        self._transcriber = backend
        self.device_in_use = backend.device_in_use
        self.backend_in_use = "funasr_onnx"

    def _build_faster_whisper_backend(self) -> None:
        backend = _FasterWhisperBackend(self._config)
        self._transcriber = backend
        self.device_in_use = backend.device_in_use
        self.backend_in_use = "faster_whisper"


def apply_corrections(text: str, corrections: dict[str, str]) -> str:
    """Rewrite known mis-transcriptions in the finished text.

    Single left-to-right pass, longest key first. Two properties matter here and
    neither survives a chain of str.replace() calls:

    * Longest match wins, so a table holding both "实验" and "湿实验" does not let
      the shorter key consume the prefix the longer one needs.
    * Text already emitted is never re-scanned, so one entry's replacement cannot
      be rewritten by another entry -- {"低度": "滴度", "滴度": "titer"} must not
      turn "低度" into "titer".
    """
    if not text or not corrections:
        return text

    keys = sorted(corrections, key=len, reverse=True)
    parts: list[str] = []
    index = 0
    while index < len(text):
        for key in keys:
            if text.startswith(key, index):
                parts.append(corrections[key])
                index += len(key)
                break
        else:
            parts.append(text[index])
            index += 1
    return "".join(parts)


def build_vocabulary_prompt(terms: tuple[str, ...], language: str) -> str | None:
    """Render the vocabulary as Whisper prompt text that biases decoding."""
    if not terms:
        return None
    if language.strip().lower().startswith("en"):
        return "Transcript mentioning these terms: " + ", ".join(terms) + "."
    return "以下是普通话转写，可能包含这些专有名词：" + "、".join(terms) + "。"


class _FunASRONNXBackend:
    def __init__(self, config: AppConfig) -> None:
        self._config: AppConfig = config
        self._model: _ONNXSenseVoiceModel | None = None
        self._postprocess: _PostprocessFn | None = None
        self._load_lock: Lock = Lock()
        self.device_in_use: str = "cpu"
        self._ensure_model_loaded()

    def transcribe(self, audio_path: Path) -> str:
        if self._model is None:
            raise RuntimeError("funasr_onnx SenseVoice model is not initialized")
        if self._postprocess is None:
            raise RuntimeError("funasr postprocess function is not initialized")

        textnorm = "withitn" if self._config.use_itn else "woitn"
        result = self._model(
            str(audio_path),
            language=self._config.language,
            textnorm=textnorm,
        )
        if not result:
            return ""

        raw_text = result[0]
        return self._postprocess(raw_text).strip()

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return

        with self._load_lock:
            if self._model is not None:
                return
            try:
                SenseVoiceSmall = self._load_onnx_class()
                postprocess = self._load_postprocess()
            except Exception as error:
                raise RuntimeError(
                    "funasr_onnx backend requires funasr-onnx package"
                ) from error

            requested_path = self._resolve_onnx_model_dir()
            self._ensure_tokenizer_file(requested_path)
            device_id = self._resolve_onnx_device_id(self._config.device)

            try:
                model = SenseVoiceSmall(
                    model_dir=str(requested_path),
                    batch_size=1,
                    device_id=device_id,
                    quantize=True,
                    cache_dir=None,
                )
                self._model = model
                self._postprocess = postprocess
                self.device_in_use = self._resolve_device_label(self._config.device)
                _LOG.info(
                    "Loaded funasr_onnx model: device_in_use=%s model=%s",
                    self.device_in_use,
                    requested_path,
                )
                return
            except Exception as primary_error:
                if not self._config.fallback_to_cpu:
                    raise RuntimeError(
                        f"Failed to load funasr_onnx backend on {self._config.device}: {primary_error}"
                    ) from primary_error

            try:
                model = SenseVoiceSmall(
                    model_dir=str(requested_path),
                    batch_size=1,
                    device_id="-1",
                    quantize=True,
                    cache_dir=None,
                )
            except Exception as cpu_error:
                raise RuntimeError(
                    f"Failed to load funasr_onnx backend on {self._config.device} and cpu fallback: {cpu_error}"
                ) from cpu_error

            self._model = model
            self._postprocess = postprocess
            self.device_in_use = "cpu"
            _LOG.warning(
                "Loaded funasr_onnx model with CPU fallback after device load failure"
            )

    def _resolve_onnx_model_dir(self) -> Path:
        raw_model = self._config.model_name
        canonical_model = raw_model
        if raw_model == "iic/SenseVoiceSmall":
            canonical_model = "iic/SenseVoiceSmall-onnx"

        if canonical_model.startswith("iic/"):
            return self._download_modelscope_snapshot(canonical_model)

        path_candidate = Path(canonical_model)
        if not path_candidate.exists():
            return path_candidate

        if self._contains_onnx_model(path_candidate):
            return path_candidate

        raise RuntimeError(
            f"ONNX model directory {path_candidate} exists but model_quant.onnx/model.onnx is missing"
        )

    @staticmethod
    def _contains_onnx_model(model_dir: Path) -> bool:
        return (model_dir / "model_quant.onnx").exists() or (
            model_dir / "model.onnx"
        ).exists()

    @staticmethod
    def _download_modelscope_snapshot(model_id: str) -> Path:
        try:
            snapshot_mod = importlib.import_module("modelscope.hub.snapshot_download")
        except Exception as error:
            raise RuntimeError(
                "modelscope is required to download ONNX model snapshots"
            ) from error

        snapshot_download = cast(
            _SnapshotDownloadFn,
            getattr(snapshot_mod, "snapshot_download"),
        )
        snapshot_path = snapshot_download(model_id)
        model_dir = Path(snapshot_path)
        if not model_dir.exists():
            raise RuntimeError(f"Downloaded model path does not exist: {snapshot_path}")
        if not _FunASRONNXBackend._contains_onnx_model(model_dir):
            raise RuntimeError(
                f"Downloaded model {model_id} missing model_quant.onnx/model.onnx"
            )
        return model_dir

    @staticmethod
    def _resolve_onnx_device_id(device: str) -> str:
        normalized = device.strip().lower()
        if normalized == "cpu":
            return "-1"
        if normalized.startswith("cuda"):
            parts = normalized.split(":", 1)
            return parts[1] if len(parts) > 1 and parts[1] else "0"
        return "-1"

    @staticmethod
    def _resolve_device_label(device: str) -> str:
        normalized = device.strip().lower()
        if normalized.startswith("cuda"):
            return normalized
        return "cpu"

    def _ensure_tokenizer_file(self, model_dir: Path) -> None:
        target = model_dir / "chn_jpn_yue_eng_ko_spectok.bpe.model"
        if target.exists():
            return

        fallback = (
            Path.home()
            / ".cache/modelscope/hub/models/iic/SenseVoiceSmall/chn_jpn_yue_eng_ko_spectok.bpe.model"
        )
        if fallback.exists():
            model_dir.mkdir(parents=True, exist_ok=True)
            _ = target.write_bytes(fallback.read_bytes())
            return

        raise RuntimeError(
            "Tokenizer file chn_jpn_yue_eng_ko_spectok.bpe.model is missing and no fallback was found"
        )

    @staticmethod
    def _load_onnx_class() -> _ONNXSenseVoiceCtor:
        module = importlib.import_module("funasr_onnx")
        return cast(_ONNXSenseVoiceCtor, getattr(module, "SenseVoiceSmall"))

    @staticmethod
    def _load_postprocess() -> _PostprocessFn:
        try:
            post_module = importlib.import_module("funasr.utils.postprocess_utils")
            return cast(
                _PostprocessFn,
                getattr(post_module, "rich_transcription_postprocess"),
            )
        except Exception:
            try:
                post_module = importlib.import_module(
                    "funasr_onnx.utils.postprocess_utils"
                )
                return cast(
                    _PostprocessFn,
                    getattr(post_module, "rich_transcription_postprocess"),
                )
            except Exception:
                return _strip_sensevoice_control_tokens


class _FasterWhisperBackend:
    def __init__(self, config: AppConfig) -> None:
        self._config: AppConfig = config
        self._model: _WhisperModel | None = None
        self._load_lock: Lock = Lock()
        self._prompt: str | None = build_vocabulary_prompt(
            config.vocabulary_terms, config.language
        )
        self._hotwords: str | None = (
            " ".join(config.vocabulary_terms) if config.vocabulary_terms else None
        )
        self.device_in_use: str = "cpu"
        self._ensure_model_loaded()

    def transcribe(self, audio_path: Path) -> str:
        if self._model is None:
            raise RuntimeError("faster_whisper model is not initialized")

        segments, _info = self._model.transcribe(
            str(audio_path),
            language=self._resolve_language(),
            beam_size=self._config.whisper_beam_size,
            initial_prompt=self._prompt,
            hotwords=self._hotwords,
            vad_filter=self._config.enable_vad,
            condition_on_previous_text=False,
        )
        # transcribe() returns a generator; decoding happens as it is consumed.
        return "".join(segment.text for segment in segments).strip()

    def _resolve_language(self) -> str | None:
        language = self._config.language.strip().lower()
        return None if language in {"", "auto"} else language

    def _ensure_model_loaded(self) -> None:
        if self._model is not None:
            return

        with self._load_lock:
            if self._model is not None:
                return

            _register_cuda_dll_directories()
            try:
                whisper_model = self._load_whisper_class()
            except Exception as error:
                raise RuntimeError(
                    "faster_whisper backend requires the faster-whisper package"
                ) from error

            model_name = self._resolve_model_name()
            device = self._resolve_device(self._config.device)
            compute_type = self._config.whisper_compute_type

            try:
                self._model = whisper_model(
                    model_name,
                    device=device,
                    compute_type=compute_type,
                )
                self.device_in_use = device
                _LOG.info(
                    "Loaded faster_whisper model: device_in_use=%s model=%s "
                    "compute_type=%s vocabulary_terms=%d",
                    device,
                    model_name,
                    compute_type,
                    len(self._config.vocabulary_terms),
                )
                return
            except Exception as primary_error:
                if device == "cpu" or not self._config.fallback_to_cpu:
                    raise RuntimeError(
                        f"Failed to load faster_whisper on {device}: {primary_error}"
                    ) from primary_error
                _LOG.warning(
                    "faster_whisper failed to load on %s (%s); falling back to CPU",
                    device,
                    primary_error,
                )

            # float16 is a GPU compute type; CPU needs an int8 variant instead.
            cpu_compute_type = "int8" if "float16" in compute_type else compute_type
            try:
                self._model = whisper_model(
                    model_name,
                    device="cpu",
                    compute_type=cpu_compute_type,
                )
            except Exception as cpu_error:
                raise RuntimeError(
                    f"Failed to load faster_whisper on {device} and cpu fallback: "
                    f"{cpu_error}"
                ) from cpu_error

            self.device_in_use = "cpu"
            _LOG.warning(
                "Loaded faster_whisper with CPU fallback (compute_type=%s)",
                cpu_compute_type,
            )

    def _resolve_model_name(self) -> str:
        model_name = self._config.model_name.strip()
        if model_name.startswith("iic/"):
            raise RuntimeError(
                f"transcriber.model_name {model_name!r} is a SenseVoice/ModelScope id "
                "and cannot be used with the faster_whisper backend. Set it to a "
                "Whisper model such as 'large-v3', 'large-v3-turbo', or a local "
                "CTranslate2 model directory."
            )
        return model_name

    @staticmethod
    def _resolve_device(device: str) -> str:
        normalized = device.strip().lower()
        # faster-whisper takes a bare device name; CUDA ordinals are a separate arg.
        return "cuda" if normalized.startswith("cuda") else normalized or "cpu"

    @staticmethod
    def _load_whisper_class() -> _WhisperModelCtor:
        module = importlib.import_module("faster_whisper")
        return cast(_WhisperModelCtor, getattr(module, "WhisperModel"))


def _register_cuda_dll_directories() -> None:
    """Make pip-installed CUDA runtime libraries loadable on Windows.

    nvidia-cublas-cu12 / nvidia-cudnn-cu12 drop their DLLs under
    site-packages/nvidia/*/bin, which is not on PATH. CTranslate2 resolves them with
    a bare LoadLibrary call, so it follows the standard search order and ignores
    os.add_dll_directory() -- PATH is what actually makes the load succeed.
    """
    if sys.platform != "win32":
        return

    roots: list[Path] = []
    try:
        nvidia = importlib.import_module("nvidia")
        roots.extend(Path(entry) for entry in getattr(nvidia, "__path__", []))
    except Exception:
        roots.extend(Path(entry) / "nvidia" for entry in site.getsitepackages())

    bin_dirs: list[str] = []
    for root in roots:
        if root.is_dir():
            bin_dirs.extend(str(path) for path in sorted(root.glob("*/bin")))
    if not bin_dirs:
        return

    current_path = os.environ.get("PATH", "")
    missing = [path for path in bin_dirs if path not in current_path]
    if missing:
        os.environ["PATH"] = os.pathsep.join([*missing, current_path])
    for path in bin_dirs:
        try:
            os.add_dll_directory(path)
        except OSError:
            _LOG.debug("Could not register DLL directory %s", path)
    _LOG.debug("Registered %d CUDA DLL directories", len(bin_dirs))


_SENSEVOICE_CONTROL_TOKEN_RE = re.compile(r"<\|[^|>]+\|>")


def _strip_sensevoice_control_tokens(text: str) -> str:
    cleaned = _SENSEVOICE_CONTROL_TOKEN_RE.sub("", text)
    return " ".join(cleaned.split()).strip()


class _TranscriberProtocol(Protocol):
    device_in_use: str

    def transcribe(self, audio_path: Path) -> str: ...


class _PostprocessFn(Protocol):
    def __call__(self, text: str) -> str: ...


class _ONNXSenseVoiceModel(Protocol):
    def __call__(
        self,
        wav_content: str,
        *,
        language: str,
        textnorm: str,
    ) -> list[str]: ...


class _ONNXSenseVoiceCtor(Protocol):
    def __call__(
        self,
        *,
        model_dir: str,
        batch_size: int,
        device_id: str,
        quantize: bool,
        cache_dir: str | None,
    ) -> _ONNXSenseVoiceModel: ...


class _SnapshotDownloadFn(Protocol):
    def __call__(self, model_id: str) -> str: ...


class _WhisperSegment(Protocol):
    text: str


class _WhisperModel(Protocol):
    def transcribe(
        self,
        audio: str,
        *,
        language: str | None,
        beam_size: int,
        initial_prompt: str | None,
        hotwords: str | None,
        vad_filter: bool,
        condition_on_previous_text: bool,
    ) -> tuple[Iterable[_WhisperSegment], object]: ...


class _WhisperModelCtor(Protocol):
    def __call__(
        self,
        model_size_or_path: str,
        *,
        device: str,
        compute_type: str,
    ) -> _WhisperModel: ...
