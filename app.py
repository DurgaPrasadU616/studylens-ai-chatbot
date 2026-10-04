"""StudyLens AI — Streamlit front-end.

Layout
------
1. CONFIG          – constants, page config, CSS injection
2. SECRETS         – API keys loaded from st.secrets
3. GEMINI HELPERS  – client, chat helpers, quiz & flashcard generation
4. EMAIL HELPERS   – plain-text → HTML conversion, SMTP send
5. UI – ONBOARDING – name/email gate
6. UI – SIDEBAR    – mode picker, session controls
7. UI – FLASHCARDS – one-card-at-a-time review
8. UI – QUIZ       – MCQ display and scoring
9. UI – CHAT       – message history, suggestion chips, input
"""

# ── Imports ────────────────────────────────────────────────────────────────────
import html
import json
import re
import smtplib
import time
from email.header import Header
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

import streamlit as st
from google import genai
from google.genai import types

from helpers import EMAIL_PATTERN, MAX_IMAGE_BYTES, is_image_too_large, parse_quiz_response
from prompts import (
    FLASHCARD_REQUEST_PROMPT,
    MODE_INSTRUCTIONS,
    QUIZ_REQUEST_PROMPT,
    SUMMARY_REQUEST_PROMPT,
    SYSTEM_PROMPT,
    WELCOME_MESSAGE_TEMPLATE,
)

# ── 1. CONFIG ──────────────────────────────────────────────────────────────────

MODEL_NAME = "gemini-3.5-flash"     # Gemini model used for all requests
# EMAIL_PATTERN, MAX_IMAGE_BYTES, is_image_too_large, parse_quiz_response → helpers.py

# Maps suggestion-chip labels → study-mode keys
_MODE_MAP = {
    "Explain a diagram": "Explain",
    "Solve a problem": "Solve",
    "Make revision notes": "Exam Revision",
}

# Regex that matches every fixed section heading produced by SUMMARY_REQUEST_PROMPT
# and the optional FLASHCARDS section appended when cards exist.
_SECTION_TITLES = re.compile(
    r"^(TOPIC|KEY CONCEPTS|IMPORTANT EXPLANATIONS|FORMULAS AND DEFINITIONS|"
    r"EXAM POINTS|5 QUICK REVISION QUESTIONS|FLASHCARDS)$"
)

st.set_page_config(page_title="StudyLens AI", page_icon="📚")

st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700&display=swap');

/* Typography — DM Sans on every element (outranks Streamlit's element rules) */
html, body, .stApp, .stApp *,
input, textarea, label, button {
    font-family: "DM Sans", ui-sans-serif, system-ui, -apple-system,
        "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif !important;
}
/* …but icons keep their icon face and code stays monospace */
.stApp [data-testid^="stIcon"] {
    font-family: "Material Symbols Rounded" !important;
}
.stApp pre, .stApp code, .stApp kbd, .stApp samp,
.stApp pre *, .stApp code * {
    font-family: "Source Code Pro", ui-monospace, SFMono-Regular,
        Menlo, Consolas, monospace !important;
}
html, body { line-height: 1.6; }
[data-testid="stMarkdownContainer"] p,
[data-testid="stChatMessage"] p,
[data-testid="stMarkdownContainer"] li,
[data-testid="stChatMessage"] li { line-height: 1.6; }

/* Headings — slightly lighter weight, tighter letter spacing */
[data-testid="stMarkdownContainer"] h1 {
    font-weight: 600;
    letter-spacing: -0.025em;
    line-height: 1.2;
}
[data-testid="stMarkdownContainer"] h2,
[data-testid="stMarkdownContainer"] h3 {
    font-weight: 500;
    letter-spacing: -0.02em;
    line-height: 1.25;
}
[data-testid="stMarkdownContainer"] h4,
[data-testid="stMarkdownContainer"] h5,
[data-testid="stMarkdownContainer"] h6 {
    font-weight: 600;
    letter-spacing: -0.01em;
    line-height: 1.3;
}

/* Type scale — 12 / 14 / 16 / 18 / 20 / 24 / 28 px (hero > brand > section) */
h1 { font-size: 1.75rem !important; }
h2 { font-size: 1.5rem !important; }
h3 { font-size: 1.25rem !important; }
h4 { font-size: 1.125rem !important; }
h5, h6 { font-size: 1rem !important; }

/* Form & chat inputs match body text (16px also stops iOS zooming in) */
input, textarea { font-size: 1rem !important; }

/* Consistent vertical spacing between sections (4px grid) */
:root {
    --section-gap: 2rem;   /* 32px — shared by headings and st.divider() */
    --sub-gap: 1.25rem;    /* 20px */
}
[data-testid="stMarkdownContainer"] h1 { margin: 0 0 0.75rem; }
[data-testid="stMarkdownContainer"] h2 { margin: var(--section-gap) 0 0.5rem; }
[data-testid="stMarkdownContainer"] h3 { margin: var(--sub-gap) 0 0.5rem; }
[data-testid="stMarkdownContainer"] > :first-child { margin-top: 0; }

/* Dividers — palette hairline on the section rhythm (st.divider() renders <hr>) */
hr {
    border: 0 !important;
    border-top: 1px solid #E8E1CB !important;
    margin: var(--section-gap) 0 !important;
}
[data-testid="stChatMessage"] hr { margin: 0.75rem 0 !important; }

/* Compact header — app name (left), mode pill (right), caption below */
.app-header { margin-bottom: 0.75rem; }
.app-header-top {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.5rem 0.75rem;
}
.app-header-title {
    font-size: 1.5rem;
    font-weight: 600;
    letter-spacing: -0.025em;
    line-height: 1.2;
    color: #2E2B24;
}
.app-header-pill {
    flex-shrink: 0;
    font-size: 0.75rem;
    font-weight: 500;
    color: #6B6557;
    background: #F4EFDF;
    border: 1px solid #E8E1CB;
    border-radius: 999px;
    padding: 0.25rem 0.75rem;
    white-space: nowrap;
}
.app-header .app-header-caption {
    margin: 0.25rem 0 0;
    font-size: 0.875rem;
    line-height: 1.4;
    color: #6B6557;
}

/* Sidebar mode — segmented control: one row, 44px tap target, soft-gold pill */
[data-testid="stButtonGroup"] { gap: 0.25rem !important; }
[data-testid="stButtonGroup"] button[data-variant="segmented_control"] {
    flex: 0 0 auto !important;
    min-height: 44px !important;
    padding: 0.5rem !important;
    font-size: 0.875rem;
    white-space: nowrap;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"]:not([data-selected]):not([data-disabled]) {
    color: #6B6557 !important;
}
[data-testid="stButtonGroup"] button[data-variant="segmented_control"][data-selected]:not([data-disabled]) {
    background: #F4EBCB !important;
    border-color: #C9A227 !important;
    color: #2E2B24 !important;
    font-weight: 500 !important;
}

/* Study-pack card — title, uppercase muted section headings, body */
.pack-card { overflow-wrap: break-word; }
.pack-card .pack-card-title {
    margin: 0 0 0.25rem;
    font-size: 1.125rem;
    font-weight: 600;
    letter-spacing: -0.01em;
    color: #2E2B24;
}
.pack-card .pack-heading {
    margin: 1.25rem 0 0.5rem;
    font-size: 0.75rem;
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: #6B6557;
}
.pack-card .pack-card-title + .pack-heading { margin-top: 0.5rem; }
.pack-card .pack-line { margin: 0.5rem 0; }
.pack-card .pack-list { margin: 0.5rem 0; padding-left: 1.25rem; }
.pack-card .pack-list li { margin: 0.25rem 0; }

/* Flashcards — centered card: progress, large term, answer divider */
.fc-card {
    padding: 1.5rem 1rem;
    text-align: center;
    overflow-wrap: break-word;
}
.fc-card .fc-progress {
    margin: 0 0 0.75rem;
    font-size: 0.75rem;
    font-weight: 500;
    letter-spacing: 0.06em;
    color: #6B6557;
}
.fc-card .fc-term {
    margin: 0;
    font-size: 1.5rem;
    font-weight: 600;
    letter-spacing: -0.015em;
    line-height: 1.3;
    color: #2E2B24;
}
.fc-card .fc-answer {
    margin: 1.25rem 0 0;
    padding-top: 1rem;
    border-top: 1px dashed #E8E1CB;
    font-size: 1rem;
    line-height: 1.6;
    color: #2E2B24;
}

/* Quiz — roomier options, muted green/red result tints */
.stRadio [data-testid="stRadioGroup"] { gap: 0.5rem; }
.stRadio [data-testid="stWidgetLabel"] { font-size: 1rem !important; }
.quiz-results {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    margin-top: 0.25rem;
}
.quiz-result {
    border: 1px solid;
    border-radius: 12px;
    padding: 0.75rem 1rem;
    font-size: 0.875rem;
    line-height: 1.5;
    overflow-wrap: break-word;
}
.quiz-result.quiz-ok { background: #ECF3E8; border-color: #D2E2CB; color: #35502E; }
.quiz-result.quiz-bad { background: #F8EDEB; border-color: #ECD6D1; color: #6B332B; }
.quiz-result.quiz-skip { background: #F4EFDF; border-color: #E8E1CB; color: #6B6557; }

/* Hide main menu, footer, deploy button */
[data-testid="stMainMenu"], footer,
[data-testid="stDeployButton"], [data-testid="stAppDeployButton"] {
    display: none !important;
}

/* Center content, limit width, responsive spacing */
.block-container {
    max-width: 720px;
    margin: 0 auto;
    padding: 2.5rem 1.5rem 3rem;
}
@media (max-width: 640px) {
    .block-container {
        padding: 1.5rem 1rem 2rem;
    }
}

/* Buttons: one surface, rounded, 44px min tap target, wrap text cleanly */
.stButton > button, .stDownloadButton > button,
.stFormSubmitButton > button {
    border-radius: 10px;
    border: 1px solid #E8E1CB;
    box-shadow: none;
    min-height: 44px;
    padding: 0.5rem 1rem;
    white-space: normal;
    word-break: break-word;
    transition: background-color 0.2s ease;
    background: #FFFDF7 !important;
    color: #2E2B24 !important;
}
.stButton > button:hover:not(:disabled),
.stDownloadButton > button:hover:not(:disabled),
.stFormSubmitButton > button:hover:not(:disabled) {
    background: #F4EFDF !important;
}
.stButton > button:disabled,
.stDownloadButton > button:disabled,
.stFormSubmitButton > button:disabled {
    background: #FBF8EF !important;
    color: #6B6557 !important;   /* 5.5:1 on #FBF8EF */
    border-color: #E8E1CB !important;
    opacity: 1;
}

/* Muted text & caption contrast (>= 4.5:1 against #FBF8EF) */
[data-testid="stCaptionContainer"] p, .stCaption {
    color: #6B6557 !important;
}

/* Chat bubbles & overflow prevention */
[data-testid="stChatMessage"] {
    overflow-wrap: break-word;
    word-break: break-word;
}
[data-testid="stChatMessage"] pre {
    max-width: 100%;
    overflow-x: auto;
}
img {
    max-width: 100%;
    height: auto;
}

/* Uploaded images — rounded thumbnails with a thin border (320px cap) */
[data-testid="stChatMessageContent"] [data-testid="stImage"] img {
    max-width: 320px !important;
    height: auto;
    border-radius: 12px;
    border: 1px solid #E8E1CB;
}

/* Chat bubbles — shared shape: soft radius, capped width, comfy padding */
.stChatMessage[data-testid="stChatMessage"] {
    max-width: min(36rem, 88%);
    border-radius: 16px;
    padding: 1rem 1.25rem;
    margin-bottom: 1rem;
}

/* Chat bubbles — user */
.stChatMessage[data-testid="stChatMessage"]:has([aria-label="Chat message from user" i]) {
    background: #F4EBCB;
    border: 1px solid #E8E1CB;
}

/* Chat bubbles — assistant */
.stChatMessage[data-testid="stChatMessage"]:has([aria-label="Chat message from assistant" i]) {
    background: #FFFDF7;
    border: 1px solid #E8E1CB;
}

/* Links — ink text with a gold underline instead of the browser's default blue */
.stApp a {
    color: #2E2B24 !important;
    text-decoration-color: #C9A227 !important;
    text-underline-offset: 0.15em;
}
.stApp a:hover { text-decoration-color: #6B6557 !important; }

/* Alerts — palette tints (Streamlit's default yellow/blue/red are off-palette) */
[data-testid="stAlertContainer"] { border-radius: 12px; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) {
    background: #F4EBCB !important;
    color: #2E2B24 !important;   /* 11.8:1 */
    border: 1px solid #E8E1CB;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) {
    background: #F4EFDF !important;
    color: #6B6557 !important;
    border: 1px solid #E8E1CB;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) {
    background: #ECF3E8 !important;
    color: #35502E !important;
    border: 1px solid #D2E2CB;
}
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) {
    background: #F8EDEB !important;
    color: #6B332B !important;
    border: 1px solid #ECD6D1;
}

/* Chat input — radius aligned with the cards, 44px controls, palette send button */
[data-testid="stChatInput"] > div { border-radius: 12px !important; }
[data-testid="stChatInputFileUploadButton"] button,
[data-testid="stChatInputSubmitButton"] {
    min-height: 44px !important;
    min-width: 44px !important;
}
[data-testid="stChatInputSubmitButton"]:not(:disabled) {
    background: #C9A227 !important;   /* #2E2B24 on #C9A227 = 5.84:1 */
    color: #2E2B24 !important;
}
[data-testid="stChatInputSubmitButton"]:disabled {
    background: #FFFDF7 !important;
    color: #6B6557 !important;
    border: 1px solid #E8E1CB !important;
}
</style>
""", unsafe_allow_html=True)

# ── 2. SECRETS ─────────────────────────────────────────────────────────────────

GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
GMAIL_ADDRESS = st.secrets["GMAIL_ADDRESS"]
GMAIL_APP_PASSWORD = st.secrets["GMAIL_APP_PASSWORD"]

# ── 3. GEMINI HELPERS ──────────────────────────────────────────────────────────


@st.cache_resource
def get_gemini_client():
    """Return a cached Gemini API client."""
    return genai.Client(api_key=GEMINI_API_KEY)


gemini_client = get_gemini_client()


def _new_chat():
    """Create a fresh Gemini chat session and reset conversation state."""
    st.session_state.chat = gemini_client.chats.create(
        model=MODEL_NAME,
        config=types.GenerateContentConfig(system_instruction=SYSTEM_PROMPT),
    )
    st.session_state.messages = []
    st.session_state.pop("draft_pack", None)
    st.session_state.pop("quiz", None)
    st.session_state.pop("quiz_checked", None)
    st.session_state.pop("flashcards", None)
    st.session_state.pop("fc_index", None)
    st.session_state.pop("fc_show_answer", None)


def render_message(message):
    """Render a single chat message (text or image) in the appropriate bubble."""
    avatar = "📚" if message["role"] == "assistant" else "🙂"
    with st.chat_message(message["role"], avatar=avatar):
        if message["kind"] == "text":
            st.write(message["content"])
        elif message["kind"] == "image":
            st.image(message["content"])


def add_message(role, kind, content):
    """Append a message to session state and render it immediately."""
    st.session_state.messages.append({"role": role, "kind": kind, "content": content})
    render_message(st.session_state.messages[-1])


# Seconds to wait before the single automatic retry on transient errors
_RETRY_DELAY = 2


def _is_retryable(error_msg: str) -> bool:
    """Return True for transient server errors that are worth retrying once."""
    return any(tok in error_msg for tok in (
        "429", "503", "resource_exhausted", "unavailable", "rate", "quota",
    ))


def ask_gemini(parts):
    """Send *parts* to the active Gemini chat and return ``(ok, text)``.

    Retries once after ``_RETRY_DELAY`` seconds on transient errors (rate
    limits, 429, 503).  On failure ``ok`` is False and ``text`` is a
    user-friendly string — no secrets or stack traces are ever surfaced.
    """
    for attempt in range(2):  # attempt 0 = first try, attempt 1 = retry
        try:
            return True, st.session_state.chat.send_message(parts).text
        except (ConnectionError, OSError):
            # Network is down — retrying won't help
            return False, "No internet connection. Please check your network."
        except Exception as error:
            msg = str(error).lower()
            if _is_retryable(msg):
                if attempt == 0:
                    time.sleep(_RETRY_DELAY)
                    continue  # one retry
                return False, "The AI is busy right now. Please try again in a minute."
            # Any other error — do not retry, do not leak details
            return False, "Couldn't reach the AI. Please try again in a moment."
    # Should never be reached, but satisfies the type checker
    return False, "Couldn't reach the AI. Please try again in a moment."


def generate_quiz():
    """Ask Gemini for 5 MCQs and return ``(ok, questions)`` or ``(False, error_str)``."""
    ok, raw = ask_gemini([QUIZ_REQUEST_PROMPT])
    if not ok:
        return False, raw  # raw is already a friendly error string
    # Parsing and validation delegated to the pure helper in helpers.py
    return parse_quiz_response(raw)


def generate_flashcards():
    """Ask Gemini for up to 8 flashcards and return ``(ok, cards)`` or ``(False, error_str)``.

    Each card is a dict with ``"term"`` and ``"definition"`` keys.
    Invalid JSON or missing keys are caught and returned as a friendly error.
    """
    ok, raw = ask_gemini([FLASHCARD_REQUEST_PROMPT])
    if not ok:
        return False, raw

    # Strip markdown fences if Gemini wraps the JSON
    text = raw.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1]
    if text.endswith("```"):
        text = text.rsplit("```", 1)[0]
    text = text.strip()

    try:
        cards = json.loads(text)
        if not isinstance(cards, list) or len(cards) == 0:
            raise ValueError("empty or non-list")
        for card in cards:
            if not isinstance(card.get("term"), str) or not isinstance(card.get("definition"), str):
                raise ValueError("missing or wrong-type keys")
        return True, cards
    except (json.JSONDecodeError, ValueError):
        return False, "Couldn't generate flashcards. Please try again."


# ── 4. EMAIL HELPERS ───────────────────────────────────────────────────────────


def _plain_to_html(text: str) -> str:
    """Convert the plain-text study pack into simple, clean HTML.

    Supports section headings, bullet lines, numbered lines, and paragraphs.
    """
    lines = text.splitlines()
    out: list[str] = []
    in_list = False

    for line in lines:
        stripped = line.strip()

        # Blank line → close any open list, add spacing
        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append("<br>")
            continue

        # Section title → <h2>
        if _SECTION_TITLES.match(stripped):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<h2 style='color:#2c3e50;'>{html.escape(stripped)}</h2>")
            continue

        # Bullet line → list item
        if stripped.startswith(("- ", "• ", "* ")):
            if not in_list:
                out.append("<ul style='margin:0 0 0 1.2em;'>")
                in_list = True
            out.append(f"<li>{html.escape(stripped[2:])}</li>")
            continue

        # Numbered line (e.g. "1. …" or "1) …")
        numbered = re.match(r"^\d+[.)]\s+(.+)", stripped)
        if numbered:
            if not in_list:
                out.append("<ul style='margin:0 0 0 1.2em;'>")
                in_list = True
            out.append(f"<li>{html.escape(numbered.group(1))}</li>")
            continue

        # Regular paragraph text
        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p style='margin:0.3em 0;'>{html.escape(stripped)}</p>")

    if in_list:
        out.append("</ul>")

    body_html = "\n".join(out)
    return (
        "<!DOCTYPE html>"
        "<html><head><meta charset='utf-8'></head>"
        "<body style=\"font-family:Arial,Helvetica,sans-serif;color:#333;"
        "max-width:600px;margin:auto;padding:20px;\">"
        f"{body_html}"
        "</body></html>"
    )


def send_email(to_address, subject, body):
    """Send a multipart (plain + HTML) email through Gmail SMTP.

    Uses a 10-second connection timeout so a hung server never blocks
    indefinitely.  Returns ``(True, "sent")`` on success or
    ``(False, user_friendly_error)`` on failure — no secrets or stack
    traces are ever returned.
    """
    try:
        message = MIMEMultipart("alternative")
        message["Subject"] = Header(subject, "utf-8")
        message["From"] = GMAIL_ADDRESS
        message["To"] = to_address
        message.attach(MIMEText(body, "plain", "utf-8"))
        message.attach(MIMEText(_plain_to_html(body), "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=10) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.send_message(message)
        return True, "sent"
    except smtplib.SMTPAuthenticationError:
        return False, "Email login failed. Check your Gmail App Password."
    except TimeoutError:
        return False, "Email server took too long to respond. Please try again."
    except (ConnectionError, OSError, smtplib.SMTPConnectError):
        return False, "Couldn't connect to email server. Please check your network."
    except smtplib.SMTPException:
        return False, "The email server rejected the message. Please try again."
    except Exception:
        return False, "Couldn't send email. Please try again later."


# ── 5. UI – ONBOARDING ─────────────────────────────────────────────────────────

if "onboarded" not in st.session_state:
    st.markdown("")  # top spacer
    _, center, _ = st.columns([1, 2, 1])
    with center:
        st.markdown(
            "<div style='text-align:center; padding:1.5rem 0 0.25rem;'>"
            "<span style='font-size:3.5rem;'>📚</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<h1 style='text-align:center; margin:0;'>StudyLens AI</h1>",
            unsafe_allow_html=True,
        )
        st.markdown(
            "<p style='text-align:center; color:#6B6557; margin-bottom:1.5rem;'>"
            "Snap it. Understand it. Save it.</p>",
            unsafe_allow_html=True,
        )
        with st.form("onboarding_form"):
            name = st.text_input(
                "Your name",
                help="We'll use this to personalise your Study Pack.",
            )
            email = st.text_input(
                "Your email address",
                placeholder="you@gmail.com",
                help="Your Study Pack will be emailed here.",
            )
            submitted = st.form_submit_button(
                "Start studying 🚀", use_container_width=True
            )
    if submitted:
        if not name.strip() or not email.strip():
            st.warning("Please fill in both your name and email address.")
        elif not EMAIL_PATTERN.match(email.strip()):
            st.warning("That doesn't look like a valid email address.")
        else:
            st.session_state.name = name.strip()
            st.session_state.email = email.strip()
            st.session_state.onboarded = True
            _new_chat()
            st.rerun()
    st.stop()

# ── 6. UI – SIDEBAR ────────────────────────────────────────────────────────────

with st.sidebar:
    st.header("📚 StudyLens AI")
    st.caption(f"{st.session_state.name}  ·  {st.session_state.email}")

    st.markdown("")  # spacer

    # — Mode —
    st.markdown(
        "<p style='color:#6B6557; font-size:0.75rem; margin:0 0 0.25rem;'>MODE</p>",
        unsafe_allow_html=True,
    )
    mode = st.segmented_control(
        "Study mode", list(MODE_INSTRUCTIONS),
        key="study_mode", default=list(MODE_INSTRUCTIONS)[0],
        required=True, label_visibility="collapsed",
        width="stretch", wrap=True,
    )

    st.divider()

    # — Session —
    st.markdown(
        "<p style='color:#6B6557; font-size:0.75rem; margin:0 0 0.25rem;'>SESSION</p>",
        unsafe_allow_html=True,
    )
    if st.button("🔄 Start new topic", use_container_width=True):
        _new_chat()
        st.rerun()

    quiz_disabled = len(st.session_state.messages) <= 2
    if st.button("🧠 Quiz me", disabled=quiz_disabled, use_container_width=True):
        with st.spinner("Building your quiz..."):
            ok, result = generate_quiz()
            if ok:
                st.session_state.quiz = result
                st.session_state.pop("quiz_checked", None)
                st.rerun()
            else:
                st.toast(result, icon="⚠️")

    fc_disabled = len(st.session_state.messages) <= 2
    if st.button("🃏 Flashcards", disabled=fc_disabled, use_container_width=True):
        with st.spinner("Making your flashcards..."):
            ok, result = generate_flashcards()
            if ok:
                st.session_state.flashcards = result
                st.session_state.fc_index = 0
                st.session_state.fc_show_answer = False
                st.rerun()
            else:
                st.toast(result, icon="⚠️")

    st.markdown("")  # spacer
    st.caption("Upload a photo or type a question · pick a mode · chat · send your Study Pack")

# ── 7. UI – FLASHCARDS ────────────────────────────────────────────────────────

if "flashcards" in st.session_state:
    cards = st.session_state.flashcards
    idx = st.session_state.fc_index
    total = len(cards)
    card = cards[idx]

    st.subheader("🃏 Flashcards")
    with st.container(border=True):
        answer_html = (
            f"<div class='fc-answer'>{html.escape(card['definition'])}</div>"
            if st.session_state.fc_show_answer
            else ""
        )
        st.markdown(
            f"<div class='fc-card'>"
            f"<p class='fc-progress'>{idx + 1} / {total}</p>"
            f"<p class='fc-term'>{html.escape(card['term'])}</p>"
            f"{answer_html}"
            f"</div>",
            unsafe_allow_html=True,
        )
        if not st.session_state.fc_show_answer:
            _, fc_btn_col, _ = st.columns([1, 2, 1])
            with fc_btn_col:
                if st.button("Show answer", key="fc_show"):
                    st.session_state.fc_show_answer = True
                    st.rerun()

    fc_col1, fc_col2 = st.columns([1, 1])
    with fc_col1:
        next_label = "Next →" if idx < total - 1 else "Start over 🔁"
        if st.button(next_label, use_container_width=True, key="fc_next"):
            st.session_state.fc_index = (idx + 1) % total
            st.session_state.fc_show_answer = False
            st.rerun()
    with fc_col2:
        if st.button("✖ Close", use_container_width=True, key="fc_close"):
            st.session_state.pop("flashcards", None)
            st.session_state.pop("fc_index", None)
            st.session_state.pop("fc_show_answer", None)
            st.rerun()

    st.divider()

# ── 8. UI – QUIZ ───────────────────────────────────────────────────────────────

if "quiz" in st.session_state:
    st.subheader("🧠 Quick Quiz")
    questions = st.session_state.quiz
    user_answers = []
    for i, q in enumerate(questions):
        with st.container(border=True):
            choice = st.radio(
                f"**Q{i + 1}.** {q['question']}",
                options=q["options"],
                key=f"quiz_q_{i}",
                index=None,
            )
            user_answers.append(choice)

    quiz_col1, quiz_col2, _ = st.columns([1, 1, 4])
    with quiz_col1:
        if st.button("✅ Check answers", use_container_width=True):
            score = sum(
                1 for i, q in enumerate(questions)
                if user_answers[i] == q["options"][q["answer"]]
            )
            st.session_state.quiz_checked = {
                "score": score,
                "total": len(questions),
                "user_answers": user_answers,
            }
            st.rerun()
    with quiz_col2:
        if st.button("🚪 Close quiz", use_container_width=True):
            st.session_state.pop("quiz", None)
            st.session_state.pop("quiz_checked", None)
            st.rerun()

    if "quiz_checked" in st.session_state:
        result = st.session_state.quiz_checked
        st.divider()
        st.markdown(f"### Score: **{result['score']} / {result['total']}**")
        rows = []
        for i, q in enumerate(questions):
            correct_text = q["options"][q["answer"]]
            picked = result["user_answers"][i]
            if picked == correct_text:
                cls, text = "quiz-ok", f"Q{i + 1}: ✅ {html.escape(correct_text)}"
            elif picked is None:
                cls = "quiz-skip"
                text = f"Q{i + 1}: ⏭️ Skipped — correct answer: {html.escape(correct_text)}"
            else:
                cls = "quiz-bad"
                text = (
                    f"Q{i + 1}: ❌ You chose \u201c{html.escape(str(picked))}\u201d — "
                    f"correct answer: {html.escape(correct_text)}"
                )
            rows.append(f"<div class='quiz-result {cls}'>{text}</div>")
        st.markdown(
            "<div class='quiz-results'>" + "".join(rows) + "</div>",
            unsafe_allow_html=True,
        )

    st.divider()

# ── 9. UI – CHAT ───────────────────────────────────────────────────────────────

header_col, button_col = st.columns([5, 2], vertical_alignment="center")

with header_col:
    st.markdown(
        "<div class='app-header'>"
        "<div class='app-header-top'>"
        "<span class='app-header-title'>📚 StudyLens AI</span>"
        f"<span class='app-header-pill'>Mode: {html.escape(str(mode))}</span>"
        "</div>"
        "<p class='app-header-caption'>Snap it. Understand it. Save it.</p>"
        "</div>",
        unsafe_allow_html=True,
    )

with button_col:
    send_disabled = len(st.session_state.messages) <= 2
    if st.button("📧 Send Study Pack", disabled=send_disabled, use_container_width=True):
        with st.spinner("Writing your study pack..."):
            ok, pack = ask_gemini([SUMMARY_REQUEST_PROMPT])
            if ok:
                st.session_state.draft_pack = pack
            else:
                st.toast(pack, icon="⚠️")
    if send_disabled:
        st.caption("Chat about something first to enable this")

def _pack_to_card_html(text: str) -> str:
    """Render study pack text as HTML with small uppercase section headings.

    Every piece of model-generated text is passed through ``html.escape``.
    """
    out: list[str] = []
    in_list = False

    for line in text.splitlines():
        stripped = line.strip()

        if not stripped:
            if in_list:
                out.append("</ul>")
                in_list = False
            continue

        if _SECTION_TITLES.match(stripped):
            if in_list:
                out.append("</ul>")
                in_list = False
            out.append(f"<p class='pack-heading'>{html.escape(stripped)}</p>")
            continue

        item = None
        if stripped.startswith(("- ", "• ", "* ")):
            item = stripped[2:]
        else:
            numbered = re.match(r"^\d+[.)]\s+(.+)", stripped)
            if numbered:
                item = numbered.group(1)

        if item is not None:
            if not in_list:
                out.append("<ul class='pack-list'>")
                in_list = True
            out.append(f"<li>{html.escape(item)}</li>")
            continue

        if in_list:
            out.append("</ul>")
            in_list = False
        out.append(f"<p class='pack-line'>{html.escape(stripped)}</p>")

    if in_list:
        out.append("</ul>")
    return "\n".join(out)


# — Study-pack card / send / download / cancel —
if "draft_pack" in st.session_state:
    pack_text = st.session_state.draft_pack
    st.divider()
    with st.container(border=True):
        st.markdown(
            "<div class='pack-card'>"
            "<p class='pack-card-title'>📝 Review your Study Pack</p>"
            f"{_pack_to_card_html(pack_text)}"
            "</div>",
            unsafe_allow_html=True,
        )

    send_col, download_col, cancel_col = st.columns(3)
    with send_col:
        if st.button("Send", use_container_width=True):
            # Append flashcards section to the email body only if cards exist
            flashcard_section = ""
            if "flashcards" in st.session_state:
                lines = ["\n\nFLASHCARDS"]
                for i, card in enumerate(st.session_state.flashcards, 1):
                    lines.append(f"{i}. {card['term']}")
                    lines.append(f"   {card['definition']}")
                flashcard_section = "\n".join(lines)
            body = (
                f"Hi {st.session_state.name},\n\n"
                "Here is your StudyLens AI study pack:\n\n"
                f"{pack_text}{flashcard_section}\n\n"
                "Happy studying!\n- StudyLens AI"
            )
            with st.spinner("Sending your study pack..."):
                ok, info = send_email(
                    st.session_state.email,
                    "📚 StudyLens AI — Your Study Pack",
                    body,
                )
            del st.session_state.draft_pack
            if ok:
                st.toast("Study Pack sent", icon="📬")
            else:
                st.toast(info, icon="⚠️")
    with download_col:
        st.download_button(
            label="Download",
            data=pack_text,
            file_name="studylens_study_pack.txt",
            mime="text/plain",
            use_container_width=True,
        )
    with cancel_col:
        if st.button("Cancel", use_container_width=True):
            del st.session_state.draft_pack
            st.rerun()

# — Message history —
has_user_message = any(m["role"] == "user" for m in st.session_state.messages)

if not st.session_state.messages:
    add_message("assistant", "text", WELCOME_MESSAGE_TEMPLATE.format(name=st.session_state.name))
else:
    for message in st.session_state.messages:
        render_message(message)

# — Suggestion chips (shown only before the first user message) —
if not has_user_message:
    st.markdown(
        "<p style='color:#6B6557; margin:0.75rem 0 0.5rem;'>Try one of these to get started:</p>",
        unsafe_allow_html=True,
    )
    cols = st.columns(3)
    for col, label in zip(cols, _MODE_MAP):
        with col:
            if st.button(label, use_container_width=True, key=f"suggest_{label}"):
                st.session_state.study_mode = _MODE_MAP[label]
                st.rerun()

# — Chat input —
user_input = st.chat_input(
    "Ask a question, or attach a photo of your study material",
    accept_file=True,
    file_type=["jpg", "jpeg", "png"],
)

if user_input:
    photo = user_input.files[0] if user_input.files else None
    text = user_input.text
    instruction = MODE_INSTRUCTIONS[mode]
    parts = []

    if photo is not None:
        photo_bytes = photo.getvalue()
        if is_image_too_large(len(photo_bytes)):
            st.toast("Image is over 5 MB. Please choose a smaller one.", icon="⚠️")
            st.stop()
        add_message("user", "image", photo_bytes)
        parts.append(types.Part.from_bytes(data=photo_bytes, mime_type=photo.type))
    if text:
        add_message("user", "text", text)
        parts.append(f"{instruction}\n\nStudent's message: {text}")
    elif photo is not None:
        parts.append(instruction)

    status = "Reading your image..." if photo is not None else "Thinking..."
    with st.spinner(status):
        ok, answer = ask_gemini(parts)
    if ok:
        add_message("assistant", "text", answer)
    else:
        # Show the friendly error as a transient toast; do NOT store it in
        # message history — it would corrupt the Study Pack and inflate the
        # message count that gates the Quiz / Send Study Pack buttons.
        st.toast(answer, icon="⚠️")
