import re
from typing import Tuple, Optional, Dict, Any, List
from database.db import get_recent_meals, delete_meal, clear_recent_meals

def get_clear_records_view() -> Tuple[str, Optional[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    Returns (text_message, inline_keyboard_markup_dict, list_of_meals)
    for the last 5 meals.
    """
    meals = get_recent_meals(limit=5)
    if not meals:
        return (
            "🗑 **Предыдущие записи:**\n\n"
            "В вашем дневнике пока нет сохраненных записей за последнее время.",
            None,
            []
        )

    lines = [
        "🗑 **Предыдущие записи приемов пищи (последние 5):**\n"
    ]
    inline_buttons = []

    for i, m in enumerate(meals, 1):
        meal_id = m.get("id")
        meal_type = m.get("meal_type") or "Прием пищи"
        
        # Time formatting
        ts = m.get("timestamp") or ""
        time_str = ts[-5:] if len(ts) >= 5 and ":" in ts[-5:] else ""
        time_part = f" ({time_str})" if time_str else ""
        
        cals = m.get("total_calories", 0)
        p = m.get("total_protein", 0)
        f = m.get("total_fat", 0)
        c = m.get("total_carbs", 0)

        # Ingredients preview
        items = m.get("items") or []
        items_preview = []
        for item in items[:4]:
            pname = item.get("product_name", "")
            q = int(round(float(item.get("quantity_g", 0) or 0)))
            if q > 0:
                items_preview.append(f"{pname} ({q}г)")
            else:
                items_preview.append(pname)
        items_text = ", ".join(items_preview)
        if len(items) > 4:
            items_text += f" и ещё {len(items)-4} поз."

        lines.append(f"{i}️⃣ **{meal_type}{time_part}** — **{cals} ккал** (Б:{p}g | Ж:{f}g | У:{c}g)")
        if items_text:
            lines.append(f"   • _{items_text}_")
        lines.append("")

        # Inline button for deleting this specific meal
        btn_text = f"❌ Стереть #{i} ({meal_type}, {cals} ккал)"
        inline_buttons.append([{"text": btn_text, "callback_data": f"del_meal_{meal_id}"}])

    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    lines.append("👇 **Нажмите кнопку ниже, чтобы стереть запись, или отправьте её номер (1-5):**")

    # Group actions
    if len(meals) > 1:
        inline_buttons.append([{"text": f"🗑 Стереть все {len(meals)} записей", "callback_data": "del_meals_all"}])
    inline_buttons.append([{"text": "✖️ Отмена", "callback_data": "del_meals_cancel"}])

    reply_markup = {"inline_keyboard": inline_buttons}
    return "\n".join(lines), reply_markup, meals


def handle_delete_meal_action(meal_id: int) -> Tuple[str, Optional[Dict[str, Any]]]:
    """
    Deletes the meal and returns the confirmation message with the updated list.
    """
    delete_meal(meal_id)
    meals = get_recent_meals(limit=5)
    if not meals:
        return (
            "✅ **Запись успешно стёрта!**\n\n"
            "Все предыдущие записи приемов пищи очищены. Дневник и дашборд обновлены.",
            None
        )

    view_text, markup, _ = get_clear_records_view()
    msg = f"✅ **Запись успешно стёрта!** Дневник и дашборд обновлены.\n\n{view_text}"
    return msg, markup


def handle_delete_all_action(limit: int = 5) -> str:
    """Deletes all recent meals up to limit and returns confirmation."""
    cleared = clear_recent_meals(limit=limit)
    if cleared > 0:
        return f"✅ **Успешно стёрто записей: {cleared}**.\n\nДневник питания очищен, дашборд обновлён."
    return "ℹ️ В дневнике не было записей для удаления."


def parse_and_execute_text_delete(text: str) -> Optional[Tuple[str, Optional[Dict[str, Any]]]]:
    """
    Checks if text is a deletion command (e.g. '1', 'стереть 1', 'все', 'отмена')
    and executes it. Returns (response_text, optional_markup) or None if not a delete command.
    """
    cleaned = text.strip().lower()

    if cleaned in ("отмена", "отменить", "cancel", "назад"):
        return ("❌ Операция очистки записей отменена.", None)

    if cleaned in ("все", "всё", "стереть все", "удалить все", "стереть всё", "удалить всё", "clear all", "all"):
        return (handle_delete_all_action(limit=5), None)

    # Check for single number: "1", "2", "3", "4", "5" or "стереть 2"
    m = re.search(r'^(?:стереть|удалить|del|delete)?\s*#?\s*([1-5])$', cleaned)
    if m:
        idx = int(m.group(1))
        recent = get_recent_meals(limit=5)
        if 1 <= idx <= len(recent):
            target_meal = recent[idx - 1]
            meal_id = target_meal.get("id")
            meal_name = target_meal.get("meal_type") or "Прием пищи"
            cals = target_meal.get("total_calories", 0)
            msg, markup = handle_delete_meal_action(meal_id)
            return (f"🗑 **Запись #{idx} ({meal_name}, {cals} ккал) стёрта!**\n\n{msg}", markup)
        else:
            return (f"⚠️ Запись с номером #{idx} не найдена. Доступны номера от 1 до {len(recent)}.", None)

    return None
