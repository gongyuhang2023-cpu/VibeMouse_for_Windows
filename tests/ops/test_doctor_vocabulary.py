from __future__ import annotations

import unittest
from dataclasses import replace
from unittest.mock import patch

from vibemouse.config.schema import (
    AppConfig,
    build_default_config_document,
    config_document_to_app_config,
)
from vibemouse.ops.doctor import _check_vocabulary


def _config(**overrides: object) -> AppConfig:
    base = config_document_to_app_config(build_default_config_document())
    return replace(base, **overrides)  # type: ignore[arg-type]


class CheckVocabularyTests(unittest.TestCase):
    def test_reports_ok_when_no_vocabulary_is_configured(self) -> None:
        check = _check_vocabulary(_config())
        self.assertEqual(check.status, "ok")
        self.assertIn("no vocabulary", check.detail)

    def test_warns_when_config_is_unavailable(self) -> None:
        check = _check_vocabulary(None)
        self.assertEqual(check.status, "warn")

    def test_warns_that_terms_are_ignored_on_a_non_whisper_backend(self) -> None:
        check = _check_vocabulary(
            _config(
                transcriber_backend="funasr_onnx",
                vocabulary_terms=("phage",),
            )
        )
        self.assertEqual(check.status, "warn")
        self.assertIn("funasr_onnx", check.detail)
        self.assertIn("corrections still apply", check.detail)

    def test_corrections_alone_are_fine_on_any_backend(self) -> None:
        check = _check_vocabulary(
            _config(
                transcriber_backend="funasr_onnx",
                corrections={"列解曲线": "裂解曲线"},
            )
        )
        self.assertEqual(check.status, "ok")

    def test_fails_when_the_prompt_exceeds_the_truncation_budget(self) -> None:
        config = _config(
            transcriber_backend="faster_whisper",
            vocabulary_terms=tuple(f"term{i}" for i in range(10)),
        )
        with patch("vibemouse.ops.doctor._count_prompt_tokens", return_value=400):
            check = _check_vocabulary(config)
        self.assertEqual(check.status, "fail")
        self.assertIn("truncates", check.detail)
        self.assertIn("corrections", check.detail)

    def test_warns_about_dilution_past_the_advisory_term_count(self) -> None:
        config = _config(
            transcriber_backend="faster_whisper",
            vocabulary_terms=tuple(f"term{i}" for i in range(31)),
        )
        with patch("vibemouse.ops.doctor._count_prompt_tokens", return_value=150):
            check = _check_vocabulary(config)
        self.assertEqual(check.status, "warn")
        self.assertIn("dilutes", check.detail)

    def test_reports_ok_within_budget_and_term_count(self) -> None:
        config = _config(
            transcriber_backend="faster_whisper",
            vocabulary_terms=("prophage", "phage", "湿实验"),
            corrections={"列解曲线": "裂解曲线"},
        )
        with patch("vibemouse.ops.doctor._count_prompt_tokens", return_value=42):
            check = _check_vocabulary(config)
        self.assertEqual(check.status, "ok")
        self.assertIn("3 terms, 1 corrections", check.detail)
        self.assertIn("42/223", check.detail)

    def test_survives_a_missing_tokenizer(self) -> None:
        config = _config(
            transcriber_backend="faster_whisper",
            vocabulary_terms=("phage",),
        )
        with patch("vibemouse.ops.doctor._count_prompt_tokens", return_value=None):
            check = _check_vocabulary(config)
        self.assertEqual(check.status, "ok")
        self.assertIn("unverified", check.detail)


if __name__ == "__main__":
    unittest.main()
