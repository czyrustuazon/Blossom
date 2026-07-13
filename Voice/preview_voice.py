"""Offline CLI to preview JA Style-Bert-VITS2 → RVC for one emotion.

Uses the same VoicePipeline as service.py.

Example:
  python preview_voice.py happy
  python preview_voice.py angry --text "いい加減にしてよ！"
  python preview_voice.py happy --voice VOICE
"""
from __future__ import annotations

import argparse

from pipeline import get_pipeline, wav_bytes
from voices import characters_root, discover_voices

ROOT = __import__("pathlib").Path(__file__).resolve().parent
OUTPUT = ROOT / "output.wav"
CHARACTERS = characters_root(ROOT)

# Sample lines for offline listen tests (style/pitch still come from presets.yaml).
SAMPLE_TEXT = {
    "angry": "いい加減にしてよ！なんで毎回こんな適当なことばかりするの！もう我慢できない！",
    "happy": "やったー！うまくいったよ！最高の一日になりそう！",
    "sad": "どうして…私だけいつもこうなるの？もう何もかも嫌になってきた…",
    "surprise": "えっ、本気で！？そんなのありえないよ！信じられない！",
    "fear": "やめて…近づかないで！怖いよ、お願いだから！",
    "disgust": "うわ、気持ち悪い…そんなの絶対に嫌だよ、近づかないで！",
}


def main() -> None:
    pipe = get_pipeline()
    packs = discover_voices(CHARACTERS)
    pack_ids = [p.id for p in packs]

    parser = argparse.ArgumentParser(description="Emotion voice listening test (JA)")
    parser.add_argument(
        "emotion",
        nargs="?",
        default="happy",
        choices=pipe.emotion_keys,
        help="Emotion preset (default: happy)",
    )
    parser.add_argument(
        "--text",
        default=None,
        help="Optional custom Japanese text",
    )
    parser.add_argument(
        "--voice",
        default=None,
        help=f"Voice pack id (discovered: {', '.join(pack_ids) or 'none'})",
    )
    args = parser.parse_args()

    text = args.text or SAMPLE_TEXT.get(args.emotion) or "テストです。"
    print(f"emotion={args.emotion!r} voice={args.voice or pipe.default_voice or '(first)'}")
    print(f"Text: {text}")

    sr, pcm = pipe.speak(text, args.emotion, locale="ja", voice_id=args.voice)
    OUTPUT.write_bytes(wav_bytes(sr, pcm))
    print(f"Done -> {OUTPUT} ({sr} Hz, {len(pcm)} samples)")


if __name__ == "__main__":
    main()
