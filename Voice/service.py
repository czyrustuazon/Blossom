"""FastAPI voice service: JA (SBV2) or EN (Edge) → character RVC → WAV.

Character packs are auto-discovered under Voice/characters/<voice_id>/{Jpn,Eng}/.

    python -m uvicorn service:app --host 127.0.0.1 --port 8090
"""
from __future__ import annotations

import logging
import os
import sys
from contextlib import asynccontextmanager
from typing import Literal

import uvicorn
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel, Field

try:
    from pipeline import get_pipeline, normalize_locale, wav_bytes
except ModuleNotFoundError as exc:
    print(
        "Missing Voice dependency:",
        getattr(exc, "name", None) or exc,
        "\nInstall CUDA torch, then: pip install -r requirements.txt",
        file=sys.stderr,
    )
    raise

logging.basicConfig(level=logging.INFO, format="[Voice]: %(message)s")
logger = logging.getLogger(__name__)

EmotionName = Literal[
    "angry", "happy", "sad", "surprise", "fear", "disgust", "neutral"
]
LocaleName = Literal["ja", "en", "japanese", "english"]

HOST = os.getenv("VOICE_HOST", "127.0.0.1")
PORT = int(os.getenv("VOICE_PORT", "8090"))
PRELOAD = os.getenv("VOICE_PRELOAD", "true").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


class SpeakRequest(BaseModel):
    text: str = Field(..., min_length=1)
    emotion: EmotionName
    locale: LocaleName = "ja"
    voice_id: str | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    if PRELOAD:
        logger.info("Preloading SBV2 + default RVC…")
        try:
            get_pipeline().ensure_loaded()
        except Exception:
            logger.exception("Model preload failed; will retry on first /v1/speak")
    yield


app = FastAPI(title="Blossom Voice", version="1.2.0", lifespan=lifespan)


@app.get("/health")
def health():
    pipe = get_pipeline()
    voices = pipe.list_voices()
    return {
        "ok": True,
        "ready": pipe._sbv2_ready,
        "device": pipe.device,
        "emotions": pipe.emotion_keys,
        "locales": ["ja", "en"],
        "voices": voices,
        "default_voice": pipe.default_voice,
        "edge_voice": pipe.edge_voice,
        "python": sys.executable,
        "rvc_loaded": [
            {"voice_id": vid, "locale": loc} for (vid, loc) in pipe._rvc_cache
        ],
    }


@app.get("/v1/voices")
def list_voices():
    pipe = get_pipeline()
    return {
        "ok": True,
        "default_voice": pipe.default_voice,
        "voices": pipe.list_voices(),
    }


@app.post("/v1/speak")
def speak(body: SpeakRequest):
    pipe = get_pipeline()
    locale = normalize_locale(body.locale)
    voice_id = (body.voice_id or "").strip() or None
    try:
        sr, pcm = pipe.speak(
            body.text,
            body.emotion,
            locale=locale,
            voice_id=voice_id,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("speak failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    resolved = pipe.resolve_pack(voice_id).id
    data = wav_bytes(sr, pcm)
    return Response(
        content=data,
        media_type="audio/wav",
        headers={
            "X-Sample-Rate": str(sr),
            "X-Emotion": body.emotion,
            "X-Locale": locale,
            "X-Voice-Id": resolved,
            "Content-Disposition": 'inline; filename="speak.wav"',
        },
    )


if __name__ == "__main__":
    uvicorn.run("service:app", host=HOST, port=PORT, reload=False)
