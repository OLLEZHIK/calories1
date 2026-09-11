import os
import json
import base64
import urllib.request
import urllib.parse
from typing import Dict, Any

class AudioTranscriptionAgent:
    """
    Agent 8: Audio Transcription Agent
    Transcribes Telegram voice messages into Russian text using Speech-to-Text inference models.
    """
    def __init__(self):
        self.name = "AudioTranscriptionAgent"

    def transcribe(self, voice_bytes: bytes) -> str:
        if not voice_bytes:
            return ""

        speech_key = os.getenv("SPEECH_API_KEY") or os.getenv("HF_API_TOKEN") or os.getenv("GROQ_API_KEY") or os.getenv("GEMINI_API_KEY", "")

        # 1. HuggingFace Whisper Large V3 API with Speech API Token
        if speech_key:
            try:
                headers = {
                    "Authorization": f"Bearer {speech_key}",
                    "Content-Type": "audio/ogg"
                }
                req = urllib.request.Request(
                    "https://api-inference.huggingface.co/models/openai/whisper-large-v3",
                    data=voice_bytes,
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    if isinstance(data, dict):
                        text = data.get("text", "").strip()
                        if text:
                            return text
            except Exception as e:
                print(f"HuggingFace Whisper Large V3 Error: {e}")

        # 2. Try Yandex SpeechKit / STT REST fallback
        if speech_key:
            try:
                headers = {
                    "Authorization": f"Bearer {speech_key}",
                    "Content-Type": "audio/ogg"
                }
                req = urllib.request.Request(
                    "https://stt.api.yandex.cloud/speech/v1/stt:recognize?topic=general&lang=ru-RU",
                    data=voice_bytes,
                    headers=headers,
                    method="POST"
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    text = data.get("result", "").strip()
                    if text:
                        return text
            except Exception as e:
                print(f"Yandex SpeechKit Error: {e}")

        # 3. Fallback Gemini Audio API
        gemini_key = os.getenv("GEMINI_API_KEY", "") or speech_key
        if gemini_key:
            try:
                b64_audio = base64.b64encode(voice_bytes).decode('utf-8')
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": "Точно расшифруй это аудиосообщение о еде на русском языке. Верни ТОЛЬКО расшифрованный текст продуктов."},
                            {"inline_data": {"mime_type": "audio/ogg", "data": b64_audio}}
                        ]
                    }]
                }
                headers = {"Content-Type": "application/json"}
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "").strip()
                            if text:
                                return text
            except Exception as e:
                print(f"Gemini Audio Error: {e}")

        return ""

audio_agent = AudioTranscriptionAgent()
