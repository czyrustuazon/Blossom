"""Warm Style-Bert-VITS2 / Edge TTS → character RVC pipeline (singleton).

Character packs live under Voice/characters/<voice_id>/{Jpn,Eng}/ (auto-discovered).
presets.yaml holds shared emotion / Edge / SBV2 knobs plus optional default_voice.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import re
import tempfile
import threading
from functools import wraps
from pathlib import Path

import numpy as np
import torch
import torchaudio
import yaml
from huggingface_hub import hf_hub_download
from scipy.io import wavfile

# PyTorch 2.6+ defaults weights_only=True; fairseq Hubert checkpoints need False.
_orig_load = torch.load


@wraps(_orig_load)
def _load(*args, **kwargs):
    kwargs.setdefault("weights_only", False)
    return _orig_load(*args, **kwargs)


torch.load = _load

from style_bert_vits2.constants import Languages
from style_bert_vits2.nlp import bert_models
from style_bert_vits2.tts_model import TTSModel
from rvc_python.infer import RVCInference

from voices import characters_root, discover_voices, resolve_voice_id

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent
ASSETS = ROOT / "model_assets"
PRESETS_PATH = ROOT / "presets.yaml"
CHARACTERS = characters_root(ROOT)

_SENTENCE_RE = re.compile(r"(?<=[。！？!?…])\s*")
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
_STAGE_LINE_MD_RE = re.compile(r"(?m)^\s*\*[^*\n]{1,100}\*\s*$")
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
_MD_BOLD_ITALIC_RE = re.compile(r"\*{1,3}([^*\n]+?)\*{1,3}")
_MD_UNDERSCORE_RE = re.compile(r"_{1,3}([^_\n]+?)_{1,3}")
_STRAY_EMPHASIS_RE = re.compile(r"[*_`]{1,}")


def load_presets(path: Path | None = None) -> dict:
    p = path or PRESETS_PATH
    with open(p, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def strip_emojis_for_speech(text: str) -> str:
    """Remove emoji, stage directions, and markdown so TTS stays spoken dialogue."""
    cleaned = text or ""
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


def truncate_for_speech(text: str, max_chars: int) -> str:
    """Cap length for TTS; allow a soft overrun so the last sentence isn't dropped."""
    text = strip_emojis_for_speech(text)
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    soft = min(len(text), max(max_chars, max_chars + 160))
    window = text[:soft]
    best = -1
    for sep in ("。", "！", "？", "!", "?", "…", "\n", "."):
        idx = window.rfind(sep)
        if idx >= max_chars // 4:
            best = max(best, idx)
    if best >= 0:
        return window[: best + 1].strip()
    return text[:max_chars].strip()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in _SENTENCE_RE.split(text) if p and p.strip()]
    return parts or ([text.strip()] if text.strip() else [])


def normalize_locale(raw: str | None) -> str:
    value = (raw or "ja").strip().lower()
    if value in {"en", "english", "eng"}:
        return "en"
    return "ja"


class VoicePipeline:
    """Loads SBV2 once; lazy-loads RVC per (voice_id, locale)."""

    def __init__(self, presets: dict | None = None) -> None:
        self.presets = presets or load_presets()
        shared = self.presets.get("shared") or {}
        self.style_weight = float(shared.get("style_weight", 2.5))
        self.sdp_ratio = float(shared.get("sdp_ratio", 0.6))
        self.index_rate = float(shared.get("index_rate", 0.2))
        self.protect = float(shared.get("protect", 0.4))
        self.f0method = str(shared.get("f0method", "rmvpe"))
        self.emotions: dict = self.presets.get("emotions") or {}
        en_cfg = self.presets.get("english") or {}
        self.edge_voice = str(en_cfg.get("voice") or "en-US-AvaNeural")
        self.en_index_rate = float(en_cfg.get("index_rate", self.index_rate))
        self.en_protect = float(en_cfg.get("protect", self.protect))
        self.en_pitch_offset = int(en_cfg.get("pitch_offset", 0))
        # pm/dio/harvest faster than rmvpe; EN speech usually fine with pm
        self.en_f0method = str(en_cfg.get("f0method") or self.f0method)
        self.default_voice = str(self.presets.get("default_voice") or "").strip() or None
        rvc_cfg = self.presets.get("rvc") or {}
        self.rvc_version = str(rvc_cfg.get("version", "v2"))

        pref = self.presets.get("device") or "cuda:0"
        self.device = (
            pref if torch.cuda.is_available() and str(pref).startswith("cuda") else "cpu"
        )

        self._tts: TTSModel | None = None
        self._rvc_cache: dict[tuple[str, str], tuple[RVCInference, Path]] = {}
        self._lock = threading.Lock()
        self._sbv2_ready = False
        self._packs = []
        self.refresh_voices()

    def refresh_voices(self):
        self._packs = discover_voices(CHARACTERS)
        return self._packs

    @property
    def emotion_keys(self) -> list[str]:
        return sorted(self.emotions.keys())

    def list_voices(self) -> list[dict]:
        self.refresh_voices()
        out = []
        for p in self._packs:
            try:
                rel = str(p.path.relative_to(ROOT)).replace("\\", "/")
            except ValueError:
                rel = str(p.path)
            out.append({"id": p.id, "locales": p.locales, "path": rel})
        return out

    def resolve_pack(self, voice_id: str | None):
        packs = self._packs or self.refresh_voices()
        resolved = resolve_voice_id(voice_id, packs, default=self.default_voice)
        if not resolved:
            raise FileNotFoundError(
                "No voice packs found. Add Voice/characters/<Name>/{Jpn,Eng}/*.pth + *.index"
            )
        for pack in packs:
            if pack.id == resolved:
                return pack
        raise FileNotFoundError(f"Unknown voice_id {voice_id!r}")

    def ensure_sbv2(self) -> None:
        with self._lock:
            if self._sbv2_ready:
                return
            self._load_sbv2_unlocked()
            self._sbv2_ready = True

    def ensure_loaded(self) -> None:
        """Warm SBV2 and default voice RVC locales (lazy cache for others)."""
        self.ensure_sbv2()
        try:
            pack = self.resolve_pack(None)
            for loc in pack.locales:
                self._get_rvc(pack.id, loc)
        except Exception:
            logger.exception("Default RVC preload skipped")

    def _ensure_sbv2_assets(self) -> tuple[Path, Path, Path]:
        sbv2 = self.presets["sbv2"]
        files = list(sbv2["files"])
        ASSETS.mkdir(exist_ok=True)
        for file in files:
            hf_hub_download(sbv2["repo"], file, local_dir=str(ASSETS))
        return ASSETS / files[0], ASSETS / files[1], ASSETS / files[2]

    def _load_sbv2_unlocked(self) -> None:
        bert_name = self.presets["sbv2"]["bert_model"]
        logger.info("Loading Japanese BERT (%s)…", bert_name)
        bert = bert_models.load_model(Languages.JP, bert_name)
        bert.float()
        bert_models.load_tokenizer(Languages.JP, bert_name)

        model_path, config_path, style_path = self._ensure_sbv2_assets()
        logger.info("Loading Style-Bert-VITS2 on %s…", self.device)
        self._tts = TTSModel(
            model_path=model_path,
            config_path=config_path,
            style_vec_path=style_path,
            device=self.device,
        )
        logger.info(
            "SBV2 ready; voice packs=%s default=%s",
            [p.id for p in self._packs],
            self.default_voice,
        )

    def _get_rvc(self, voice_id: str | None, locale: str):
        pack = self.resolve_pack(voice_id)
        locale = normalize_locale(locale)
        loc = pack.for_locale(locale)
        if loc is None:
            raise FileNotFoundError(
                f"Voice {pack.id!r} has no {locale} pack under {pack.path}"
            )
        key = (pack.id, locale)
        cached = self._rvc_cache.get(key)
        if cached is not None:
            return cached

        logger.info("Loading RVC %s/%s (%s)…", pack.id, locale, loc.model.name)
        rvc = RVCInference(device=self.device)
        rvc.load_model(
            str(loc.model),
            version=self.rvc_version,
            index_path=str(loc.index),
        )
        self._rvc_cache[key] = (rvc, loc.index)
        return rvc, loc.index

    def _run_rvc(
        self,
        wav_path: str,
        pitch: int,
        *,
        voice_id: str | None,
        locale: str = "ja",
        index_rate: float | None = None,
        protect: float | None = None,
    ) -> tuple[int, np.ndarray]:
        locale = normalize_locale(locale)
        rvc, file_index = self._get_rvc(voice_id, locale)
        if locale == "en":
            default_index = self.en_index_rate
            default_protect = self.en_protect
            f0method = self.en_f0method
        else:
            default_index = self.index_rate
            default_protect = self.protect
            f0method = self.f0method
        use_index = default_index if index_rate is None else float(index_rate)
        use_protect = default_protect if protect is None else float(protect)
        rvc.set_params(
            f0method=f0method,
            f0up_key=pitch,
            index_rate=use_index,
            protect=use_protect,
        )
        result = rvc.vc.vc_single(
            sid=0,
            input_audio_path=wav_path,
            f0_up_key=rvc.f0up_key,
            f0_method=rvc.f0method,
            file_index=str(file_index),
            index_rate=rvc.index_rate,
            filter_radius=rvc.filter_radius,
            resample_sr=rvc.resample_sr,
            rms_mix_rate=rvc.rms_mix_rate,
            protect=rvc.protect,
            f0_file="",
            file_index2="",
        )
        if isinstance(result, tuple):
            raise RuntimeError(f"RVC conversion failed:\n{result[0]}")

        out_sr = int(rvc.vc.tgt_sr)
        pcm = np.asarray(result)
        if pcm.dtype != np.int16:
            pcm_f = np.asarray(pcm, dtype=np.float32).reshape(-1)
            peak = float(np.max(np.abs(pcm_f))) if pcm_f.size else 0.0
            if peak > 1.0 + 1e-3:
                pcm_f = pcm_f / peak
            pcm = np.clip(pcm_f * 32767.0, -32768, 32767).astype(np.int16)
        else:
            pcm = pcm.reshape(-1)
        return out_sr, pcm

    def _synthesize_ja_segment(
        self, text: str, style: str, pitch: int, voice_id: str | None
    ) -> tuple[int, np.ndarray]:
        assert self._tts is not None
        sr, audio = self._tts.infer(
            text=text,
            style=style,
            style_weight=self.style_weight,
            sdp_ratio=self.sdp_ratio,
        )
        audio = np.asarray(audio, dtype=np.float32).reshape(-1)
        peak = float(np.max(np.abs(audio))) if audio.size else 0.0
        if peak > 1e-8:
            audio = audio / peak * 0.89
        audio_i16 = np.clip(audio * 32767.0, -32768, 32767).astype(np.int16)

        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        try:
            wavfile.write(tmp_path, sr, audio_i16)
            return self._run_rvc(tmp_path, pitch, voice_id=voice_id, locale="ja")
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

    def _edge_tts_to_wav(self, text: str, emotion: str) -> str:
        import edge_tts

        preset = self.emotions[emotion]
        rate = str(preset.get("edge_rate") or "+0%")
        pitch = str(preset.get("edge_pitch") or "+0Hz")

        with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as mp3_tmp:
            mp3_path = mp3_tmp.name
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as wav_tmp:
            wav_path = wav_tmp.name

        async def _save() -> None:
            communicate = edge_tts.Communicate(
                text,
                self.edge_voice,
                rate=rate,
                pitch=pitch,
            )
            await communicate.save(mp3_path)

        try:
            asyncio.run(_save())
            waveform, sr = torchaudio.load(mp3_path)
            if waveform.shape[0] > 1:
                waveform = waveform.mean(dim=0, keepdim=True)
            peak = float(waveform.abs().max()) if waveform.numel() else 0.0
            if peak > 1e-8:
                waveform = waveform / peak * 0.89
            torchaudio.save(wav_path, waveform, int(sr))
            return wav_path
        except Exception:
            try:
                os.unlink(wav_path)
            except OSError:
                pass
            raise
        finally:
            try:
                os.unlink(mp3_path)
            except OSError:
                pass

    def _synthesize_en_segment(
        self, text: str, emotion: str, pitch: int, voice_id: str | None
    ) -> tuple[int, np.ndarray]:
        wav_path = self._edge_tts_to_wav(text, emotion)
        try:
            return self._run_rvc(
                wav_path,
                pitch,
                voice_id=voice_id,
                locale="en",
                index_rate=self.en_index_rate,
                protect=self.en_protect,
            )
        finally:
            try:
                os.unlink(wav_path)
            except OSError:
                pass

    def speak(
        self,
        text: str,
        emotion: str,
        *,
        locale: str = "ja",
        voice_id: str | None = None,
        max_chars: int | None = None,
    ) -> tuple[int, np.ndarray]:
        emotion = (emotion or "").strip().lower()
        if emotion not in self.emotions:
            raise ValueError(
                f"Unknown emotion {emotion!r}; expected one of {self.emotion_keys}"
            )
        preset = self.emotions[emotion]
        style = str(preset["style"])
        locale = normalize_locale(locale)
        if locale == "en":
            pitch = int(preset["pitch_en"] if "pitch_en" in preset else preset["pitch"])
            pitch += self.en_pitch_offset
        else:
            pitch = int(preset["pitch"])

        if max_chars is None:
            max_chars = int(os.getenv("VOICE_MAX_CHARS", "400"))
        text = truncate_for_speech(text, max_chars)
        if not text:
            raise ValueError("Empty text after truncation")

        self.ensure_sbv2()
        pack = self.resolve_pack(voice_id)
        if locale not in pack.locales:
            raise ValueError(
                f"Voice {pack.id!r} has no {locale} locale (has {pack.locales})"
            )

        split = os.getenv("VOICE_SPLIT_SENTENCES", "false").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        segments = split_sentences(text) if split else [text]

        with self._lock:
            pieces: list[np.ndarray] = []
            out_sr = 0
            for seg in segments:
                if not seg.strip():
                    continue
                if locale == "en":
                    sr, pcm = self._synthesize_en_segment(seg, emotion, pitch, pack.id)
                else:
                    sr, pcm = self._synthesize_ja_segment(seg, style, pitch, pack.id)
                out_sr = sr
                pieces.append(pcm)
            if not pieces:
                raise ValueError("No synthesizable segments")
            combined = np.concatenate(pieces) if len(pieces) > 1 else pieces[0]
            return out_sr, combined


def wav_bytes(sr: int, pcm: np.ndarray) -> bytes:
    buf = io.BytesIO()
    wavfile.write(buf, sr, pcm)
    return buf.getvalue()


_pipeline: VoicePipeline | None = None
_pipeline_lock = threading.Lock()


def get_pipeline() -> VoicePipeline:
    global _pipeline
    with _pipeline_lock:
        if _pipeline is None:
            _pipeline = VoicePipeline()
        return _pipeline
