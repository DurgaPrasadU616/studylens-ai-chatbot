"""Pure helper functions and constants.

This module has no Streamlit dependency so it can be imported safely
by the test suite without triggering ``st.set_page_config`` or
``st.secrets`` side-effects.
"""

import json
import re

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EMAIL_PATTERN = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_IMAGE_BYTES = 5 * 1024 * 1024  # 5 MB upload limit


# ---------------------------------------------------------------------------
# Image helpers
# ---------------------------------------------------------------------------

def is_image_too_large(num_bytes: int) -> bool:
    """Return True if *num_bytes* exceeds MAX_IMAGE_BYTES."""
    return num_bytes > MAX_IMAGE_BYTES


# ---------------------------------------------------------------------------
# Quiz JSON helpers
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    """Remove markdown code fences from *text* (e.g. \\`\\`\\`json … \\`\\`\\`)."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    return text.strip()


def parse_quiz_response(raw: str):
    """Parse and validate a Gemini quiz JSON string.

    Returns ``(True, list_of_question_dicts)`` on success, or
    ``(False, user_friendly_error_str)`` on any validation failure.

    Each question dict must contain:
    - ``"question"``: str
    - ``"options"``: list of exactly 4 strings
    - ``"answer"``: int in 0–3 (index of the correct option)
    """
    text = _strip_fences(raw)
    try:
        questions = json.loads(text)
        if not isinstance(questions, list) or len(questions) == 0:
            raise ValueError("empty or non-list")
        for q in questions:
            if not all(k in q for k in ("question", "options", "answer")):
                raise ValueError("missing keys")
            if not isinstance(q["answer"], int) or q["answer"] not in range(4):
                raise ValueError("answer index out of range")
        return True, questions
    except (json.JSONDecodeError, ValueError):
        return False, "Couldn't generate the quiz. Please try again."
