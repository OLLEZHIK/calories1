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
from agents.audio_agent import audio_agent

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

def get_telegram_voice_bytes(token: str, file_id: str) -> bytes:
    """Downloads voice message bytes from Telegram API."""
    try:
        get_file_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
        req = urllib.request.Request(get_file_url)
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            file_path = data.get("result", {}).get("file_path")

        if not file_path:
            return b""

        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        voice_req = urllib.request.Request(download_url)
        with urllib.request.urlopen(voice_req, timeout=12) as resp:
            return resp.read()
    except Exception as e:
        print(f"Error downloading Telegram voice file: {e}")
        return b""

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
                    voice_bytes = get_telegram_voice_bytes(token, file_id) if file_id else b""
                    
                    if voice_bytes:
                        result = audio_agent.transcribe(voice_bytes)
                        transcription = result.get("text", "")
                        engine = result.get("engine", "")
                        err = result.get("error", "")

                        if transcription:
                            reply = f"🎤 **Распознано ({engine})**:\n*\"{transcription}\"*\n\n" + process_user_meal_input(transcription, input_type="voice")
                        else:
                            reply = f"⚠️ **Ошибка расшифровки аудио**:\n`{err}`\n\nВы можете вписать еду текстом (например '200г бекона, 5 яиц')."
                    else:
                        reply = "⚠️ Не удалось скачать файл аудиозаписи из Telegram."

                    send_telegram_message(token, chat_id, reply)

                elif text:
                    if text == "/start":
                        reply = "👋 Привет! Я твой ИИ-ассистент по питанию (Calories AI).\nЗаписывай еду текстом или надиктовывай голосом!"
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
            import traceback
            err_trace = traceback.format_exc()
            print(f"Webhook Exception: {err_trace}")
            try:
                update = json.loads(post_data)
                chat_id = update.get("message", {}).get("chat", {}).get("id")
                if chat_id:
                    send_telegram_message(token, chat_id, f"⚠️ **Внутренняя ошибка сервера**:\n`{str(e)}`")
            except Exception:
                pass

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))

