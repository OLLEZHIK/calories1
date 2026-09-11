from http.server import BaseHTTPRequestHandler
import json
import os
import sys
from pathlib import Path
import urllib.request
import urllib.parse

# Ensure root path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.telegram_bot import process_user_meal_input

def send_telegram_message(token: str, chat_id: int, text: str):
    """Sends reply back to Telegram user via Telegram Bot API."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown"
    }
    headers = {"Content-Type": "application/json"}
    req = urllib.request.Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers, method="POST")
    try:
        urllib.request.urlopen(req)
    except Exception as e:
        print(f"Error sending Telegram message: {e}")

def transcribe_telegram_voice(token: str, file_id: str) -> str:
    """Downloads voice message from Telegram API and transcribes it via OpenAI Whisper if API key is present."""
    openai_key = os.getenv("OPENAI_API_KEY", "")
    if not openai_key:
        return ""

    try:
        # Get file path from Telegram
        get_file_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
        req = urllib.request.Request(get_file_url)
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            file_path = data.get("result", {}).get("file_path")

        if not file_path:
            return ""

        # Download voice file
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        voice_req = urllib.request.Request(download_url)
        with urllib.request.urlopen(voice_req) as resp:
            voice_bytes = resp.read()

        # Send to OpenAI Whisper Transcribe API
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
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
        whisper_req = urllib.request.Request("https://api.openai.com/v1/audio/transcriptions", data=bytes(body), headers=headers, method="POST")
        with urllib.request.urlopen(whisper_req) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))
            return res_data.get("text", "")

    except Exception as e:
        print(f"Voice Transcription Error: {e}")
        return ""

class handler(BaseHTTPRequestHandler):
    def do_POST(self):
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        content_length = int(self.headers.get('Content-Length', 0))
        post_data = self.rfile.read(content_length).decode('utf-8')
        
        try:
            update = json.loads(post_data)
            message = update.get("message", {})
            chat_id = message.get("chat", {}).get("id")
            
            text = message.get("text", "") or message.get("caption", "")
            voice = message.get("voice")

            if chat_id:
                if voice:
                    file_id = voice.get("file_id")
                    transcription = transcribe_telegram_voice(token, file_id) if file_id else ""
                    if transcription:
                        reply = f"🎤 **Распознанный голос**: '{transcription}'\n\n" + process_user_meal_input(transcription, input_type="voice")
                    else:
                        reply = "🎤 **Голосовое сообщение получено!**\nДля автоматической расшифровки аудио укажите `OPENAI_API_KEY` в файле `.env` или напишите еду текстом."
                    send_telegram_message(token, chat_id, reply)

                elif text:
                    if text == "/start":
                        reply = "👋 Привет! Я твой ИИ-ассистент по питанию (Calories AI).\nЗаписывай еду текстом или голосом!"
                    elif text == "/summary":
                        from database.db import get_today_summary
                        today = get_today_summary()
                        reply = f"📊 **Итоги за сегодня ({today['date']})**:\n🔥 **Калории**: {today['total_calories']}/{today['goals']['calories']} ккал\n🥩 **Белки**: {today['total_protein']}g\n🥑 **Жиры**: {today['total_fat']}g\n🍚 **Углеводы**: {today['total_carbs']}g"
                    else:
                        reply = process_user_meal_input(text, input_type="webhook")
                    send_telegram_message(token, chat_id, reply)

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(b'{"status": "ok"}')

        except Exception as e:
            self.send_response(500)
            self.end_headers()
            self.wfile.write(f'{{"error": "{str(e)}"}}'.encode('utf-8'))
