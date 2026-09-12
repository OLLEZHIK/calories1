import os
import json
import base64
import urllib.request
import urllib.parse
from typing import Dict, Any


class AudioTranscriptionAgent:
    """
    Agent 8: Audio Transcription Agent
    Priority order for transcription:
      1. Gemini 1.5 Flash Audio  (GEMINI_API_KEY=AIza...)  — multimodal, understands OGG natively
      2. Groq Whisper Large V3   (GROQ_API_KEY=gsk_...)    — fast, accurate
      3. Yandex SpeechKit        (YANDEX_SPEECH_KEY=AQ...) — Russian-optimized
      4. HuggingFace Whisper     (HF_API_TOKEN=hf_...)     — fallback
    """

    def __init__(self):
        self.name = "AudioTranscriptionAgent"

    def transcribe(self, voice_bytes: bytes) -> Dict[str, Any]:
        if not voice_bytes:
            return {"text": "", "error": "Empty audio payload"}

        errors = []

        # ── 1. Gemini Audio (primary when a Gemini client is configured) ──
        from gemini_client import get_genai_client
        client = get_genai_client()
        if client:
            try:
                from google.genai import types
                model = os.getenv("GEMINI_AUDIO_MODEL", "gemini-3.6-flash")
                b64_audio = base64.b64encode(voice_bytes).decode("utf-8")
                resp = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Content(role="user", parts=[
                            types.Part(text=(
                                "Точно расшифруй это голосовое сообщение на русском языке. "
                                "Верни ТОЛЬКО расшифрованный текст без комментариев."
                            )),
                            types.Part(
                                inline_data=types.Blob(
                                    mime_type="audio/ogg",
                                    data=base64.b64decode(b64_audio)
                                )
                            )
                        ])
                    ]
                )
                text = (resp.text or "").strip()
                if text:
                    return {"text": text, "engine": "Gemini Audio", "error": None}
            except Exception as e:
                err_msg = f"Gemini Audio Error: {e}"
                print(err_msg)
                errors.append(err_msg)

        # ── 2. Groq Whisper Large V3 ──────────────────────────────────────
        groq_key = os.getenv("GROQ_API_KEY", "").strip() or os.getenv("SPEECH_API_KEY", "").strip()
        if groq_key and groq_key.startswith("gsk_"):
            try:
                boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
                body = []
                body.append(f"--{boundary}".encode("utf-8"))
                body.append(b'Content-Disposition: form-data; name="file"; filename="voice.ogg"')
                body.append(b"Content-Type: audio/ogg\r\n")
                body.append(voice_bytes)
                body.append(f"--{boundary}".encode("utf-8"))
                body.append(b'Content-Disposition: form-data; name="model"\r\n')
                body.append(b"whisper-large-v3-turbo")
                body.append(f"--{boundary}".encode("utf-8"))
                body.append(b'Content-Disposition: form-data; name="language"\r\n')
                body.append(b"ru")
                body.append(f"--{boundary}--\r\n".encode("utf-8"))

                payload = b"\r\n".join(body)
                headers = {
                    "Authorization": f"Bearer {groq_key}",
                    "User-Agent": "curl/7.68.0",
                    "Content-Type": f"multipart/form-data; boundary={boundary}",
                }
                req = urllib.request.Request(
                    "https://api.groq.com/openai/v1/audio/transcriptions",
                    data=payload, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=15) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("text", "").strip()
                    if text:
                        return {"text": text, "engine": "Groq Whisper V3", "error": None}
            except Exception as e:
                err_msg = f"Groq Error: {e}"
                print(err_msg)
                errors.append(err_msg)

        # ── 3. Yandex SpeechKit ───────────────────────────────────────────
        yandex_key = os.getenv("YANDEX_SPEECH_KEY", "").strip()
        if not yandex_key:
            # Also check generic SPEECH_API_KEY for Yandex format
            sp = os.getenv("SPEECH_API_KEY", "").strip()
            if sp.startswith("AQ"):
                yandex_key = sp
        if yandex_key and yandex_key.startswith("AQ"):
            try:
                headers = {
                    "Authorization": f"Api-Key {yandex_key}",
                    "Content-Type": "audio/ogg",
                }
                url = "https://stt.api.cloud.yandex.net/speech/v1/stt:recognize?topic=general&lang=ru-RU"
                req = urllib.request.Request(url, data=voice_bytes, headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    text = data.get("result", "").strip()
                    if text:
                        return {"text": text, "engine": "Yandex SpeechKit", "error": None}
            except Exception as e:
                err_body = ""
                if hasattr(e, "read"):
                    try:
                        err_body = e.read().decode("utf-8")
                    except Exception:
                        pass
                err_msg = f"Yandex STT Error: {e} {err_body}".strip()
                print(err_msg)
                errors.append(err_msg)

        # ── 4. HuggingFace Whisper ────────────────────────────────────────
        hf_key = os.getenv("HF_API_TOKEN", "").strip()
        if hf_key and hf_key.startswith("hf_"):
            try:
                headers = {
                    "Authorization": f"Bearer {hf_key}",
                    "Content-Type": "audio/ogg",
                }
                req = urllib.request.Request(
                    "https://api-inference.huggingface.co/models/openai/whisper-large-v3",
                    data=voice_bytes, headers=headers, method="POST"
                )
                with urllib.request.urlopen(req, timeout=12) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    if isinstance(data, dict):
                        text = data.get("text", "").strip()
                        if text:
                            return {"text": text, "engine": "HuggingFace Whisper", "error": None}
            except Exception as e:
                err_msg = f"HuggingFace Whisper Error: {e}"
                print(err_msg)
                errors.append(err_msg)

        return {
            "text": "",
            "error": " | ".join(errors) if errors else "No active speech recognition API key found.",
        }


audio_agent = AudioTranscriptionAgent()
