import os
import json
import base64
import urllib.request
import urllib.parse
from typing import Dict, Any

class AudioTranscriptionAgent:
    """
    Agent 8: Audio Transcription Agent
    Transcribes Telegram voice messages into Russian text for FREE using Gemini Audio API,
    Groq Free Whisper, OpenAI Whisper, or HuggingFace endpoints.
    """
    def __init__(self):
        self.name = "AudioTranscriptionAgent"

    def transcribe(self, voice_bytes: bytes) -> str:
        if not voice_bytes:
            return ""

        # 1. Try Gemini Audio API (Gemini 1.5 Flash natively transcribes .ogg audio)
        gemini_key = os.getenv("GEMINI_API_KEY", "")
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
                print(f"Gemini Audio Transcription Error: {e}")

        # 2. Try OpenAI Whisper API if key present
        openai_key = os.getenv("OPENAI_API_KEY", "")
        if openai_key:
            try:
                boundary = "----WebKitFormBoundaryWhisperReq"
                body = bytearray()
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b'Content-Disposition: form-data; name="file"; filename="voice.ogg"\r\n')
                body.extend(b'Content-Type: audio/ogg\r\n\r\n')
                body.extend(voice_bytes)
                body.extend(b'\r\n')
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-1\r\n')
                body.extend(f"--{boundary}--\r\n".encode('utf-8'))

                headers = {
                    "Authorization": f"Bearer {openai_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}"
                }
                req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=bytes(body), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    text = data.get("text", "").strip()
                    if text:
                        return text
            except Exception as e:
                print(f"OpenAI Whisper Error: {e}")

        # 3. Try Groq Free Whisper API if key present
        groq_key = os.getenv("GROQ_API_KEY", "")
        if groq_key:
            try:
                boundary = "----WebKitFormBoundaryGroqReq"
                body = bytearray()
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b'Content-Disposition: form-data; name="file"; filename="voice.ogg"\r\n')
                body.extend(b'Content-Type: audio/ogg\r\n\r\n')
                body.extend(voice_bytes)
                body.extend(b'\r\n')
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-large-v3-turbo\r\n')
                body.extend(f"--{boundary}--\r\n".encode('utf-8'))

                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": f"multipart/form-data; boundary={boundary}"
                }
                req = urllib.request.Request("https://api.groq.com/openai/v1/audio/transcriptions", data=bytes(body), headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=10) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    text = data.get("text", "").strip()
                    if text:
                        return text
            except Exception as e:
                print(f"Groq Whisper Error: {e}")

        return ""

audio_agent = AudioTranscriptionAgent()
