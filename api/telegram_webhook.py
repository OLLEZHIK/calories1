from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.audio_agent import audio_agent
from bot.telegram_bot import process_task_input, process_user_meal_input
from database.db import get_bot_session_mode, get_today_summary, save_custom_product, set_bot_session_mode
from gemini_client import get_genai_client

MODE_FOOD = "food"
MODE_TASK = "task"
MODE_ADD_PRODUCT = "add_product"
SESSION_MODES: Dict[str, str] = {}

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "🍲 Запись приема пищи"}, {"text": "➕ Добавить продукт"}],
        [{"text": "📊 Итоги за сегодня"}, {"text": "💡 Советы ИИ-тренера"}],
        [{"text": "👨‍💼 Технический таск"}],
    ],
    "resize_keyboard": True,
}


def send_telegram_message(token: str, chat_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
    """Send a Telegram reply and keep the shared keyboard visible."""
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown", "reply_markup": reply_markup or MAIN_KEYBOARD}
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=12):
            pass
    except Exception as exc:
        print(f"Telegram send error: {type(exc).__name__}: {exc}")


def get_telegram_file_bytes(token: str, file_id: str) -> bytes:
    """Download a Telegram file by id (voice or photo)."""
    try:
        get_file_url = f"https://api.telegram.org/bot{token}/getFile?file_id={file_id}"
        with urllib.request.urlopen(get_file_url, timeout=10) as response:
            file_path = json.loads(response.read().decode("utf-8")).get("result", {}).get("file_path")
        if not file_path:
            return b""
        download_url = f"https://api.telegram.org/file/bot{token}/{file_path}"
        with urllib.request.urlopen(download_url, timeout=15) as response:
            return response.read()
    except Exception as exc:
        print(f"Telegram file download error: {type(exc).__name__}: {exc}")
        return b""


def set_mode(chat_id: int, mode: Optional[str]) -> None:
    key = str(chat_id)
    if mode:
        SESSION_MODES[key] = mode
    else:
        SESSION_MODES.pop(key, None)
    set_bot_session_mode(chat_id, mode)


def get_mode(chat_id: int) -> Optional[str]:
    key = str(chat_id)
    if key not in SESSION_MODES:
        mode = get_bot_session_mode(chat_id)
        if mode:
            SESSION_MODES[key] = mode
    return SESSION_MODES.get(key)


def is_authorized(chat_id: int) -> bool:
    configured_id = os.getenv("TELEGRAM_USER_ID", "").strip()
    return not configured_id or str(chat_id) == configured_id


def is_verified_telegram_request(headers: Any) -> bool:
    secret = os.getenv("TELEGRAM_WEBHOOK_SECRET", "").strip()
    return not secret or headers.get("X-Telegram-Bot-Api-Secret-Token") == secret


def format_summary() -> str:
    today = get_today_summary()
    goals = today["goals"]
    return (
        f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
        f"🔥 **Калории**: {int(round(today['total_calories']))} / {goals['calories']} ккал\n"
        f"🥩 **Белки**: {int(round(today['total_protein']))}g / {goals['protein_g']}g\n"
        f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {goals['fat_g']}g\n"
        f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {goals['carbs_g']}g\n\n"
        "🌐 [Открыть дашборд](https://fatcaunter.vercel.app)"
    )


def format_coach() -> str:
    from agents.coach_agent import coach_agent

    recommendations = coach_agent.analyze().get("recommendations", [])
    body = "\n\n".join(f"💡 **[{item['severity'].upper()}]** {item['message']}" for item in recommendations)
    return (body or "💡 Советы формируются на основе вашего ежедневного рациона.") + "\n\n🌐 [Открыть дашборд](https://fatcaunter.vercel.app)"


def save_product_from_photo(image_bytes: bytes) -> str:
    """Recognize package nutrition information and save it as a personal product."""
    client = get_genai_client()
    if not client:
        return "⚠️ **Gemini недоступен.** Проверьте настройки Vertex AI и попробуйте снова."
    from google.genai import types

    prompt = (
        "Извлеки название продукта и КБЖУ на 100 грамм с изображения. Верни только JSON: "
        "{\"product_name\": \"string\", \"calories_100g\": float, \"protein_100g\": float, "
        "\"fat_100g\": float, \"carbs_100g\": float}."
    )
    response = client.models.generate_content(
        model=os.getenv("GEMINI_MODEL", "gemini-3.6-flash"),
        contents=[types.Part.from_text(text=prompt), types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")],
        config=types.GenerateContentConfig(temperature=0.0),
    )
    raw = (response.text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    product = json.loads(raw)
    save_custom_product(product["product_name"], float(product["calories_100g"]), float(product["protein_100g"]), float(product["fat_100g"]), float(product["carbs_100g"]))
    return (
        "✅ **Продукт добавлен в базу!**\n\n"
        f"📦 Название: `{product['product_name']}`\n"
        f"🔥 Калории: {product['calories_100g']} ккал/100г\n"
        f"🥩 Белки: {product['protein_100g']} г/100г\n"
        f"🥑 Жиры: {product['fat_100g']} г/100г\n"
        f"🍚 Углеводы: {product['carbs_100g']} г/100г"
    )


class handler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        post_data = self.rfile.read(int(self.headers.get("Content-Length", 0))).decode("utf-8")
        try:
            if not is_verified_telegram_request(self.headers):
                self.send_response(403)
                self.end_headers()
                return
            message = json.loads(post_data).get("message", {})
            chat_id = message.get("chat", {}).get("id")
            if not chat_id or not is_authorized(chat_id):
                self._respond_ok()
                return
            mode = get_mode(chat_id)
            if message.get("voice"):
                voice_bytes = get_telegram_file_bytes(token, message["voice"].get("file_id", ""))
                result = audio_agent.transcribe(voice_bytes) if voice_bytes else {"text": ""}
                transcription = result.get("text", "")
                if transcription:
                    routed = process_task_input(transcription) if mode == MODE_TASK else process_user_meal_input(transcription, input_type="voice")
                    reply = f"🎤 **Распознано**:\n*\"{transcription}\"*\n\n{routed}"
                else:
                    reply = "⚠️ Не удалось распознать голосовое сообщение. Отправьте еду текстом."
                set_mode(chat_id, None)
            elif message.get("photo"):
                image_bytes = get_telegram_file_bytes(token, message["photo"][-1].get("file_id", ""))
                if not image_bytes:
                    reply = "⚠️ Не удалось скачать фотографию. Попробуйте ещё раз."
                elif mode == MODE_ADD_PRODUCT:
                    reply = save_product_from_photo(image_bytes)
                else:
                    reply = "📷 **Фото блюда обработано!**\n\n" + process_user_meal_input(message.get("caption", ""), input_type="photo", image_bytes=image_bytes)
                set_mode(chat_id, None)
            else:
                reply = self._handle_text(chat_id, (message.get("text") or "").strip(), mode)
            if reply:
                send_telegram_message(token, chat_id, reply)
        except Exception:
            print(f"Webhook exception:\n{traceback.format_exc()}")
            try:
                chat_id = json.loads(post_data).get("message", {}).get("chat", {}).get("id")
                if chat_id and is_authorized(chat_id):
                    send_telegram_message(token, chat_id, "⚠️ Внутренняя ошибка. Попробуйте ещё раз.")
            except Exception:
                pass
        self._respond_ok()

    def _handle_text(self, chat_id: int, text: str, mode: Optional[str]) -> str:
        if text in ("/start", "меню", "главное меню"):
            set_mode(chat_id, None)
            return "👋 **Calories AI**\n\nВыберите действие кнопками ниже."
        if text in ("🍲 Запись приема пищи", "/food"):
            set_mode(chat_id, MODE_FOOD)
            return "🍲 Напишите или надиктуйте еду, например: *3 яйца, 80г макарон*."
        if text in ("➕ Добавить продукт", "/add_product"):
            set_mode(chat_id, MODE_ADD_PRODUCT)
            return "➕ Отправьте фото упаковки с таблицей КБЖУ на 100 г."
        if text in ("👨‍💼 Технический таск", "/task"):
            set_mode(chat_id, MODE_TASK)
            return "👨‍💼 Опишите задачу или желаемую функцию — я передам её Тимлиду."
        if text in ("📊 Итоги за сегодня", "/summary"):
            set_mode(chat_id, None)
            return format_summary()
        if text in ("💡 Советы ИИ-тренера", "/coach"):
            set_mode(chat_id, None)
            return format_coach()
        if mode == MODE_ADD_PRODUCT:
            return "➕ Для добавления продукта отправьте именно фотографию упаковки."
        set_mode(chat_id, None)
        return process_task_input(text) if mode == MODE_TASK else process_user_meal_input(text, input_type="webhook")

    def _respond_ok(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
