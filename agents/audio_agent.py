import os
import json
import base64
import urllib.request
import urllib.parse
from typing import Dict, Any

class AudioTranscriptionAgent:
    """
    Agent 8: Audio Transcription Agent
    Transcribes Telegram voice messages into Russian text using:
    - Yandex SpeechKit (API Key starting with AQVN or AQ)
    - Groq Whisper Large V3 (API Key starting with gsk_)
    - OpenAI Whisper (API Key starting with sk-)
    - Gemini 1.5 Flash Audio (API Key starting with AIza)
    - HuggingFace Whisper (API Key starting with hf_)
    """
    def __init__(self):
        self.name = "AudioTranscriptionAgent"

    def transcribe(self, voice_bytes: bytes) -> Dict[str, Any]:
        if not voice_bytes:
            return {"text": "", "error": "Empty audio payload"}

        speech_key = os.getenv("SPEECH_API_KEY", "").strip() or os.getenv("GROQ_API_KEY", "").strip() or os.getenv("HF_API_TOKEN", "").strip() or os.getenv("GEMINI_API_KEY", "").strip() or os.getenv("OPENAI_API_KEY", "").strip()


        errors = []

        # 1. Groq Whisper Large V3 (Key starts with gsk_)
        if speech_key.startswith("gsk_"):
            try:
                boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
                body = []
                body.append(f"--{boundary}".encode('utf-8'))
                body.append(b'Content-Disposition: form-data; name="file"; filename="voice.ogg"')
                body.append(b'Content-Type: audio/ogg\r\n')
                body.append(voice_bytes)
                body.append(f"--{boundary}".encode('utf-8'))
                body.append(b'Content-Disposition: form-data; name="model"\r\n')
                body.append(b'whisper-large-v3-turbo')
                body.append(f"--{boundary}".encode('utf-8'))
                body.append(b'Content-Disposition: form-data; name="language"\r\n')
                body.append(b'ru')
                body.append(f"--{boundary}--\r\n".encode('utf-8'))
                
                payload = b"\r\n".join(body)
                headers = {
                    "Authorization": f"Bearer {speech_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}"
                }
                req = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", data=payload, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    text = data.get("text", "").strip()
                    if text:
                        return {"text": text, "engine": "Groq Whisper V3", "error": None}
            except Exception as e:
                err_msg = f"Groq Error: {e}"
                print(err_msg)
                errors.append(err_msg)

        # 2. Yandex SpeechKit REST v1 (Correct Endpoint: stt.api.cloud.yandex.net)
        if speech_key.startswith("AQ"):
            try:
                headers = {
                    "Authorization": f"Api-Key {speech_key}",
                    "Content-Type": "audio/ogg"
                }
                url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize?topic=general&lang=ru-RU"
                req = urllib.request.Request(url, data=voice_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    text = data.get("result", "").strip()
                    if text:
                        return {"text": text, "engine": "Yandex SpeechKit", "error": None}
            except Exception as e:
                err_body = ""
                if hasattr(e, 'read'):
                    try:
                        err_body = e.read().decode('utf-8')
                    except Exception:
                        pass
                err_msg = f"Yandex STT Error: {e} {err_body}".strip()
                print(err_msg)
                errors.append(err_msg)

        # 3. Gemini 1.5 Flash Audio API (Key MUST start with AIza)
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key and speech_key.startswith("AIza"):
            gemini_key = speech_key

        if gemini_key and gemini_key.startswith("AIza"):
            try:
                b64_audio = base64.b64encode(voice_bytes).decode('utf-8')
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent?key={gemini_key}"
                payload = {
                    "contents": [{
                        "parts": [
                            {"text": "Точно расшифруй это голосовое сообщение о еде на русском языке. Верни ТОЛЬКО расшифрованный текст продуктов без лишних комментариев."},
                            {"inline_data": {"mime_type": "audio/ogg", "data": b64_audio}}
                        ]
                    }]
                }
                headers = {"Content-Type": "application/json"}
                req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    candidates = data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            text = parts[0].get("text", "").strip()
                            if text:
                                return {"text": text, "engine": "Gemini Audio", "error": None}
            except Exception as e:
                err_msg = f"Gemini Audio Error: {e}"
                print(err_msg)
                errors.append(err_msg)


        # 4. HuggingFace Whisper (Key starts with hf_)
        if speech_key.startswith("hf_"):
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
                            return {"text": text, "engine": "HuggingFace Whisper", "error": None}
            except Exception as e:
                err_msg = f"HuggingFace Whisper Error: {e}"
                print(err_msg)
                errors.append(err_msg)

        return {"text": "", "error": " | ".join(errors) if errors else "No active speech recognition API key found."}

audio_agent = AudioTranscriptionAgent()

