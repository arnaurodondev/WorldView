"""Tests for F-103 — _extract_json_object tolerant LLM-JSON parser."""

from __future__ import annotations

import json

import pytest
from nlp_pipeline.infrastructure.workers.unresolved_resolution_worker import (
    _extract_json_object,
)

pytestmark = pytest.mark.unit


class TestExtractJsonObject:
    def test_plain_json_object(self) -> None:
        result = _extract_json_object('{"is_entity": true, "reason": "company"}')
        assert result == {"is_entity": True, "reason": "company"}

    def test_strips_json_code_fence(self) -> None:
        # Llama-3.1-8B-Instruct sometimes wraps JSON in ```json fences```
        # despite response_format=json_object.
        wrapped = '```json\n{"is_entity": false, "reason": "noise"}\n```'
        result = _extract_json_object(wrapped)
        assert result == {"is_entity": False, "reason": "noise"}

    def test_strips_plain_code_fence(self) -> None:
        wrapped = '```\n{"is_entity": true}\n```'
        result = _extract_json_object(wrapped)
        assert result == {"is_entity": True}

    def test_extracts_balanced_braces_from_prose(self) -> None:
        # Some models return prose around the JSON — we still want the answer.
        prose = 'Here is my classification: {"is_entity": true, "reason": "regulator"} — hope this helps!'
        result = _extract_json_object(prose)
        assert result == {"is_entity": True, "reason": "regulator"}

    def test_handles_nested_objects(self) -> None:
        wrapped = 'Sure: {"is_entity": true, "metadata": {"score": 0.9}}'
        result = _extract_json_object(wrapped)
        assert result["is_entity"] is True
        assert result["metadata"] == {"score": 0.9}

    def test_strips_whitespace(self) -> None:
        result = _extract_json_object('   \n {"is_entity": true}\n  ')
        assert result == {"is_entity": True}

    def test_empty_input_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _extract_json_object("")

    def test_garbage_input_raises(self) -> None:
        with pytest.raises(json.JSONDecodeError):
            _extract_json_object("this is not JSON anywhere")

    def test_non_string_input_raises(self) -> None:
        # Defensive — if response.json() returns a dict directly somehow,
        # fail loudly rather than silently propagate.
        with pytest.raises(json.JSONDecodeError):
            _extract_json_object(None)  # type: ignore[arg-type]

    def test_array_only_input_raises(self) -> None:
        # Worker expects a JSON OBJECT, not array. Falling through to the
        # balanced-brace search must not return a list disguised as a dict.
        with pytest.raises(json.JSONDecodeError):
            _extract_json_object('["a", "b"]')

    def test_code_fence_with_invalid_json_falls_through(self) -> None:
        # Fence stripped but inner is still bad — should raise after exhausting all paths.
        wrapped = "```json\nnot really json\n```"
        with pytest.raises(json.JSONDecodeError):
            _extract_json_object(wrapped)
