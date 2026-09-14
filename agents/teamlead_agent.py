import re
import json
import os
from typing import Dict, Any, List, Optional

try:
    import config  # noqa: F401 - ensures .env is loaded
except ImportError:
    pass
from database.db import (
    get_today_summary, save_product_price, save_coach_recommendation, save_meal,
    get_product_price_map, find_item_price_per_100g
)
from agents.ingestion_agent import ingestion_agent, process_add_product
from agents.nutrition_agent import nutrition_agent
from agents.auditor_agent import auditor_agent
from agents.economy_agent import economy_agent
from agents.coach_agent import coach_agent
from agents.dashboard_agent import dashboard_agent

def detect_meal_type(raw_text: str) -> str:
    """
    Detects meal category (Завтрак, Обед, Ужин, Перекус) via explicit user keywords
    or by matching local timestamp of the message.
    """
    text_lower = raw_text.lower()

    if any(k in text_lower for k in ["завтрак", "на завтрак", "к завтраку", "позавтракал", "утром"]):
        return "Завтрак"
    if any(k in text_lower for k in ["обед", "на обед", "к обеду", "в обед", "пообедал", "днем"]):
        return "Обед"
    if any(k in text_lower for k in ["ужин", "на ужин", "к ужину", "поужинал", "вечером"]):
        return "Ужин"
    if any(k in text_lower for k in ["перекус", "перекусил", "полдник", "снек", "перекусить", "к перекусу"]):
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

def handle_weight_or_goal_update(text_lower: str) -> Optional[str]:
    """
    Detects user intent to update weight or goal mode, recalculates all nutrition targets,
    and returns an informative response with exact energy checks.
    """
    import re
    from database.db import save_user_weight_and_goals, get_user_goals

    # Check mode change
    target_mode = None
    if any(k in text_lower for k in ["набор", "качаться", "набирать", "масс", "профицит", "качаюсь", "буду качаться", "кач", "gain"]):
        target_mode = "gain"
    else:
        m_loss = re.search(r'(?:режим|похудение|дефицит|минус|сброс|цель|переключи|потери\s*веса)?\s*(?:на\s*)?(200|300|400)\s*(?:г|гр|грамм|g)?\b', text_lower)
        if m_loss and m_loss.group(1):
            val = m_loss.group(1)
            has_intent_word = any(k in text_lower for k in ["режим", "похуден", "дефицит", "минус", "сброс", "цель", "переключ", "потер", "loss"])
            is_isolated_mode = bool(re.match(r'^(?:режим\s*)?(200|300|400)\s*(?:г|гр|грамм|g)?$', text_lower))
            if has_intent_word or is_isolated_mode:
                target_mode = f"loss_{val}"

    # Check weight extraction (e.g. "мой вес 76.5", "вешу 78", "вес 75 кг", "похудел до 74", "76.5 кг")
    weight_match = re.search(
        r'(?:мой\s+вес|вес|вешу|взвесился|похудел\s+до|запиши\s+вес|сейчас\s+вешу)\s*(?:составляет|сейчас|сегодня)?\s*[:=-]?\s*(\d+[\.,]?\d*)\s*(?:кг|килограмм|kilos|kg)?',
        text_lower
    )
    if not weight_match and re.match(r'^(?:вес\s*)?(\d+[\.,]?\d*)\s*(?:кг|килограмм|kg)$', text_lower):
        weight_match = re.match(r'^(?:вес\s*)?(\d+[\.,]?\d*)\s*(?:кг|килограмм|kg)$', text_lower)

    extracted_weight = None
    if weight_match:
        try:
            val = float(weight_match.group(1).replace(',', '.'))
            if 30.0 <= val <= 300.0:
                extracted_weight = val
        except (ValueError, IndexError):
            pass

    # If neither weight nor mode was detected, return None
    if extracted_weight is None and target_mode is None:
        return None

    current_goals = get_user_goals()
    w_to_save = extracted_weight if extracted_weight is not None else current_goals["weight_current"]
    mode_to_save = target_mode if target_mode is not None else current_goals["goal_mode"]

    updated = save_user_weight_and_goals(w_to_save, mode=mode_to_save, weight_goal=current_goals.get("weight_goal"))

    mode_emoji = "💪" if updated["goal_mode"] == "gain" else "📉"
    diff_str = f"+{updated['delta_kcal']}" if updated['delta_kcal'] >= 0 else f"{updated['delta_kcal']}"

    return (
        f"⚖️ **Параметры веса и цели успешно обновлены!**\n\n"
        f"Текущий вес: **{updated['weight_current']} кг**\n"
        f"{mode_emoji} Режим: **{updated['goal_title']}**\n\n"
        f"📊 **Новые суточные нормы КБЖУ**:\n"
        f"🔥 **Калории**: **{updated['calories']} ккал** (TDEE {updated['tdee']} {diff_str} ккал)\n"
        f"🥩 **Белки**: {updated['protein_g']}g ({round(updated['protein_g'] / updated['weight_current'], 1)} г/кг)\n"
        f"🥑 **Жиры**: {updated['fat_g']}g ({round(updated['fat_g'] / updated['weight_current'], 1)} г/кг)\n"
        f"🍚 **Углеводы**: {updated['carbs_g']}g\n\n"
        f"⚡ **Проверка баланса энергии**: `{updated['energy_check']}` ✓\n\n"
        f"🌐 [Открыть обновленный Дашборд](https://fatcaunter.vercel.app)"
    )

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
        from gemini_client import get_genai_client
        client = get_genai_client()
        if not client:
            return None
        try:
            from google.genai import types
            model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
            prompt = f"""Classify this Russian message into exactly one category. Reply with ONLY the category word.

Categories:
- food: user is describing food they ate (e.g. яйца, макароны) OR logged activities/burned calories (e.g. тренировка, активность, потратил, сожжен)
- task: user asks a technical question, reports a bug, requests a feature, or asks "why/how" about the app
- summary: user wants to see today's calorie/nutrition summary
- coach: user wants diet advice or recommendations
- price: user is logging a product price (рублей, евро, стоит)

Message: "{text}"

Reply with ONLY one word: food, task, summary, coach, or price"""

            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.0, max_output_tokens=1000)
            )
            tokens = (resp.text or "").strip().lower().split()
            intent = tokens[0] if tokens else None
            if intent in ("food", "task", "summary", "coach", "price"):
                return intent
        except Exception as e:
            print(f"Intent classification error: {e}")
        return None

    def route_input(self, raw_text: str, input_type: str = "text", image_bytes: bytes = None) -> str:
        if not raw_text and not image_bytes:
            return "⚠️ Пустое сообщение. Напишите или надиктуйте еду (например: '200г творога, 2 яйца')."

        text_lower = raw_text.lower().strip() if raw_text else ""

        # Guard: reject UI button texts that must never reach the food pipeline
        NON_FOOD_UI_TEXTS = [
            "запись приема пищи", "технический таск",
            "итоги за сегодня", "советы ии-тренера", "список продуктов",
            "очистить записи", "стереть записи"
        ]
        if any(text_lower == t for t in NON_FOOD_UI_TEXTS):
            if text_lower == "список продуктов":
                from agents.ingestion_agent import format_products_catalog
                return format_products_catalog()
            if text_lower in ("очистить записи", "стереть записи"):
                from bot.meal_cleanup import get_clear_records_view
                view_text, _, _ = get_clear_records_view()
                return view_text
            return "👇 Нажмите одну из кнопок ниже чтобы начать."

        if any(k in text_lower for k in ["список продуктов", "база продуктов", "мои продукты"]):
            from agents.ingestion_agent import format_products_catalog
            return format_products_catalog()

        if any(k in text_lower for k in ["очистить записи", "стереть записи", "удалить запись"]):
            from bot.meal_cleanup import get_clear_records_view
            view_text, _, _ = get_clear_records_view()
            return view_text

        m_del = re.match(r'^(?:удали|удалить|стереть|сотри)\s+продукт\s+(.+)$', text_lower)
        if m_del:
            from database.db import delete_product
            from agents.ingestion_agent import format_products_catalog
            p_to_del = m_del.group(1).strip()
            delete_product(p_to_del)
            return f"✅ Продукт **{p_to_del.capitalize()}** успешно удален из базы и таблицы!\n\n{format_products_catalog()}"

        if any(k in text_lower for k in [
            "аудит", "проверь дубликаты", "проверь таблицу", "почисти повторы",
            "проверь базу", "проверь продукты", "повторы", "/audit"
        ]):
            from agents.economy_agent import economy_agent
            return economy_agent.run_audit_command()

        # Check if user is logging weight or switching goal mode
        weight_res = handle_weight_or_goal_update(text_lower)
        if weight_res:
            return weight_res

        # ── LLM Intent Classification (Gemini) ──────────────────────────────
        # When GEMINI_API_KEY is set, Gemini classifies ANY natural language phrase.
        # This replaces brittle keyword matching for the majority of inputs.
        llm_intent = self._classify_intent_llm(raw_text)

        if llm_intent == "summary":
            today = get_today_summary()
            cost_str = f"\n💰 **Потрачено на еду**: {today.get('total_cost_eur', 0.0):.2f} €" if today.get('total_cost_eur', 0) > 0 else ""
            return (
                f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
                f"🔥 **Калории**: {int(round(today['total_calories']))} / {today['goals']['calories']} ккал\n"
                f"🥩 **Белки**: {int(round(today['total_protein']))}g / {today['goals']['protein_g']}g\n"
                f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {today['goals']['fat_g']}g\n"
                f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {today['goals']['carbs_g']}g"
                f"{cost_str}"
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
            return process_add_product(raw_text=raw_text, image_bytes=image_bytes)

        # If llm_intent == "food" OR no Gemini key — fall through to keyword + food pipeline below

        # ── Keyword fallback (no GEMINI_API_KEY) ────────────────────────────
        # 1. Check if user is logging a product price
        if llm_intent is None:
            if any(w in text_lower for w in ["стоят", "стоит", "цена", "стоимость", "евро", "euro", "€", "$", "руб", "рублей"]):
                price_res = process_add_product(raw_text=raw_text, image_bytes=image_bytes)
                if price_res:
                    return price_res

            if any(cmd in text_lower for cmd in ["/summary", "итоги", "сколько я съел", "калории за день", "норма"]):
                today = get_today_summary()
                cost_str = f"\n💰 **Потрачено на еду**: {today.get('total_cost_eur', 0.0):.2f} €" if today.get('total_cost_eur', 0) > 0 else ""
                return (
                    f"📊 **Итоги за сегодня ({today['date']})**:\n\n"
                    f"🔥 **Калории**: {int(round(today['total_calories']))} / {today['goals']['calories']} ккал\n"
                    f"🥩 **Белки**: {int(round(today['total_protein']))}g / {today['goals']['protein_g']}g\n"
                    f"🥑 **Жиры**: {int(round(today['total_fat']))}g / {today['goals']['fat_g']}g\n"
                    f"🍚 **Углеводы**: {int(round(today['total_carbs']))}g / {today['goals']['carbs_g']}g"
                    f"{cost_str}"
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
                "не работает", "не заполняется", "задачу", "задача", "отправь"
            ]):
                feature_res = self.process_feature_request(raw_text)
                return (
                    f"👨‍💼 **Тимлид принял задачу!**\n\n{feature_res['summary']}\n\nСформированы подзадачи для агентов:\n"
                    + "\n".join([f"• [{t['agent']}]: {t['task']}" for t in feature_res.get("tasks", [])])
                    + "\n\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)"
                )

        # 4. Multi-Meal Processing Pipeline (Supports multiple meals dictated in one audio message)
        llm_meals = ingestion_agent._parse_llm(raw_text, image_bytes=image_bytes)
        
        # If LLM didn't return multi-meal array, build single meal structure only for explicit food items
        if not llm_meals:
            parsed_items = ingestion_agent.parse(raw_text, image_bytes=image_bytes)
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

            price_map = get_product_price_map()
            meal_cost = 0.0
            item_lines = []
            for item in audited_items:
                p_val = int(round(item['protein_g']))
                f_val = int(round(item['fat_g']))
                c_val = int(round(item['carbs_g']))
                cal_val = int(round(item['calories']))
                g_val = int(round(item['quantity_g']))
                pr100 = find_item_price_per_100g(item['product_name'], price_map)
                cost_part = ""
                if pr100 is not None and g_val > 0:
                    it_cost = (g_val / 100.0) * pr100
                    meal_cost += it_cost
                    cost_part = f" | 💰 {it_cost:.2f} €"
                item_lines.append(f"• {item['product_name']} ({g_val}g): {cal_val} ккал | Б:{p_val}g | Ж:{f_val}g | У:{c_val}g{cost_part}")

            cost_line = f" | 💰 {meal_cost:.2f} €" if meal_cost > 0 else ""
            saved_meal_responses.append(
                f"{m_icon} **{m_type.upper()} записан!** (Запись #{meal_id})\n"
                + "\n".join(item_lines) + "\n"
                + f"🔥 **Сумма**: {total_cal} ккал | Б: {total_p}g | Ж: {total_f}g | У: {total_c}g{cost_line}"
            )

        if not saved_meal_responses:
            return "⚠️ Не удалось записать продукты из вашего сообщения."

        # Step 5 & 6: Coach & Dashboard sync
        coach_agent.analyze()
        dashboard_agent.render()
        today = get_today_summary()
        day_cost_str = f" | 💰 {today.get('total_cost_eur', 0):.2f} €" if today.get('total_cost_eur', 0) > 0 else ""

        response = (
            "\n\n".join(saved_meal_responses) + "\n\n"
            + f"📊 **Всего за день**: {int(round(today['total_calories']))}/{today['goals']['calories']} ккал "
            + f"(Б: {int(round(today['total_protein']))}g / Ж: {int(round(today['total_fat']))}g / У: {int(round(today['total_carbs']))}g){day_cost_str}"
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

        from datetime import datetime
        try:
            with open("IDEAS.md", "a", encoding="utf-8") as f:
                f.write(f"\n- **{datetime.now().strftime('%Y-%m-%d %H:%M')}**: {user_prompt}")
        except Exception as e:
            print(f"Failed to write to IDEAS.md: {e}")

        save_coach_recommendation(
            topic="Запрос фичи от пользователя",
            recommendation=f"Идея записана в блокнот (IDEAS.md): {user_prompt}",
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

