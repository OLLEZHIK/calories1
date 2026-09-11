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

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "🍲 Запись приема пищи"}, {"text": "👨‍💼 Технический таск"}],
        [{"text": "📊 Итоги за сегодня"}, {"text": "💡 Советы ИИ-тренера"}]
    ],
    "resize_keyboard": True
}

def send_telegram_message(token: str, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None):
    """Sends reply back to Telegram user via Telegram Bot API with interactive buttons."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "reply_markup": reply_markup or MAIN_KEYBOARD
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
                    if text in ["/start", "меню", "главное меню"]:
                        reply = (
                            "👋 **Привет! Я твой ИИ-ассистент по питанию Calories AI.**\n\n"
                            "Выберите нужную команду кнопками ниже или надиктуйте сообщение:\n"
                            "• 🍲 **Запись приема пищи** — чтобы записать еду\n"
                            "• 👨‍💼 **Технический таск** — чтобы отправить задачу Тимлиду\n"
                            "• 📊 **Итоги за сегодня** — посмотреть КБЖУ за день\n"
                            "• 💡 **Советы ИИ-тренера** — узнать рекомендации"
                        )
                    elif text in ["🍲 Запись приема пищи", "/food"]:
                        reply = "🍲 **Режим записи приема пищи**\n\nНапишите или надиктуйте голосом вашу еду (например: *'3 яйца, 80г макарон, 20г бекона'*)."
                    elif text in ["👨‍💼 Технический таск", "/task"]:
                        reply = "👨‍💼 **Режим технической задачи Тимлиду**\n\nОпишите задачу или желаемую фичу (например: *'Добавь на дашборд показатель веса 74 кг и роста 175 см'*)."
                    elif text in ["📊 Итоги за сегодня", "/summary"]:
                        from database.db import get_today_summary
                        today = get_today_summary()
                        reply = (
                            f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
                            f"🔥 **Калории**: {int(round(today['total_calories']))} / {today['goals']['calories']} ккал\n"
                            f"🥩 **Белки**: {int(round(today['total_protein']))}g / {today['goals']['protein_g']}g\n"
                            f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {today['goals']['fat_g']}g\n"
                            f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {today['goals']['carbs_g']}g"
                            f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
                        )
                    elif text in ["💡 Советы ИИ-тренера", "/coach"]:
                        from agents.coach_agent import coach_agent
                        analysis = coach_agent.analyze()
                        recs = analysis.get("recommendations", [])
                        lines = [f"💡 **[{r['severity'].upper()}]** {r['message']}" for r in recs]
                        body = "\n\n".join(lines) if lines else "💡 Советы формируются на основе вашего ежедневного рациона."
                        reply = body + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
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

