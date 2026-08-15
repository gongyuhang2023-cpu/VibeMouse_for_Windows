from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from vibemouse.config.schema import (
    AppConfig,
    build_default_config_document,
    config_document_to_app_config,
)
from vibemouse.core.transcriber import (
    Transcriber,
    _FasterWhisperBackend,
    apply_corrections,
    build_vocabulary_prompt,
)


def _config(**overrides: object) -> AppConfig:
    base = config_document_to_app_config(build_default_config_document())
    return replace(base, **overrides)  # type: ignore[arg-type]


class ApplyCorrectionsTests(unittest.TestCase):
    def test_rewrites_a_known_mis_transcription(self) -> None:
        self.assertEqual(
            apply_corrections("先做施实验再说", {"施实验": "湿实验"}),
            "先做湿实验再说",
        )

    def test_longest_key_wins_over_a_shorter_overlapping_key(self) -> None:
        # "实验" would otherwise consume the prefix that "施实验" needs to match.
        corrections = {"实验": "experiment", "施实验": "湿实验"}
        self.assertEqual(
            apply_corrections("施实验", corrections),
            "湿实验",
        )

    def test_applies_every_matching_entry(self) -> None:
        text = "propage 的滴度低度都要测"
        corrections = {"propage": "prophage", "低度": "滴度"}
        self.assertEqual(
            apply_corrections(text, corrections),
            "prophage 的滴度滴度都要测",
        )

    def test_a_replacement_is_not_rewritten_by_another_entry(self) -> None:
        # Emitted text must not be re-scanned, or "低度" would cascade to "titer".
        corrections = {"低度": "滴度", "滴度": "titer"}
        self.assertEqual(apply_corrections("低度", corrections), "滴度")
        self.assertEqual(apply_corrections("滴度", corrections), "titer")

    def test_empty_replacement_deletes_the_phrase(self) -> None:
        self.assertEqual(apply_corrections("嗯那个好的", {"嗯那个": ""}), "好的")

    def test_returns_text_unchanged_without_corrections(self) -> None:
        self.assertEqual(apply_corrections("原文", {}), "原文")

    def test_handles_empty_text(self) -> None:
        self.assertEqual(apply_corrections("", {"a": "b"}), "")


class BuildVocabularyPromptTests(unittest.TestCase):
    def test_returns_none_without_terms(self) -> None:
        self.assertIsNone(build_vocabulary_prompt((), "zh"))

    def test_builds_a_chinese_prompt_by_default(self) -> None:
        prompt = build_vocabulary_prompt(("prophage", "湿实验"), "zh")
        assert prompt is not None
        self.assertIn("prophage、湿实验", prompt)
        self.assertTrue(prompt.endswith("。"))

    def test_builds_an_english_prompt_for_english_language(self) -> None:
        prompt = build_vocabulary_prompt(("prophage", "phage"), "en")
        assert prompt is not None
        self.assertIn("prophage, phage", prompt)

    def test_auto_language_uses_the_chinese_prompt(self) -> None:
        prompt = build_vocabulary_prompt(("phage",), "auto")
        assert prompt is not None
        self.assertIn("专有名词", prompt)


class TranscriberDispatchTests(unittest.TestCase):
    def test_unknown_backend_lists_the_supported_options(self) -> None:
        subject = Transcriber(_config(transcriber_backend="whisper.cpp"))
        with self.assertRaises(RuntimeError) as caught:
            subject.prewarm()
        message = str(caught.exception)
        self.assertIn("funasr_onnx", message)
        self.assertIn("faster_whisper", message)

    def test_faster_whisper_backend_is_selected(self) -> None:
        subject = Transcriber(_config(transcriber_backend="faster_whisper"))
        with patch.object(Transcriber, "_build_faster_whisper_backend") as build:
            subject.prewarm()
        build.assert_called_once()

    def test_deprecated_backend_aliases_fall_back_to_funasr_onnx(self) -> None:
        for alias in ("auto", "funasr"):
            with self.subTest(alias=alias):
                subject = Transcriber(_config(transcriber_backend=alias))
                with patch.object(Transcriber, "_build_funasr_onnx_backend") as build:
                    subject.prewarm()
                build.assert_called_once()

    def test_transcribe_applies_corrections_to_backend_output(self) -> None:
        subject = Transcriber(_config(corrections={"施实验": "湿实验"}))

        class _StubBackend:
            device_in_use = "cpu"

            def transcribe(self, audio_path: Path) -> str:
                return "先做施实验"

        setattr(subject, "_transcriber", _StubBackend())
        self.assertEqual(subject.transcribe(Path("clip.wav")), "先做湿实验")


class FasterWhisperBackendTests(unittest.TestCase):
    @staticmethod
    def _backend(config: AppConfig) -> _FasterWhisperBackend:
        # Bypass __init__ so the test never touches a real model.
        backend = object.__new__(_FasterWhisperBackend)
        setattr(backend, "_config", config)
        return backend

    def test_rejects_a_sensevoice_model_id(self) -> None:
        backend = self._backend(_config(model_name="iic/SenseVoiceSmall"))
        with self.assertRaises(RuntimeError) as caught:
            backend._resolve_model_name()
        self.assertIn("large-v3", str(caught.exception))

    def test_accepts_a_whisper_model_name(self) -> None:
        backend = self._backend(_config(model_name="large-v3"))
        self.assertEqual(backend._resolve_model_name(), "large-v3")

    def test_cuda_ordinal_is_reduced_to_a_bare_device_name(self) -> None:
        self.assertEqual(_FasterWhisperBackend._resolve_device("cuda:1"), "cuda")
        self.assertEqual(_FasterWhisperBackend._resolve_device("CUDA"), "cuda")
        self.assertEqual(_FasterWhisperBackend._resolve_device("cpu"), "cpu")
        self.assertEqual(_FasterWhisperBackend._resolve_device(""), "cpu")

    def test_auto_language_becomes_none_for_whisper(self) -> None:
        backend = self._backend(_config(language="auto"))
        self.assertIsNone(backend._resolve_language())

    def test_explicit_language_is_passed_through_lowercased(self) -> None:
        backend = self._backend(_config(language="ZH"))
        self.assertEqual(backend._resolve_language(), "zh")


if __name__ == "__main__":
    unittest.main()
