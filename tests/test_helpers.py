"""Tests for the pure helper functions in helpers.py.

No Streamlit, no network calls, no mocking required.
Run with:  pytest tests/ -v
"""

import json

import pytest

from helpers import (
    EMAIL_PATTERN,
    MAX_IMAGE_BYTES,
    is_image_too_large,
    parse_quiz_response,
)

# ---------------------------------------------------------------------------
# 1. Email validation (EMAIL_PATTERN regex)
# ---------------------------------------------------------------------------

class TestEmailValidation:
    """EMAIL_PATTERN should accept valid addresses and reject malformed ones."""

    # --- valid ---
    @pytest.mark.parametrize("address", [
        "student@example.com",
        "name+tag@university.ac.uk",
        "user.name@sub.domain.org",
        "x@y.io",
    ])
    def test_valid_addresses_are_accepted(self, address):
        assert EMAIL_PATTERN.match(address), f"Expected {address!r} to be valid"

    # --- invalid ---
    @pytest.mark.parametrize("address", [
        "notanemail",          # no @ at all
        "missing@domain",      # no TLD dot
        "@nodomain.com",       # empty local part
        "user @example.com",   # space before @
        "user@ example.com",   # space after @
        "",                    # empty string
    ])
    def test_invalid_addresses_are_rejected(self, address):
        assert not EMAIL_PATTERN.match(address), f"Expected {address!r} to be invalid"


# ---------------------------------------------------------------------------
# 2. Quiz JSON parsing (parse_quiz_response)
# ---------------------------------------------------------------------------

_VALID_QUESTION = {
    "question": "What is 2 + 2?",
    "options": ["1", "2", "3", "4"],
    "answer": 3,
}


class TestQuizJsonParsing:
    """parse_quiz_response should accept well-formed JSON and reject bad input."""

    def test_valid_json_returns_ok_and_questions(self):
        raw = json.dumps([_VALID_QUESTION])
        ok, result = parse_quiz_response(raw)
        assert ok is True
        assert result == [_VALID_QUESTION]

    def test_strips_markdown_fences_before_parsing(self):
        fenced = f"```json\n{json.dumps([_VALID_QUESTION])}\n```"
        ok, result = parse_quiz_response(fenced)
        assert ok is True
        assert len(result) == 1

    def test_strips_plain_fences_without_language_tag(self):
        fenced = f"```\n{json.dumps([_VALID_QUESTION])}\n```"
        ok, result = parse_quiz_response(fenced)
        assert ok is True

    def test_multiple_questions_are_accepted(self):
        questions = [_VALID_QUESTION, {**_VALID_QUESTION, "answer": 0}]
        ok, result = parse_quiz_response(json.dumps(questions))
        assert ok is True
        assert len(result) == 2

    def test_empty_list_is_rejected(self):
        ok, msg = parse_quiz_response("[]")
        assert ok is False
        assert isinstance(msg, str)

    def test_missing_question_key_is_rejected(self):
        bad = [{"options": ["A", "B", "C", "D"], "answer": 0}]
        ok, msg = parse_quiz_response(json.dumps(bad))
        assert ok is False

    def test_missing_options_key_is_rejected(self):
        bad = [{"question": "Q?", "answer": 0}]
        ok, msg = parse_quiz_response(json.dumps(bad))
        assert ok is False

    def test_missing_answer_key_is_rejected(self):
        bad = [{"question": "Q?", "options": ["A", "B", "C", "D"]}]
        ok, msg = parse_quiz_response(json.dumps(bad))
        assert ok is False

    def test_answer_index_out_of_range_is_rejected(self):
        bad = [{**_VALID_QUESTION, "answer": 4}]  # valid range is 0-3
        ok, msg = parse_quiz_response(json.dumps(bad))
        assert ok is False

    def test_answer_as_string_is_rejected(self):
        bad = [{**_VALID_QUESTION, "answer": "3"}]  # must be int
        ok, msg = parse_quiz_response(json.dumps(bad))
        assert ok is False

    def test_invalid_json_is_rejected(self):
        ok, msg = parse_quiz_response("not json at all")
        assert ok is False
        assert isinstance(msg, str)

    def test_error_message_is_user_friendly(self):
        ok, msg = parse_quiz_response("garbage")
        assert ok is False
        # Must not contain raw Python exception details
        assert "Traceback" not in msg
        assert "Error" not in msg


# ---------------------------------------------------------------------------
# 3. Image size check (is_image_too_large / MAX_IMAGE_BYTES)
# ---------------------------------------------------------------------------

class TestImageSizeCheck:
    """is_image_too_large should enforce the 5 MB limit precisely."""

    def test_exactly_at_limit_is_allowed(self):
        assert is_image_too_large(MAX_IMAGE_BYTES) is False

    def test_one_byte_over_limit_is_rejected(self):
        assert is_image_too_large(MAX_IMAGE_BYTES + 1) is True

    def test_small_image_is_allowed(self):
        assert is_image_too_large(1024) is False

    def test_zero_bytes_is_allowed(self):
        assert is_image_too_large(0) is False

    def test_limit_is_five_megabytes(self):
        assert MAX_IMAGE_BYTES == 5 * 1024 * 1024
