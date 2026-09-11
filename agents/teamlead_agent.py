import re
import json
import os
from typing import Dict, Any, List
from database.db import get_today_summary, save_product_price, save_coach_recommendation
from agents.ingestion_agent import ingestion_agent
from agents.nutrition_agent import nutrition_agent
from agents.auditor_agent import auditor_agent
from agents.economy_agent import economy_agent
from agents.coach_agent import coach_agent
from agents.dashboard_agent import dashboard_agent
from database.db import save_meal

def detect_meal_type(raw_text: str) -> str:
    """
    Detects meal category (Завтрак, Обед, Ужин, Перекус) via explicit user keywords
    or by matching local timestamp of the message.
    """
    text_lower = raw_text.lower()

    if any(k in text_lower for k in ["завтрак", "на завтрак", "утром"]):
        return "Завтрак"
    if any(k in text_lower for k in ["обед", "на обед", "днем"]):
        return "Обед"
    if any(k in text_lower for k in ["ужин", "на ужин", "вечером"]):
        return "Ужин"
    if any(k in text_lower for k in ["перекус", "перекусил", "полдник", "снек", "перекусить"]):
        return "Перекус"

    # Time-based fallback
    from datetime import datetime
    now_hour = datetime.now().hour
    if 5 <= now_hour < 12:
        return "Завтрак"
    elif 12 <= now_hour < 17:
        return "Обед"
    elif 17 <= now_hour < 22:
        return "Ужин"
    else:
        return "Перекус"

class TeamLeadAgent:
    """
    Agent 7: Master Router & TeamLead Agent
    Orchestrates user inputs (voice transcripts / text / photos) across all 7 specialized agents:
    - Classifies intent (Meal Logging, Price Entry, Summary/Analytics Request, Feature Task).
    - Detects meal category (Завтрак, Обед, Ужин, Перекус).
    - Routes food text to IngestionAgent (LLM) -> NutritionAgent -> AuditorAgent -> DB.
    - Routes prices to EconomyAgent.
    - Routes feature requests to Coder/DashboardAgent & AuditorAgent.
    """
    def __init__(self):
        self.name = "TeamLeadAgent"

    def route_input(self, raw_text: str, input_type: str = "text") -> str:
        if not raw_text or not raw_text.strip():
            return "⚠️ Пустое сообщение. Напишите или надиктуйте еду (например: '200г творога, 2 яйца')."

        text_lower = raw_text.lower().strip()

        # 1. Check if user is logging a product price (e.g., 'творог 200г 120р' or '500г макарон стоят 1.5€')
        price_info = ingestion_agent.parse_price_entry(raw_text)
        if price_info:
            save_product_price(
                product_name=price_info["product_name"],
                price_rub=price_info["price"],
                weight_g=price_info["weight_g"]
            )
            econ_stats = economy_agent.analyze_economy()
            return (
                f"💰 **Цена продукта записана!**\n\n"
                f"🛒 **Продукт**: {price_info['product_name']}\n"
                f"💵 **Стоимость**: {price_info['price']} {price_info['currency']} за {int(round(price_info['weight_g']))}g\n"
                f"📊 **Цена за 100g**: {round(price_info['price_per_100g'], 2)} {price_info['currency']}\n\n"
                f"📈 **Экономика рациона**: Всего отслеживается продуктов: {econ_stats.get('total_tracked_products', 0)}."
                f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
            )

        # 2. Check if user is asking for Summary / Coach Advice
        if any(cmd in text_lower for cmd in ["/summary", "итоги", "сколько я съел", "калории за день", "норма"]):
            today = get_today_summary()
            return (
                f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
                f"🔥 **Калории**: {int(round(today['total_calories']))} / {today['goals']['calories']} ккал\n"
                f"🥩 **Белки**: {int(round(today['total_protein']))}g / {today['goals']['protein_g']}g\n"
                f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {today['goals']['fat_g']}g\n"
                f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {today['goals']['carbs_g']}g"
                f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
            )

        if any(cmd in text_lower for cmd in ["/coach", "совет", "тренер", "рекомендации"]):
            analysis = coach_agent.analyze()
            recs = analysis.get("recommendations", [])
            lines = [f"💡 **[{r['severity'].upper()}]** {r['message']}" for r in recs]
            body = "\n\n".join(lines) if lines else "💡 Советы формируются на основе вашего ежедневного рациона."
            return body + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"

        # 3. Check if user is requesting a system feature / task for TeamLead
        if any(w in text_lower for w in ["добавь фичу", "сожг", "тренировка", "активные калории", "трекер"]):
            feature_res = self.process_feature_request(raw_text)
            return (
                f"👨‍💼 **Тимлид принял задачу!**\n\n{feature_res['summary']}\n\nСформированы подзадачи для агентов:\n" 
                + "\n".join([f"• [{t['agent']}]: {t['task']}" for t in feature_res.get('tasks', [])])
                + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
            )

        # 4. Detect Meal Category (Breakfast, Lunch, Dinner, Snack)
        meal_type = detect_meal_type(raw_text)
        meal_icon = "🍳" if meal_type == "Завтрак" else ("🍲" if meal_type == "Обед" else ("🌙" if meal_type == "Ужин" else "🍎"))

        # Step 1: Ingestion Agent (LLM product & weight extraction)
        parsed_items = ingestion_agent.parse(raw_text)
        if not parsed_items:
            return "⚠️ Не удалось распознать продукты. Напишите или надиктуйте в формате: '200г творога, 2 яйца, стакан молока'."

        # Step 2: Nutrition Agent (Calculate macros P/F/C/Calories)
        calculated_items = nutrition_agent.calculate(parsed_items)

        # Step 3: Auditor Agent (Audit macro math & sanity checks)
        audited_items = auditor_agent.audit(calculated_items)

        # Step 4: Database Agent (Persist meal entry with meal_type)
        meal_id = save_meal(raw_input=raw_text, input_type=input_type, items=audited_items, meal_type=meal_type)

        # Step 5: Coach Agent (Evaluate nutritional balance)
        coach_agent.analyze()

        # Step 6: Dashboard Agent (Update HTML Web Dashboard)
        dashboard_agent.render()

        # Format Telegram Response with integer rounding
        total_cal = int(round(sum(i["calories"] for i in audited_items)))
        total_p = int(round(sum(i["protein_g"] for i in audited_items)))
        total_f = int(round(sum(i["fat_g"] for i in audited_items)))
        total_c = int(round(sum(i["carbs_g"] for i in audited_items)))

        item_lines = []
        for item in audited_items:
            p_val = int(round(item['protein_g']))
            f_val = int(round(item['fat_g']))
            c_val = int(round(item['carbs_g']))
            cal_val = int(round(item['calories']))
            g_val = int(round(item['quantity_g']))
            item_lines.append(f"• {item['product_name']} ({g_val}g): {cal_val} ккал | Б:{p_val}g | Ж:{f_val}g | У:{c_val}g")

        today = get_today_summary()

        response = (
            f"{meal_icon} **{meal_type.upper()} записан!** (Запись #{meal_id})\n\n"
            + "\n".join(item_lines) + "\n\n"
            + f"🔥 **Сумма за прием**: {total_cal} ккал | Б: {total_p}g | Ж: {total_f}g | У: {total_c}g\n\n"
            + f"📊 **Всего за день**: {int(round(today['total_calories']))}/{today['goals']['calories']} ккал "
            + f"(Б: {int(round(today['total_protein']))}g / Ж: {int(round(today['total_fat']))}g / У: {int(round(today['total_carbs']))}g)"
            + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
        )

        return response


    def process_feature_request(self, user_prompt: str) -> Dict[str, Any]:
        prompt_lower = user_prompt.lower()
        tasks_created = []

        if any(word in prompt_lower for word in ["потрачен", "сожжен", "тренировка", "активность", "активные"]):
            tasks_created = [
                {"agent": "NutritionAgent", "task": "Учет активных сожженных калорий и вычитание из чистого баланса дня."},
                {"agent": "AuditorAgent", "task": "Проверка уравнения энергии: Чистые ккал = Приход - Расход."},
                {"agent": "DashboardAgent", "task": "Добавление карточки сожженных калорий на веб-дашборд."}
            ]
        else:
            tasks_created = [
                {"agent": "DashboardAgent", "task": f"UI обновление: {user_prompt}"},
                {"agent": "AuditorAgent", "task": f"Проверка логики для: {user_prompt}"}
            ]

        save_coach_recommendation(
            topic="Запрос фичи от пользователя",
            recommendation=f"Тимлид сформировал {len(tasks_created)} подзадач для агентов системы.",
            severity="info"
        )

        return {
            "status": "success",
            "feature_name": "Custom Feature Request",
            "user_prompt": user_prompt,
            "tasks": tasks_created,
            "summary": f"Тимлид распределил задачи между агентами для интеграции: '{user_prompt}'"
        }

teamlead_agent = TeamLeadAgent()

