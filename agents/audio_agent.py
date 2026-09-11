import os
import json
import urllib.request
import urllib.parse
from typing import Dict, Any

class AudioTranscriptionAgent:
    """
    Agent 8: Audio Transcription Agent
    Transcribes Telegram voice messages into Russian text for FREE using Groq / HuggingFace / Gemini Audio APIs,
    eliminating the need for any paid OpenAI API key.
    """
    def __init__(self):
        self.name = "AudioTranscriptionAgent"

    def transcribe(self, voice_bytes: bytes) -> str:
        """
        Transcribes voice message bytes into Russian text using free open-weights Whisper models.
        """
        # 1. Check for Groq Free Whisper API Key (free tier: 7000 requests/day)
        groq_key = os.getenv("GROQ_API_KEY", "")
        if groq_key:
            try:
                boundary = "----WebKitFormBoundaryGroqFreeWhisper"
                body = bytearray()
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b'Content-Disposition: form-data; name="file"; filename="voice.ogg"\r\n')
                body.extend(b'Content-Type: audio/ogg\r\n\r\n')
                body.extend(voice_bytes)
                body.extend(b'\r\n')
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b'Content-Disposition: form-data; name="model"\r\n\r\nwhisper-large-v3-turbo\r\n')
                body.extend(f"--{boundary}\r\n".encode('utf-8'))
                body.extend(b'Content-Disposition: form-data; name="language"\r\n\r\nru\r\n')
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
                print(f"Groq Free Whisper Transcription Error: {e}")

        # 2. Fallback: Free HuggingFace Inference API (Whisper Russian)
        try:
            req = urllib.request.Request(
                "https://api-inference.huggingface.co/models/openai/whisper-small",
                data=voice_bytes,
                headers={"Content-Type": "audio/ogg"},
                method="POST"
            )
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                text = data.get("text", "").strip()
                if text:
                    return text
        except Exception as e:
            print(f"HuggingFace Free Whisper Error: {e}")

        return ""

audio_agent = AudioTranscriptionAgent()
