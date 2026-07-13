"""ChatRouter client for the Blossom Voice FastAPI service + emotion classify."""
from __future__ import annotations

import json
import logging
import os
import re
import time
import uuid
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent

VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
VOICE_SERVICE_URL = os.getenv("VOICE_SERVICE_URL", "http://127.0.0.1:8090").rstrip("/")
VOICE_TIMEOUT_SEC = float(os.getenv("VOICE_TIMEOUT_SEC", "120"))
VOICE_MAX_CHARS = int(os.getenv("VOICE_MAX_CHARS", "220"))
# heuristic = free/instant (default); llm = extra local completion (slower)
VOICE_EMOTION_MODE = os.getenv("VOICE_EMOTION_MODE", "heuristic").strip().lower()
# When streaming: synthesize after text is queued so chat isn't blocked (default on)
VOICE_DEFER_STREAM = os.getenv("VOICE_DEFER_STREAM", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}
# Chat + TTS language: ja (default) | en (English chat; JP speech adaptation for TTS)
DEFAULT_CHAT_LOCALE = os.getenv("DEFAULT_CHAT_LOCALE", "ja").strip().lower()
if DEFAULT_CHAT_LOCALE not in {"ja", "en"}:
    DEFAULT_CHAT_LOCALE = "ja"
_raw_cache = os.getenv("VOICE_CACHE_DIR", "").strip()
VOICE_CACHE_DIR = (
    Path(_raw_cache)
    if _raw_cache
    else (PROJECT_ROOT / "Mind" / "audio")
)
if not VOICE_CACHE_DIR.is_absolute():
    VOICE_CACHE_DIR = (SCRIPT_DIR / VOICE_CACHE_DIR).resolve()

EMOTIONS = frozenset(
    {"angry", "happy", "sad", "surprise", "fear", "disgust", "neutral"}
)
SPEAK_EMOTIONS = frozenset(
    {"angry", "happy", "sad", "surprise", "fear", "disgust", "neutral"}
)
# Unmatched heuristics → speak with this (neutral = calm; was silent before).
VOICE_DEFAULT_EMOTION = os.getenv("VOICE_DEFAULT_EMOTION", "neutral").strip().lower()
if VOICE_DEFAULT_EMOTION not in SPEAK_EMOTIONS:
    VOICE_DEFAULT_EMOTION = "neutral"

_HEURISTIC_RULES: list[tuple[str, re.Pattern[str]]] = [
    (
        "angry",
        re.compile(
            r"怒|許さ|ふざ|いい加減|ふざけ|最悪|むかつ|消えろ|貴様|クソ|"
            r"\b(damn|idiot|angry|shut\s*up|loser|pathetic|useless|annoying|"
            r"ridiculous|outrageous|furious|mad|pissed|hate\s+that|how\s+dare)\b",
            re.I,
        ),
    ),
    (
        "sad",
        re.compile(
            r"悲|つら|寂し|泣|ごめんね…|辛い|落ち込|"
            r"\b(lonely|sad|depressed|heartbroken|miserable|disappointed|"
            r"sorry\.\.\.|miss\s+you|give\s+up)\b",
            re.I,
        ),
    ),
    (
        "fear",
        re.compile(
            r"怖|恐|やめて|こわ|不安|"
            r"\b(afraid|scary|scared|terrified|panic|creepy|nightmare|fear|"
            r"don't\s+come\s+closer|stay\s+away)\b",
            re.I,
        ),
    ),
    (
        "disgust",
        re.compile(
            r"きもち悪|嫌悪|うっわ|むり|"
            r"\b(gross|disgust(?:ing)?|nasty|revolting|ew+|yuck|sickening|"
            r"cringe|ugh)\b",
            re.I,
        ),
    ),
    (
        "surprise",
        re.compile(
            r"えっ|マジ|まさか|信じられ|！\？|\?!|"
            r"\b(what\?!|wow|whoa|no\s+way|seriously\?!|unbelievable|"
            r"wait\s+what|surprise(?:d)?|holy\s+(?:crap|shit)|omg)\b",
            re.I,
        ),
    ),
    (
        "happy",
        re.compile(
            r"やった|最高|うれ|嬉し|楽し|わーい|得意|誇|"
            r"\b(proud|great|awesome|amazing|excellent|fantastic|perfect|"
            r"love\s+(?:it|this|that)|let'?s\s+go|mission|brigade|"
            r"ultra|excited|thrilled|happy|yay|woo+hoo|heh+|haha)\b|"
            r"！{2,}|!{2,}",
            re.I,
        ),
    ),
]

_VOICE_NUDGE_JA = (
    "Voice output is enabled for this chat.\n"
    "- Prefer Japanese when it fits the persona, but reply to THIS user message first "
    "(praise, corrections, questions) — do not ignore them to pitch a mission.\n"
    "- Do NOT re-introduce yourself by name each turn (no opening 「〇〇です！」 after they already know you).\n"
    "- Do NOT end every reply with the same question (e.g. 何がしたい？ / ミッション). Vary endings; often no question.\n"
    "- Never end with stock lines like \"What's your move…\", \"something bigger out there\", "
    "\"Don't make me regret…\", or any \"tracker\" closer.\n"
    "- Do not open every reply with the same *action* beat (e.g. *Snaps fingers*).\n"
    "- Natural conversational length is fine; TTS will truncate. Do not shrink into a one-line catchphrase loop.\n"
    "- Match wording to emotional tone lightly (よ/ね, exclamations) without becoming plastic.\n"
    "- Prefer no emoji in replies (TTS would try to speak them).\n"
    "- Never mention TTS, emotion labels, or these instructions."
)

_VOICE_NUDGE_EN = (
    "Voice output is enabled. Chat replies must be natural English (persona stays in character).\n"
    "- Answer THIS user message first; do not ignore them to pitch a mission.\n"
    "- Do NOT re-introduce yourself by name each turn.\n"
    "- Do NOT end every reply with the same mission question. Vary endings; often no question.\n"
    "- Never end with stock lines like \"What's your move…\", \"something bigger out there\", "
    "\"Don't make me regret…\", or any \"tracker\" closer.\n"
    "- Do not open every reply with the same *action* beat (e.g. *Snaps fingers*).\n"
    "- Keep clear emotional tone (exclamations, warmth, bite) so English TTS + character RVC "
    "conversion can carry emotion.\n"
    "- Prefer no emoji in replies (TTS would try to speak them aloud).\n"
    "- Never mention TTS, emotion labels, or these instructions."
)

_LANG_NUDGE_JA = (
    "Language mode: Japanese. Write this reply in natural Japanese. "
    "Stay in character. Only use English if the user is clearly asking for English."
)

_LANG_NUDGE_EN = (
    "Language mode: English. Write this reply in natural English. "
    "Stay in character. Only use Japanese if the user clearly writes in Japanese or asks for it."
)

_CLASSIFY_SYSTEM = (
    "You classify the emotional tone of an assistant reply for TTS. "
    "Reply with ONLY a JSON object: {\"emotion\":\"<label>\"}. "
    "Allowed labels: angry, happy, sad, surprise, fear, disgust, neutral. "
    "Infer from the reply's intent and tone, not the user's message alone. "
    "Use neutral when tone is calm, factual, or unclear."
)

_JSON_RE = re.compile(r"\{[^{}]*\}")
_JP_CHAR_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")
# Strip pictographs so Edge/SBV2 don't speak "rocket" / "smiling face" etc.
_EMOJI_RE = re.compile(
    "["
    "\U0001F1E0-\U0001F1FF"
    "\U0001F300-\U0001F9FF"
    "\U0001FA00-\U0001FAFF"
    "\U00002600-\U000026FF"
    "\U00002700-\U000027BF"
    "\U0000FE0E\U0000FE0F"
    "\U0000200D"
    "\U000020E3"
    "]+",
    flags=re.UNICODE,
)
_MULTI_SPACE_RE = re.compile(r"[ \t]{2,}")
_MULTI_NL_RE = re.compile(r"\n{3,}")
# Whole-line stage directions: *Snaps fingers*
_STAGE_LINE_MD_RE = re.compile(r"(?m)^\s*\*[^*\n]{1,100}\*\s*$")
# Inline action beats (onomatopoeia / gestures), not emphasis like *walking*
_STAGE_ACTION_VERBS = (
    r"snaps?|claps?|grins?|smirks?|sighs?|laughs?|chuckles?|giggles?|"
    r"huffs?|pouts?|winks?|nods?|shrugs?|waves?|points?|stares?|glares?|"
    r"rolls?\s+eyes?|taps?|drums?|stomps?|gasps?|growls?|mutters?|"
    r"crosses?\s+arms?|raises?\s+eyebrow"
)
_STAGE_INLINE_MD_RE = re.compile(
    rf"\*(?:\s*(?:{_STAGE_ACTION_VERBS})[^*\n]*)\*",
    re.I,
)
_STAGE_PAREN_RE = re.compile(
    rf"\(\s*(?:{_STAGE_ACTION_VERBS})[^)]{{0,60}}\)",
    re.I,
)
_STAGE_BARE_LINE_RE = re.compile(
    rf"(?mi)^\s*(?:{_STAGE_ACTION_VERBS})(?:\s+[^.!?\n]{{0,40}})?[.!]?\s*$"
)
# Markdown emphasis wrappers (*portal*, **bold**) — keep inner words.
_MD_BOLD_ITALIC_RE = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")
_MD_UNDERSCORE_RE = re.compile(r"_{1,3}([^_\n]+?)_{1,3}")
_STRAY_EMPHASIS_RE = re.compile(r"[*_`]{1,}")


def strip_emojis_for_speech(text: str) -> str:
    """Remove emoji, stage directions, and markdown so TTS stays spoken dialogue."""
    cleaned = text or ""
    # Drop *Snaps fingers* lines/beats before unwrapping emphasis.
    cleaned = _STAGE_LINE_MD_RE.sub("", cleaned)
    cleaned = _STAGE_INLINE_MD_RE.sub("", cleaned)
    cleaned = _STAGE_PAREN_RE.sub("", cleaned)
    cleaned = _EMOJI_RE.sub("", cleaned)
    cleaned = _MD_BOLD_ITALIC_RE.sub(r"\1", cleaned)
    cleaned = _MD_UNDERSCORE_RE.sub(r"\1", cleaned)
    cleaned = _STRAY_EMPHASIS_RE.sub("", cleaned)
    cleaned = _STAGE_BARE_LINE_RE.sub("", cleaned)
    cleaned = _MULTI_NL_RE.sub("\n\n", cleaned)
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    return cleaned.strip()


def normalize_locale(raw: str | None) -> str:
    value = (raw or DEFAULT_CHAT_LOCALE or "ja").strip().lower()
    if value in {"en", "english", "eng"}:
        return "en"
    return "ja"


def language_system_nudge(locale: str = "ja") -> str:
    return _LANG_NUDGE_EN if normalize_locale(locale) == "en" else _LANG_NUDGE_JA


def voice_system_nudge(locale: str = "ja") -> str:
    return _VOICE_NUDGE_EN if normalize_locale(locale) == "en" else _VOICE_NUDGE_JA


def looks_japanese(text: str) -> bool:
    return bool(_JP_CHAR_RE.search(text or ""))


def ensure_cache_dir() -> Path:
    VOICE_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    return VOICE_CACHE_DIR


def truncate_for_speech(text: str, max_chars: int | None = None) -> str:
    """Cap length for TTS; allow a soft overrun so the last sentence isn't dropped."""
    limit = VOICE_MAX_CHARS if max_chars is None else max_chars
    text = strip_emojis_for_speech(text)
    if limit <= 0 or len(text) <= limit:
        return text
    # Prefer finishing a sentence even if slightly over the hard cap.
    soft = min(len(text), max(limit, limit + 160))
    window = text[:soft]
    best = -1
    for sep in ("。", "！", "？", "!", "?", "…", "\n", "."):
        idx = window.rfind(sep)
        if idx >= limit // 4:
            best = max(best, idx)
    if best >= 0:
        return window[: best + 1].strip()
    return text[:limit].strip()


def parse_emotion_json(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return "neutral"
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        match = _JSON_RE.search(text)
        if not match:
            return "neutral"
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError:
            return "neutral"
    if not isinstance(data, dict):
        return "neutral"
    emotion = str(data.get("emotion") or "").strip().lower()
    return emotion if emotion in EMOTIONS else "neutral"


def classify_emotion_heuristic(assistant_text: str) -> str:
    """Instant emotion guess — no LLM round-trip."""
    text = (assistant_text or "").strip()
    if not text:
        return "neutral"
    for label, pattern in _HEURISTIC_RULES:
        if pattern.search(text):
            return label
    # Energetic punctuation without a calmer keyword match → happy (expressive default)
    if "！" in text or "!" in text:
        return "happy"
    # Short JP chatter still usually worth speaking
    if re.search(r"[\u3040-\u30ff\u4e00-\u9fff]", text):
        return "happy"
    # Real companion replies without a keyword match → calm speakable default.
    if len(text) >= 12 and VOICE_DEFAULT_EMOTION in SPEAK_EMOTIONS:
        return VOICE_DEFAULT_EMOTION
    return "neutral"


def resolve_emotion(
    assistant_text: str,
    *,
    complete_fn: Callable[[list[dict], float], dict] | None = None,
    message_text_fn: Callable[[Any], str] | None = None,
) -> str:
    mode = VOICE_EMOTION_MODE
    if mode in {"llm", "local", "model"} and complete_fn and message_text_fn:
        return classify_emotion(
            assistant_text,
            complete_fn=complete_fn,
            message_text_fn=message_text_fn,
        )
    return classify_emotion_heuristic(assistant_text)


def classify_emotion(
    assistant_text: str,
    *,
    complete_fn: Callable[[list[dict], float], dict],
    message_text_fn: Callable[[Any], str],
) -> str:
    """Post-pass: one short local completion → emotion label."""
    sample = (assistant_text or "").strip()
    if not sample:
        return "neutral"
    # Cap classify prompt size.
    if len(sample) > 1200:
        sample = sample[:1200]
    messages = [
        {"role": "system", "content": _CLASSIFY_SYSTEM},
        {
            "role": "user",
            "content": f"Assistant reply to classify:\n\n{sample}",
        },
    ]
    try:
        resp = complete_fn(messages, 0.1)
        raw = message_text_fn(resp["choices"][0]["message"])
        return parse_emotion_json(raw)
    except Exception:
        logger.exception("emotion classify failed")
        return "neutral"


def pick_emotion_only(
    final_response: dict,
    *,
    skip_voice: bool,
    complete_fn: Callable[[list[dict], float], dict] | None = None,
    message_text_fn: Callable[[Any], str] | None = None,
    on_progress: Callable[..., Any] | None = None,
) -> tuple[dict, str | None]:
    """
    Fast path: attach blossom_emotion only (no TTS).
    Returns (response, speak_text_or_None).
    """
    if not VOICE_ENABLED or skip_voice:
        return final_response, None

    try:
        assistant_text = (
            message_text_fn(final_response["choices"][0]["message"])
            if message_text_fn
            else ""
        )
    except Exception:
        assistant_text = ""
    if not assistant_text.strip():
        return final_response, None

    def _thought(step: str, message: str) -> None:
        if on_progress:
            on_progress(
                {
                    "object": "blossom.thought",
                    "step": step,
                    "message": message,
                    "ts": time.time(),
                }
            )

    _thought("voice_emotion", f"Picking emotion ({VOICE_EMOTION_MODE})…")
    emotion = resolve_emotion(
        assistant_text,
        complete_fn=complete_fn,
        message_text_fn=message_text_fn,
    )
    final_response["blossom_emotion"] = emotion
    if emotion not in SPEAK_EMOTIONS:
        _thought("voice_skip", f"Skip TTS (emotion={emotion}).")
        return final_response, None
    return final_response, assistant_text


def synthesize_and_attach(
    final_response: dict,
    assistant_text: str,
    *,
    locale: str = "ja",
    voice_id: str | None = None,
    complete_fn: Callable[[list[dict], float], dict] | None = None,
    message_text_fn: Callable[[Any], str] | None = None,
    on_progress: Callable[..., Any] | None = None,
) -> dict:
    """Blocking TTS+RVC call; attach blossom_audio_url.

    JA → Style-Bert-VITS2 → RVC. EN → Edge TTS → character RVC.
    voice_id selects Voice/characters/<voice_id>/{Jpn,Eng}/ (service default if omitted).
    """
    del complete_fn, message_text_fn  # kept for call-site compatibility
    emotion = str(final_response.get("blossom_emotion") or "").strip().lower()
    if emotion not in SPEAK_EMOTIONS:
        return final_response

    def _thought(step: str, message: str) -> None:
        if on_progress:
            on_progress(
                {
                    "object": "blossom.thought",
                    "step": step,
                    "message": message,
                    "ts": time.time(),
                }
            )

    locale = normalize_locale(locale)
    speech = truncate_for_speech(assistant_text)
    if not speech:
        _thought("voice_skip", "Empty speech text; skipping TTS.")
        return final_response

    vid = (voice_id or "").strip() or None
    tag = f"emotion={emotion}, locale={locale}" + (f", voice={vid}" if vid else "")
    _thought("voice_speak", f"Synthesizing speech ({tag})…")
    path = request_speech(speech, emotion, locale=locale, voice_id=vid)
    if path is None:
        _thought("voice_error", "Voice service failed; continuing without audio.")
        return final_response

    final_response["blossom_audio_url"] = audio_url_for_path(path)
    final_response["blossom_locale"] = locale
    if vid:
        final_response["blossom_voice_id"] = vid
    _thought("voice_ready", f"Audio ready ({tag}).")
    return final_response


def maybe_attach_voice(
    final_response: dict,
    *,
    skip_voice: bool,
    complete_fn: Callable[[list[dict], float], dict],
    message_text_fn: Callable[[Any], str],
    on_progress: Callable[..., Any] | None = None,
    defer_speak: bool = False,
    locale: str = "ja",
    voice_id: str | None = None,
) -> tuple[dict, str | None]:
    """
    Classify emotion; optionally synthesize now.
    When defer_speak=True, returns speak text for a later synthesize_and_attach call.
    """
    final_response["blossom_locale"] = normalize_locale(locale)
    final_response, speak_text = pick_emotion_only(
        final_response,
        skip_voice=skip_voice,
        complete_fn=complete_fn,
        message_text_fn=message_text_fn,
        on_progress=on_progress,
    )
    if not speak_text or defer_speak:
        return final_response, speak_text
    return synthesize_and_attach(
        final_response,
        speak_text,
        locale=locale,
        voice_id=voice_id,
        complete_fn=complete_fn,
        message_text_fn=message_text_fn,
        on_progress=on_progress,
    ), None


def voice_service_healthy() -> bool:
    if not VOICE_ENABLED:
        return False
    try:
        req = Request(f"{VOICE_SERVICE_URL}/health", method="GET")
        with urlopen(req, timeout=2.0) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            return bool(body.get("ok"))
    except Exception:
        return False


def list_voice_packs() -> dict:
    """Proxy helper: GET voice service /v1/voices (or empty when disabled)."""
    if not VOICE_ENABLED:
        return {"ok": False, "voices": [], "default_voice": None}
    try:
        req = Request(f"{VOICE_SERVICE_URL}/v1/voices", method="GET")
        with urlopen(req, timeout=3.0) as resp:
            body = json.loads(resp.read().decode("utf-8", errors="replace"))
            if isinstance(body, dict):
                return body
    except Exception as exc:
        logger.warning("list voices failed: %s", exc)
    return {"ok": False, "voices": [], "default_voice": None}


def request_speech(
    text: str,
    emotion: str,
    *,
    locale: str = "ja",
    voice_id: str | None = None,
) -> Path | None:
    """POST /v1/speak → save WAV under cache; return path or None on failure."""
    emotion = (emotion or "").strip().lower()
    if emotion not in SPEAK_EMOTIONS:
        return None
    speech = truncate_for_speech(text)
    if not speech:
        return None

    ensure_cache_dir()
    audio_id = str(uuid.uuid4())
    out_path = VOICE_CACHE_DIR / f"{audio_id}.wav"
    payload_obj: dict[str, Any] = {
        "text": speech,
        "emotion": emotion,
        "locale": normalize_locale(locale),
    }
    vid = (voice_id or "").strip()
    if vid:
        payload_obj["voice_id"] = vid
    payload = json.dumps(payload_obj, ensure_ascii=False).encode("utf-8")
    req = Request(
        f"{VOICE_SERVICE_URL}/v1/speak",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(req, timeout=VOICE_TIMEOUT_SEC) as resp:
            data = resp.read()
            if not data:
                logger.warning("voice service returned empty body")
                return None
            out_path.write_bytes(data)
            return out_path
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        logger.warning("voice speak HTTP %s: %s", exc.code, detail)
        return None
    except URLError as exc:
        logger.warning("voice service unreachable: %s", exc)
        return None
    except Exception:
        logger.exception("voice speak failed")
        return None


def audio_url_for_path(path: Path) -> str:
    return f"/v1/audio/{path.stem}"


def resolve_audio_path(audio_id: str) -> Path | None:
    """Path-safe lookup: UUID-like stem only."""
    stem = (audio_id or "").strip()
    if not re.fullmatch(r"[0-9a-fA-F-]{36}", stem):
        return None
    path = (VOICE_CACHE_DIR / f"{stem}.wav").resolve()
    try:
        path.relative_to(VOICE_CACHE_DIR.resolve())
    except ValueError:
        return None
    if path.is_file():
        return path
    return None
