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

    def _classify_intent_llm(self, text: str) -> str | None:
        """
        Uses Gemini 2.0 Flash to classify user intent.
        Returns one of: 'food' | 'task' | 'summary' | 'coach' | None (uncertain)
        Falls back to None if no Gemini key — keyword matching takes over.
        """
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if not gemini_key:
            return None
        try:
            from google import genai
            from google.genai import types
            client = genai.Client(api_key=gemini_key)
            model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
            prompt = f"""Classify this Russian message into exactly one category. Reply with ONLY the category word.

Categories:
- food: user is describing food they ate (e.g. яйца, макароны, съел, поел, на завтрак/обед/ужин)
- task: user asks a technical question, reports a bug, requests a feature, or asks "why/how" about the app
- summary: user wants to see today's calorie/nutrition summary
- coach: user wants diet advice or recommendations
- price: user is logging a product price (рублей, евро, стоит)

Message: "{text}"

Reply with ONLY one word: food, task, summary, coach, or price"""

            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=10)
            )
            intent = (resp.text or "").strip().lower().split()[0]
            if intent in ("food", "task", "summary", "coach", "price"):
                return intent
        except Exception as e:
            print(f"Intent classification error: {e}")
        return None

    def route_input(self, raw_text: str, input_type: str = "text") -> str:
        if not raw_text or not raw_text.strip():
            return "⚠️ Пустое сообщение. Напишите или надиктуйте еду (например: '200г творога, 2 яйца')."

        text_lower = raw_text.lower().strip()

        # Guard: reject UI button texts that must never reach the food pipeline
        NON_FOOD_UI_TEXTS = [
            "запись приема пищи", "технический таск",
            "итоги за сегодня", "советы ии-тренера"
        ]
        if any(text_lower == t for t in NON_FOOD_UI_TEXTS):
            return "👇 Нажмите одну из кнопок ниже чтобы начать."

        # ── LLM Intent Classification (Gemini) ──────────────────────────────
        # When GEMINI_API_KEY is set, Gemini classifies ANY natural language phrase.
        # This replaces brittle keyword matching for the majority of inputs.
        llm_intent = self._classify_intent_llm(raw_text)

        if llm_intent == "summary":
            today = get_today_summary()
            return (
                f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
                f"🔥 **Калории**: {int(round(today['total_calories']))} / {today['goals']['calories']} ккал\n"
                f"🥩 **Белки**: {int(round(today['total_protein']))}g / {today['goals']['protein_g']}g\n"
                f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {today['goals']['fat_g']}g\n"
                f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {today['goals']['carbs_g']}g"
                f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
            )

        if llm_intent == "coach":
            analysis = coach_agent.analyze()
            recs = analysis.get("recommendations", [])
            lines = [f"💡 **[{r['severity'].upper()}]** {r['message']}" for r in recs]
            body = "\n\n".join(lines) if lines else "💡 Советы формируются на основе вашего ежедневного рациона."
            return body + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"

        if llm_intent == "task":
            feature_res = self.process_feature_request(raw_text)
            return (
                f"👨‍💼 **Тимлид принял задачу!**\n\n{feature_res['summary']}\n\nСформированы подзадачи для агентов:\n"
                + "\n".join([f"• [{t['agent']}]: {t['task']}" for t in feature_res.get("tasks", [])])
                + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
            )

        if llm_intent == "price":
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
                    f"📈 **Экономика рациона**: Продуктов отслеживается: {econ_stats.get('total_tracked_products', 0)}."
                    f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
                )

        # If llm_intent == "food" OR no Gemini key — fall through to keyword + food pipeline below

        # ── Keyword fallback (no GEMINI_API_KEY) ────────────────────────────
        # 1. Check if user is logging a product price
        if llm_intent is None:
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
                    f"📈 **Экономика рациона**: Продуктов отслеживается: {econ_stats.get('total_tracked_products', 0)}."
                    f"\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
                )

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

            if any(w in text_lower for w in [
                "добавь фичу", "почему", "тренировка", "активные калории", "трекер", "дашборд",
                "мобильн", "оптимизир", "верстк", "дизайн", "интерфейс", "адаптив", "техническое задание",
                "тимлид", "транскриб", "отличать", "агент", "глюк", "исправь", "настрой",
                "не работает", "не заполняется", "задачу", "задача", "отправь",
                "рост", "роста", "вес", "веса", "килограмм", "килограмма"
            ]):
                feature_res = self.process_feature_request(raw_text)
                return (
                    f"👨‍💼 **Тимлид принял задачу!**\n\n{feature_res['summary']}\n\nСформированы подзадачи для агентов:\n"
                    + "\n".join([f"• [{t['agent']}]: {t['task']}" for t in feature_res.get("tasks", [])])
                    + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
                )

        # 4. Multi-Meal Processing Pipeline (Supports multiple meals dictated in one audio message)
        llm_meals = ingestion_agent._parse_llm(raw_text)
        
        # If LLM didn't return multi-meal array, build single meal structure only for explicit food items
        if not llm_meals:
            parsed_items = ingestion_agent.parse(raw_text)
            if not parsed_items:
                return (
                    "🤔 **Не удалось автоматически определить тип сообщения.**\n\n"
                    "Вы хотите записать еду или отправить задачу ИИ-ассистенту?\n\n"
                    "• 🍲 **Записать еду**: '3 яйца, 80г макарон, 20г бекона'\n"
                    "• 👨‍💼 **Техническая задача**: 'Добавь на дашборд показатель веса 74 кг'\n\n"
                    "🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
                )
            meal_type = detect_meal_type(raw_text)
            llm_meals = [{"meal_type": meal_type, "items": parsed_items}]

        saved_meal_responses = []

        for m_data in llm_meals:
            m_type = m_data.get("meal_type") or detect_meal_type(raw_text)
            raw_items = m_data.get("items", [])
            if not raw_items:
                continue

            # Step 2: Nutrition Agent (Calculate macros P/F/C/Calories)
            calculated_items = nutrition_agent.calculate(raw_items)

            # Step 3: Auditor Agent (Audit macro math & sanity checks)
            audited_items = auditor_agent.audit(calculated_items)

            # Step 4: Database Agent (Persist meal entry with meal_type)
            meal_id = save_meal(raw_input=raw_text, input_type=input_type, items=audited_items, meal_type=m_type)

            m_icon = "🍳" if m_type == "Завтрак" else ("🍲" if m_type == "Обед" else ("🌙" if m_type == "Ужин" else "🍎"))
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

            saved_meal_responses.append(
                f"{m_icon} **{m_type.upper()} записан!** (Запись #{meal_id})\n"
                + "\n".join(item_lines) + "\n"
                + f"🔥 **Сумма**: {total_cal} ккал | Б: {total_p}g | Ж: {total_f}g | У: {total_c}g"
            )

        if not saved_meal_responses:
            return "⚠️ Не удалось записать продукты из вашего сообщения."

        # Step 5 & 6: Coach & Dashboard sync
        coach_agent.analyze()
        dashboard_agent.render()
        today = get_today_summary()

        response = (
            "\n\n".join(saved_meal_responses) + "\n\n"
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

