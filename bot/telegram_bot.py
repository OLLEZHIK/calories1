import os
import sys
import logging
from pathlib import Path
from typing import Dict, Any

# Ensure project root is in sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from agents.ingestion_agent import ingestion_agent
from agents.nutrition_agent import nutrition_agent
from agents.auditor_agent import auditor_agent
from agents.economy_agent import economy_agent
from agents.coach_agent import coach_agent
from agents.dashboard_agent import dashboard_agent
from agents.audio_agent import audio_agent
from database.db import save_meal, get_today_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CaloriesBot")

def process_user_meal_input(raw_text: str, input_type: str = "text") -> str:
    """
    Delegates user inputs to TeamLeadAgent for intent routing and specialized multi-agent execution.
    """
    from agents.teamlead_agent import teamlead_agent
    return teamlead_agent.route_input(raw_text, input_type=input_type)


# Telegram Bot Launcher using python-telegram-bot
def start_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set in .env. Please set TELEGRAM_BOT_TOKEN to launch.")
        return

    try:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

        from telegram import ReplyKeyboardMarkup

        main_keyboard = ReplyKeyboardMarkup(
            [
                ["🍲 Запись приема пищи", "👨‍💼 Технический таск"],
                ["📊 Итоги за сегодня", "💡 Советы ИИ-тренера"]
            ],
            resize_keyboard=True
        )

        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(
                "👋 **Привет! Я твой ИИ-ассистент по питанию Calories AI.**\n\n"
                "Выберите нужную команду кнопками ниже или надиктуйте сообщение:\n"
                "• 🍲 **Запись приема пищи** — чтобы записать еду\n"
                "• 👨‍💼 **Технический таск** — чтобы отправить задачу Тимлиду\n"
                "• 📊 **Итоги за сегодня** — посмотреть КБЖУ за день\n"
                "• 💡 **Советы ИИ-тренера** — узнать рекомендации",
                reply_markup=main_keyboard
            )

        async def summary_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            today = get_today_summary()
            res = (
                f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
                f"🔥 **Калории**: {int(round(today['total_calories']))} / {today['goals']['calories']} ккал\n"
                f"🥩 **Белки**: {int(round(today['total_protein']))}g / {today['goals']['protein_g']}g\n"
                f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {today['goals']['fat_g']}g\n"
                f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {today['goals']['carbs_g']}g"
                f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
            )
            await update.message.reply_markdown(res, reply_markup=main_keyboard)

        async def coach_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            analysis = coach_agent.analyze()
            recs = analysis.get("recommendations", [])
            lines = [f"💡 **[{r['severity'].upper()}]** {r['message']}" for r in recs]
            body = "\n\n".join(lines) if lines else "💡 Советы формируются на основе вашего ежедневного рациона."
            await update.message.reply_markdown(body + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)", reply_markup=main_keyboard)

        async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = update.message.text
            if text in ["🍲 Запись приема пищи", "/food"]:
                await update.message.reply_markdown("🍲 **Режим записи приема пищи**\n\nНапишите или надиктуйте голосом вашу еду (например: *'3 яйца, 80г макарон, 20г бекона'*).", reply_markup=main_keyboard)
            elif text in ["👨‍💼 Технический таск", "/task"]:
                await update.message.reply_markdown("👨‍💼 **Режим технической задачи Тимлиду**\n\nОпишите задачу или желаемую фичу (например: *'Добавь на дашборд показатель веса 74 кг и роста 175 см'*).", reply_markup=main_keyboard)
            elif text in ["📊 Итоги за сегодня", "/summary"]:
                await summary_command(update, context)
            elif text in ["💡 Советы ИИ-тренера", "/coach"]:
                await coach_command(update, context)
            else:
                response = process_user_meal_input(text, input_type="text")
                await update.message.reply_markdown(response, reply_markup=main_keyboard)

        async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text("🎤 Голосовое сообщение получено! Распознаем...")
            try:
                voice = update.message.voice
                if not voice:
                    await update.message.reply_text("⚠️ Ошибка: Голосовой файл не найден.")
                    return
                
                file = await context.bot.get_file(voice.file_id)
                voice_bytes = await file.download_as_bytearray()
                
                result = audio_agent.transcribe(bytes(voice_bytes))
                transcription = result.get("text", "")
                engine = result.get("engine", "")
                err = result.get("error", "")

                if transcription:
                    reply = f"🎤 **Распознано ({engine})**:\n*\"{transcription}\"*\n\n" + process_user_meal_input(transcription, input_type="voice")
                else:
                    reply = (
                        f"⚠️ **Ошибка расшифровки голоса**:\n`{err}`\n\n"
                        "💡 *Как настроить голосовой ввод:*\n"
                        "Вставьте свой API-ключ Yandex SpeechKit (`AQ...`), Groq (`gsk_...`), или Gemini (`AIza...`) в настройках приложения (`.env`).\n\n"
                        "Вы также можете прямо сейчас отправить еду текстом (например: `200г творога, 2 яйца`)."
                    )
                await update.message.reply_markdown(reply)
            except Exception as e:
                logger.error(f"Error handling voice message: {e}")
                await update.message.reply_text(f"⚠️ Ошибка при обработке аудио: {e}")


        async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
            caption = update.message.caption or "100г салат, 200г курица"
            response = process_user_meal_input(caption, input_type="photo")
            await update.message.reply_markdown(f"📷 **Фото блюда обработано!**\n\n{response}")

        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(CommandHandler("summary", summary_command))
        app.add_handler(CommandHandler("coach", coach_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
        app.add_handler(MessageHandler(filters.VOICE, handle_voice))
        app.add_handler(MessageHandler(filters.PHOTO, handle_photo))

        logger.info("Telegram Bot started listening...")
        app.run_polling()
    except Exception as e:
        logger.error(f"Failed to start Telegram Bot: {e}")

if __name__ == "__main__":
    start_bot()
