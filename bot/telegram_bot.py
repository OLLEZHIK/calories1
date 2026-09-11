import os
import logging
from typing import Dict, Any

from agents.ingestion_agent import ingestion_agent
from agents.nutrition_agent import nutrition_agent
from agents.auditor_agent import auditor_agent
from agents.economy_agent import economy_agent
from agents.coach_agent import coach_agent
from agents.dashboard_agent import dashboard_agent
from database.db import save_meal, get_today_summary

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("CaloriesBot")

def process_user_meal_input(raw_text: str, input_type: str = "text") -> str:
    """
    Executes the multi-agent pipeline:
    Raw Input -> Ingestion -> Nutrition -> Audit -> Database -> Coach -> Dashboard
    """
    # 1. Ingestion Agent: Parse input into raw item dictionary
    parsed_items = ingestion_agent.parse(raw_text)
    if not parsed_items:
        return "⚠️ Не удалось распознать продукты в вашем сообщении. Попробуйте написать в формате: '5 яиц, 20г масла, 200г творога'."

    # 2. Nutrition Agent: Calculate macros (P/F/C/Calories)
    calculated_items = nutrition_agent.calculate(parsed_items)

    # 3. Auditor Agent: Verify macro consistency
    audited_items = auditor_agent.audit(calculated_items)

    # 4. Save to Database
    meal_id = save_meal(raw_input=raw_text, input_type=input_type, items=audited_items)

    # 5. Run Coach Agent to evaluate patterns & recommendations
    coach_result = coach_agent.analyze()

    # 6. Dashboard Agent: Regenerate HTML Dashboard
    dashboard_path = dashboard_agent.render()

    # Build response text for Telegram user
    total_cal = sum(i["calories"] for i in audited_items)
    total_p = sum(i["protein_g"] for i in audited_items)
    total_f = sum(i["fat_g"] for i in audited_items)
    total_c = sum(i["carbs_g"] for i in audited_items)

    item_lines = []
    for item in audited_items:
        item_lines.append(f"• {item['product_name']} ({round(item['quantity_g'])}g): {round(item['calories'])} ккал | Б:{item['protein_g']}g | Ж:{item['fat_g']}g | У:{item['carbs_g']}g")

    today = get_today_summary()

    response = (
        f"✅ **Прием пищи записан!** (Meal #{meal_id})\n\n"
        + "\n".join(item_lines) + "\n\n"
        + f"🔥 **Сумма за прием**: {round(total_cal)} ккал | Б: {round(total_p,1)}g | Ж: {round(total_f,1)}g | У: {round(total_c,1)}g\n\n"
        + f"📊 **Всего за день**: {today['total_calories']}/{today['goals']['calories']} ккал "
        + f"(Б: {today['total_protein']}g / Ж: {today['total_fat']}g / У: {today['total_carbs']}g)"
    )

    return response

# Telegram Bot Launcher using python-telegram-bot
def start_bot():
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.warning("TELEGRAM_BOT_TOKEN is not set. Bot running in dry-run mode.")
        return

    try:
        from telegram import Update
        from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes

        async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
            await update.message.reply_text(
                "👋 Привет! Я твой ИИ-ассистент по питанию (Calories AI).\n\n"
                "Отправляй мне:\n"
                "🎤 Голосовые сообщения с описанием еды\n"
                "💬 Текстовые сообщения ('5 яиц, 20г масла')\n"
                "📷 Фотографии блюд\n"
                "💰 Цены продуктов: '/price творог 150р 200г'\n\n"
                "Команды:\n"
                "/summary — итоги дня\n"
                "/coach — советы от ИИ-тренера"
            )

        async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
            text = update.message.text
            response = process_user_meal_input(text, input_type="text")
            await update.message.reply_markdown(response)

        app = ApplicationBuilder().token(token).build()
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

        logger.info("Telegram Bot started listening...")
        app.run_polling()
    except Exception as e:
        logger.error(f"Failed to start Telegram Bot: {e}")

if __name__ == "__main__":
    start_bot()
