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
from agents.ingestion_agent import process_add_product, format_products_catalog
from bot.telegram_bot import process_task_input, process_user_meal_input, process_user_meal_input_with_details
from bot.meal_cleanup import (
    get_clear_records_view,
    handle_delete_meal_action,
    handle_delete_all_action,
    parse_and_execute_text_delete,
)
from database.db import get_bot_session_mode, get_today_summary, save_custom_product, set_bot_session_mode
from gemini_client import get_genai_client

MODE_FOOD = "food"
MODE_TASK = "task"
MODE_ADD_PRODUCT = "add_product"
MODE_CLEAR = "clear_records"
SESSION_MODES: Dict[str, str] = {}

MAIN_KEYBOARD = {
    "keyboard": [
        [{"text": "🍲 Запись приема пищи"}, {"text": "➕ Добавить продукт"}],
        [{"text": "📊 Итоги за сегодня"}, {"text": "💡 Советы ИИ-тренера"}],
        [{"text": "📋 Список продуктов"}, {"text": "🗑 Очистить записи"}],
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


def answer_callback_query(token: str, callback_query_id: str, text: Optional[str] = None) -> None:
    """Answer callback query from inline buttons."""
    url = f"https://api.telegram.org/bot{token}/answerCallbackQuery"
    payload = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=8):
            pass
    except Exception as exc:
        print(f"Telegram answerCallbackQuery error: {exc}")


def edit_telegram_message(token: str, chat_id: int, message_id: int, text: str, reply_markup: Optional[Dict[str, Any]] = None) -> None:
    """Edit existing Telegram message text and inline keyboard."""
    url = f"https://api.telegram.org/bot{token}/editMessageText"
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=10):
            pass
    except Exception as exc:
        print(f"Telegram editMessageText error: {exc}")


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
    cost_str = f"💰 **Потрачено на еду за день**: {today.get('total_cost_eur', 0):.2f} €\n" if today.get('total_cost_eur', 0) > 0 else ""
    return (
        f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
        f"🔥 **Калории**: {int(round(today['total_calories']))} / {goals['calories']} ккал\n"
        f"🥩 **Белки**: {int(round(today['total_protein']))}g / {goals['protein_g']}g\n"
        f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {goals['fat_g']}g\n"
        f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {goals['carbs_g']}g\n"
        f"{cost_str}\n"
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
            update_data = json.loads(post_data)

            # 1. Handle Inline Keyboard Callback Queries (e.g. Delete record)
            if "callback_query" in update_data:
                cb = update_data["callback_query"]
                cb_id = cb.get("id")
                cb_data = cb.get("data", "")
                cb_msg = cb.get("message", {})
                chat_id = cb_msg.get("chat", {}).get("id")
                msg_id = cb_msg.get("message_id")
                if chat_id and is_authorized(chat_id):
                    if cb_data.startswith("del_meal_"):
                        meal_id = int(cb_data.replace("del_meal_", ""))
                        answer_callback_query(token, cb_id, "Запись стёрта!")
                        resp_text, new_markup = handle_delete_meal_action(meal_id)
                        if msg_id:
                            edit_telegram_message(token, chat_id, msg_id, resp_text, new_markup)
                        else:
                            send_telegram_message(token, chat_id, resp_text, new_markup)
                    elif cb_data == "del_meals_all":
                        set_mode(chat_id, None)
                        answer_callback_query(token, cb_id, "Все записи стёрты!")
                        resp_text = handle_delete_all_action(5)
                        if msg_id:
                            edit_telegram_message(token, chat_id, msg_id, resp_text, None)
                        else:
                            send_telegram_message(token, chat_id, resp_text)
                    elif cb_data == "del_meals_cancel":
                        set_mode(chat_id, None)
                        answer_callback_query(token, cb_id, "Отменено")
                        if msg_id:
                            edit_telegram_message(token, chat_id, msg_id, "❌ Операция очистки записей отменена.", None)
                        else:
                            send_telegram_message(token, chat_id, "❌ Операция очистки записей отменена.")
                    elif cb_data == "skip_pending_product":
                        set_mode(chat_id, None)
                        answer_callback_query(token, cb_id, "Пропущено")
                        if msg_id:
                            edit_telegram_message(token, chat_id, msg_id, "❌ Добавление цены продукта пропущено.", None)
                        else:
                            send_telegram_message(token, chat_id, "❌ Добавление цены продукта пропущено.")
                self._respond_ok()
                return

            message = update_data.get("message", {})
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
                    if mode == MODE_ADD_PRODUCT:
                        set_mode(chat_id, None)
                        reply = f"🎤 **Распознано**:\n*\"{transcription}\"*\n\n" + process_add_product(raw_text=transcription)
                        send_telegram_message(token, chat_id, reply)
                    elif mode == MODE_TASK:
                        set_mode(chat_id, None)
                        reply = f"🎤 **Распознано**:\n*\"{transcription}\"*\n\n" + process_task_input(transcription)
                        send_telegram_message(token, chat_id, reply)
                    else:
                        set_mode(chat_id, None)
                        res_det = process_user_meal_input_with_details(transcription, input_type="voice")
                        reply = f"🎤 **Распознано**:\n*\"{transcription}\"*\n\n" + res_det["response"]
                        send_telegram_message(token, chat_id, reply)
                        pending = res_det.get("pending_product")
                        if pending:
                            set_mode(chat_id, f"await_product_price:{json.dumps(pending, ensure_ascii=False)}")
                            from agents.ingestion_agent import format_new_product_prompt
                            p_text, p_markup = format_new_product_prompt(pending)
                            send_telegram_message(token, chat_id, p_text, reply_markup=p_markup)
                else:
                    set_mode(chat_id, None)
                    send_telegram_message(token, chat_id, "⚠️ Не удалось распознать голосовое сообщение. Отправьте еду текстом.")
            elif message.get("photo"):
                image_bytes = get_telegram_file_bytes(token, message["photo"][-1].get("file_id", ""))
                if not image_bytes:
                    send_telegram_message(token, chat_id, "⚠️ Не удалось скачать фотографию. Попробуйте ещё раз.")
                elif mode == MODE_ADD_PRODUCT:
                    set_mode(chat_id, None)
                    reply = process_add_product(raw_text=message.get("caption", ""), image_bytes=image_bytes)
                    send_telegram_message(token, chat_id, reply)
                else:
                    set_mode(chat_id, None)
                    res_det = process_user_meal_input_with_details(message.get("caption", ""), input_type="photo", image_bytes=image_bytes)
                    send_telegram_message(token, chat_id, f"📷 **Фото блюда обработано!**\n\n{res_det['response']}")
                    pending = res_det.get("pending_product")
                    if pending:
                        set_mode(chat_id, f"await_product_price:{json.dumps(pending, ensure_ascii=False)}")
                        from agents.ingestion_agent import format_new_product_prompt
                        p_text, p_markup = format_new_product_prompt(pending)
                        send_telegram_message(token, chat_id, p_text, reply_markup=p_markup)
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
        token = os.getenv("TELEGRAM_BOT_TOKEN", "")
        if text in ("/start", "меню", "главное меню"):
            set_mode(chat_id, None)
            return "👋 **Calories AI**\n\nВыберите действие кнопками ниже."
        if text in ("🍲 Запись приема пищи", "/food"):
            set_mode(chat_id, MODE_FOOD)
            return "🍲 Напишите или надиктуйте еду, например: *3 яйца, 80г макарон*."
        if text in ("➕ Добавить продукт", "/add_product"):
            set_mode(chat_id, MODE_ADD_PRODUCT)
            return (
                "➕ **Режим добавления продукта**\n\n"
                "Сфотографируйте или опишите продукт:\n"
                "• 📷 **Фото**: фото упаковки с таблицей КБЖУ, ценником или блюда.\n"
                "• ✍️ **Текст**: напишите название, вес и цену (например: *«Торт медовик 800г, 7.5 евро»*).\n"
                "• 🎤 **Голос**: надиктуйте описание продукта голосом.\n\n"
                "ИИ распознает данные или автоматически рассчитает пищевую ценность!"
            )
        if text in ("👨‍💼 Технический таск", "/task"):
            set_mode(chat_id, MODE_TASK)
            return "👨‍💼 Опишите задачу или желаемую функцию — я передам её Тимлиду."
        if text in ("🗑 Очистить записи", "/clear", "/delete", "очистить записи", "стереть записи"):
            set_mode(chat_id, MODE_CLEAR)
            view_text, markup, _ = get_clear_records_view()
            send_telegram_message(token, chat_id, view_text, reply_markup=markup or MAIN_KEYBOARD)
            return ""
        import re
        m_del = re.match(r'^(?:удали|удалить|стереть|сотри)\s+продукт\s+(.+)$', text.strip().lower())
        if m_del:
            from database.db import delete_product
            p_to_del = m_del.group(1).strip()
            delete_product(p_to_del)
            return f"✅ Продукт **{p_to_del.capitalize()}** успешно удален из базы и таблицы!\n\n{format_products_catalog()}"
        if text in ("🛡 Аудит базы", "🛡 Аудит каталога", "/audit", "проверь дубликаты", "проверь таблицу", "почисти повторы", "аудит"):
            set_mode(chat_id, None)
            from agents.economy_agent import economy_agent
            return economy_agent.run_audit_command()
        if text in ("📋 Список продуктов", "/products", "продукты", "список продуктов"):
            set_mode(chat_id, None)
            return format_products_catalog()
        if text in ("📊 Итоги за сегодня", "/summary"):
            set_mode(chat_id, None)
            return format_summary()
        if text in ("💡 Советы ИИ-тренера", "/coach"):
            set_mode(chat_id, None)
            return format_coach()
        if mode and mode.startswith("await_product_price:"):
            from agents.ingestion_agent import parse_entered_price
            from database.db import save_custom_product, save_product_price

            if text.lower() in ["отмена", "пропустить", "skip", "нет", "/cancel"]:
                set_mode(chat_id, None)
                return "❌ Добавление цены продукта отменено."

            price = parse_entered_price(text)
            if price is not None:
                try:
                    prod_data = json.loads(mode[len("await_product_price:"):])
                    p_name = prod_data["product_name"]
                    cal = float(prod_data.get("calories_100g") or 0.0)
                    p = float(prod_data.get("protein_100g") or 0.0)
                    f = float(prod_data.get("fat_100g") or 0.0)
                    c = float(prod_data.get("carbs_100g") or 0.0)
                    w = float(prod_data.get("weight_g") or 100.0)
                    cat = prod_data.get("category") or "general"
                    score = int(prod_data.get("coach_score") or 6)
                    verdict = prod_data.get("coach_verdict") or ""

                    save_custom_product(p_name, cal, p, f, c)
                    save_product_price(p_name, price, w, cat, p, f, c, cal, score, verdict, user_id=1)
                    set_mode(chat_id, None)

                    p_100 = round((price / w) * 100, 2) if w > 0 else price
                    return (
                        f"✅ **Продукт «{p_name.capitalize()}» успешно добавлен в базу и каталог!**\n\n"
                        f"💰 Цена: **{price:.2f} €** ({p_100:.2f} € за 100г)\n"
                        f"📊 КБЖУ (на 100г): {int(round(cal))} ккал | Б:{p}г | Ж:{f}г | У:{c}г\n\n"
                        f"🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
                    )
                except Exception as e:
                    print(f"Error saving pending product price in webhook: {e}")

            if not text.startswith("/") and text not in [
                "🍲 Запись приема пищи", "➕ Добавить продукт", "📊 Итоги за сегодня",
                "💡 Советы ИИ-тренера", "📋 Список продуктов", "🗑 Очистить записи", "👨‍💼 Технический таск"
            ]:
                prompt_markup = {
                    "inline_keyboard": [
                        [{"text": "❌ Пропустить добавление цены", "callback_data": "skip_pending_product"}]
                    ]
                }
                send_telegram_message(
                    token, chat_id,
                    "⚠️ **Пожалуйста, введите цену числом** (например: *«2.50»* или *«2.5 евро»*) или нажмите кнопку «Пропустить».",
                    reply_markup=prompt_markup
                )
                return ""
            else:
                set_mode(chat_id, None)

        if mode == MODE_CLEAR:
            del_res = parse_and_execute_text_delete(text)
            if del_res:
                resp_text, new_markup = del_res
                if "отменен" in resp_text.lower() or "все" in text.lower():
                    set_mode(chat_id, None)
                send_telegram_message(token, chat_id, resp_text, reply_markup=new_markup or MAIN_KEYBOARD)
                return ""
            set_mode(chat_id, None)
        if mode == MODE_ADD_PRODUCT:
            set_mode(chat_id, None)
            return process_add_product(raw_text=text)
        if mode == MODE_TASK:
            set_mode(chat_id, None)
            return process_task_input(text)

        set_mode(chat_id, None)
        res_det = process_user_meal_input_with_details(text, input_type="webhook")
        reply = res_det["response"]
        pending = res_det.get("pending_product")
        if pending:
            set_mode(chat_id, f"await_product_price:{json.dumps(pending, ensure_ascii=False)}")
            from agents.ingestion_agent import format_new_product_prompt
            p_text, p_markup = format_new_product_prompt(pending)
            send_telegram_message(token, chat_id, reply)
            send_telegram_message(token, chat_id, p_text, reply_markup=p_markup)
            return ""

        return reply

    def _respond_ok(self) -> None:
        self.send_response(200)
        self.send_header("Content-type", "application/json")
        self.end_headers()
        self.wfile.write(b'{"status":"ok"}')
