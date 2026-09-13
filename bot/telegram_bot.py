import os
import sys
import logging
from pathlib import Path

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.economy_agent import economy_agent
from agents.coach_agent import coach_agent
from agents.audio_agent import audio_agent
from agents.ingestion_agent import process_add_product, format_products_catalog
from database.db import save_meal, get_today_summary

from bot.meal_cleanup import (
    get_clear_records_view,
    handle_delete_meal_action,
    handle_delete_all_action,
    parse_and_execute_text_delete,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CaloriesBot")


def process_user_meal_input(raw_text: str, input_type: str = "text", image_bytes: bytes = None) -> str:
    """Routes input through TeamLeadAgent (auto intent detection)."""
    from agents.teamlead_agent import teamlead_agent
    return teamlead_agent.route_input(raw_text, input_type=input_type, image_bytes=image_bytes)


def process_task_input(raw_text: str) -> str:
    """Routes input DIRECTLY to TeamLead as a feature/task — no intent detection."""
    from agents.teamlead_agent import teamlead_agent
    feature_res = teamlead_agent.process_feature_request(raw_text)
    return (
        f"👨\u200d💼 **Тимлид принял задачу!**\n\n{feature_res['summary']}\n\n"
        "Сформированы подзадачи для агентов:\n"
        + "\n".join([f"• [{t['agent']}]: {t['task']}" for t in feature_res.get("tasks", [])])
        + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
    )


# ── Telegram Bot ─────────────────────────────────────────────────────────────
def start_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN not set in .env")
        return

    try:
        from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
        from telegram.ext import (
            ApplicationBuilder, CommandHandler, MessageHandler, CallbackQueryHandler,
            filters, ContextTypes
        )

        def to_inline_markup(markup_dict):
            if not markup_dict or "inline_keyboard" not in markup_dict:
                return None
            return InlineKeyboardMarkup([
                [InlineKeyboardButton(btn["text"], callback_data=btn["callback_data"]) for btn in row]
                for row in markup_dict["inline_keyboard"]
            ])

        main_keyboard = ReplyKeyboardMarkup(
            [
                ["🍲 Запись приема пищи", "➕ Добавить продукт"],
                ["📊 Итоги за сегодня",  "💡 Советы ИИ-тренера"],
                ["📋 Список продуктов", "🗑 Очистить записи"],
                ["👨‍💼 Технический таск"]
            ],
            resize_keyboard=True
        )

        # ── Mode keys stored in context.user_data ────────────────────────
        MODE_FOOD = "food"
        MODE_TASK = "task"
        MODE_ADD_PRODUCT = "add_product"
        MODE_CLEAR = "clear_records"

        def get_mode(ctx):
            return ctx.user_data.get("mode")

        def set_mode(ctx, mode):
            ctx.user_data["mode"] = mode

        # ── /start ────────────────────────────────────────────────────────
        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            set_mode(context, None)
            await update.message.reply_markdown(
                "👋 **Привет! Я твой ИИ-ассистент по питанию Calories AI.**\n\n"
                "Выберите нужную команду кнопками ниже:\n"
                "• 🍲 **Запись приема пищи** — записать еду\n"
                "• ➕ **Добавить продукт** — добавить продукт в личную базу по фото\n"
                "• 👨‍💼 **Технический таск** — задача Тимлиду\n"
                "• 📊 **Итоги за сегодня** — КБЖУ за день\n"
                "• 💡 **Советы ИИ-тренера** — рекомендации ИИ",
                reply_markup=main_keyboard
            )

        # ── /summary ──────────────────────────────────────────────────────
        async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            set_mode(context, None)
            today = get_today_summary()
            await update.message.reply_markdown(
                f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
                f"🔥 **Калории**: {int(round(today['total_calories']))} / {today['goals']['calories']} ккал\n"
                f"🥩 **Белки**: {int(round(today['total_protein']))}g / {today['goals']['protein_g']}g\n"
                f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {today['goals']['fat_g']}g\n"
                f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {today['goals']['carbs_g']}g"
                f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)",
                reply_markup=main_keyboard
            )

        # ── /coach ────────────────────────────────────────────────────────
        async def coach_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            set_mode(context, None)
            analysis = coach_agent.analyze()
            recs = analysis.get("recommendations", [])
            lines = [f"💡 **[{r['severity'].upper()}]** {r['message']}" for r in recs]
            body = "\n\n".join(lines) if lines else "💡 Советы формируются на основе вашего рациона."
            await update.message.reply_markdown(
                body + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)",
                reply_markup=main_keyboard
            )

        # ── /products ─────────────────────────────────────────────────────
        async def products_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            set_mode(context, None)
            await update.message.reply_markdown(format_products_catalog(), reply_markup=main_keyboard)

        # ── /clear ────────────────────────────────────────────────────────
        async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            set_mode(context, MODE_CLEAR)
            text, markup, _ = get_clear_records_view()
            inline_kb = to_inline_markup(markup)
            await update.message.reply_markdown(text, reply_markup=inline_kb or main_keyboard)

        # ── Callback query handler ────────────────────────────────────────
        async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
            query = update.callback_query
            data = query.data or ""
            if data.startswith("del_meal_"):
                meal_id = int(data.replace("del_meal_", ""))
                msg, markup = handle_delete_meal_action(meal_id)
                await query.answer("Запись стёрта!")
                await query.edit_message_text(msg, parse_mode="Markdown", reply_markup=to_inline_markup(markup))
            elif data == "del_meals_all":
                set_mode(context, None)
                msg = handle_delete_all_action(5)
                await query.answer("Все записи стёрты!")
                await query.edit_message_text(msg, parse_mode="Markdown")
            elif data == "del_meals_cancel":
                set_mode(context, None)
                await query.answer("Отменено")
                await query.edit_message_text("❌ Операция очистки записей отменена.", parse_mode="Markdown")

        # ── Text handler ──────────────────────────────────────────────────
        async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = (update.message.text or "").strip()
            mode = get_mode(context)

            # Button: enter food mode
            if text in ("🍲 Запись приема пищи", "/food"):
                set_mode(context, MODE_FOOD)
                await update.message.reply_markdown(
                    "🍲 **Режим записи приема пищи**\n\n"
                    "Напишите или надиктуйте голосом вашу еду\n"
                    "_(например: '3 яйца, 80г макарон, 20г бекона')_",
                    reply_markup=main_keyboard
                )
                return

            # Button: enter task mode
            if text in ("👨\u200d💼 Технический таск", "/task"):
                set_mode(context, MODE_TASK)
                await update.message.reply_markdown(
                    "👨\u200d💼 **Режим технической задачи**\n\n"
                    "Опишите задачу, вопрос или желаемую фичу голосом или текстом.\n"
                    "Всё что вы скажете/напишете — уйдёт напрямую Тимлиду.",
                    reply_markup=main_keyboard
                )
                return

            # Button: enter add product mode
            if text in ("➕ Добавить продукт", "/add_product"):
                set_mode(context, MODE_ADD_PRODUCT)
                await update.message.reply_markdown(
                    "➕ **Режим добавления продукта**\n\n"
                    "Сфотографируйте или опишите продукт:\n"
                    "• 📷 **Фото**: фото упаковки с таблицей КБЖУ, ценником или блюда.\n"
                    "• ✍️ **Текст**: напишите название, вес и цену (например: *«Торт медовик 800г, 7.5 евро»*).\n"
                    "• 🎤 **Голос**: надиктуйте описание продукта голосом.\n\n"
                    "ИИ распознает данные или автоматически рассчитает пищевую ценность!",
                    reply_markup=main_keyboard
                )
                return

            if text in ("🗑 Очистить записи", "/clear", "/delete", "очистить записи", "стереть записи"):
                await clear_command(update, context)
                return

            if text in ("📋 Список продуктов", "/products", "продукты", "список продуктов"):
                await products_command(update, context)
                return

            if text in ("📊 Итоги за сегодня", "/summary"):
                await summary_command(update, context)
                return

            if text in ("💡 Советы ИИ-тренера", "/coach"):
                await coach_command(update, context)
                return

            # Route based on active session mode
            if mode == MODE_CLEAR:
                del_result = parse_and_execute_text_delete(text)
                if del_result:
                    resp_text, new_markup = del_result
                    if "отменен" in resp_text.lower() or "все" in text.lower():
                        set_mode(context, None)
                    await update.message.reply_markdown(resp_text, reply_markup=to_inline_markup(new_markup) or main_keyboard)
                    return
                set_mode(context, None)

            if mode == MODE_ADD_PRODUCT:
                set_mode(context, None)
                response = process_add_product(raw_text=text)
            elif mode == MODE_TASK:
                set_mode(context, None)
                response = process_task_input(text)
            elif mode == MODE_FOOD:
                set_mode(context, None)
                response = process_user_meal_input(text, input_type="text")
            else:
                # No mode — auto detect intent
                response = process_user_meal_input(text, input_type="text")

            await update.message.reply_markdown(response, reply_markup=main_keyboard)

        # ── Voice handler ─────────────────────────────────────────────────
        async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
            mode = get_mode(context)
            await update.message.reply_text("🎤 Голосовое сообщение получено! Распознаем...")
            try:
                voice = update.message.voice
                if not voice:
                    await update.message.reply_text("⚠️ Голосовой файл не найден.")
                    return

                file = await context.bot.get_file(voice.file_id)
                voice_bytes = await file.download_as_bytearray()

                result = audio_agent.transcribe(bytes(voice_bytes))
                transcription = result.get("text", "")
                engine = result.get("engine", "")
                err = result.get("error", "")

                if transcription:
                    header = f"🎤 **Распознано ({engine})**:\n*\"{transcription}\"*\n\n"
                    if mode == MODE_ADD_PRODUCT:
                        set_mode(context, None)
                        reply = header + process_add_product(raw_text=transcription)
                    elif mode == MODE_TASK:
                        # Voice after "Технический таск" → direct to TeamLead
                        set_mode(context, None)
                        reply = header + process_task_input(transcription)
                    elif mode == MODE_FOOD:
                        set_mode(context, None)
                        reply = header + process_user_meal_input(transcription, input_type="voice")
                    else:
                        # Auto detect
                        reply = header + process_user_meal_input(transcription, input_type="voice")
                else:
                    set_mode(context, None)
                    reply = (
                        f"⚠️ **Ошибка расшифровки голоса**:\n`{err}`\n\n"
                        "Попробуйте отправить текстом или проверьте GROQ_API_KEY в `.env`."
                    )

                await update.message.reply_markdown(reply, reply_markup=main_keyboard)
            except Exception as e:
                logger.error(f"Voice error: {e}")
                await update.message.reply_text(f"⚠️ Ошибка при обработке аудио: {e}")

        # ── Photo handler ─────────────────────────────────────────────────
        async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            mode = get_mode(context)
            await update.message.reply_text("📷 Фото получено! ИИ обрабатывает...")
            try:
                photo_file = await update.message.photo[-1].get_file()
                image_bytes = bytes(await photo_file.download_as_bytearray())
                caption = update.message.caption or ""

                if mode == MODE_ADD_PRODUCT:
                    set_mode(context, None)
                    response = process_add_product(raw_text=caption, image_bytes=image_bytes)
                    await update.message.reply_markdown(response, reply_markup=main_keyboard)
                else:
                    response = process_user_meal_input(caption, input_type="photo", image_bytes=image_bytes)
                    await update.message.reply_markdown(f"📷 **Фото блюда обработано!**\n\n{response}", reply_markup=main_keyboard)
            except Exception as e:
                logger.error(f"Photo error: {e}")
                await update.message.reply_text(f"⚠️ Ошибка при обработке фото: {e}")

        # ── App setup ─────────────────────────────────────────────────────
        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("summary", summary_command))
        app.add_handler(CommandHandler("coach", coach_command))
        app.add_handler(CommandHandler("products", products_command))
        app.add_handler(CommandHandler("clear", clear_command))
        app.add_handler(CommandHandler("delete", clear_command))
        app.add_handler(CallbackQueryHandler(handle_callback_query))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

        logger.info("Telegram Bot started listening...")
        app.run_polling()
    except Exception as e:
        logger.error(f"Failed to start Telegram Bot: {e}")


if __name__ == "__main__":
    start_bot()
