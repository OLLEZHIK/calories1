from http.server import BaseHTTPRequestHandler
import json
import os
import sys
from pathlib import Path

# Ensure root path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from bot.telegram_bot import process_user_meal_input
import urllib.request

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

            if chat_id and text:
                if text == "/start":
                    reply = "👋 Привет! Я твой ИИ-ассистент по питанию (Calories AI).\nЗаписывай еду текстом или голосом!"
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
