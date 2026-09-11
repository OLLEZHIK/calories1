from typing import List, Dict, Any

class AuditorAgent:
    """
    Agent 3: Auditor / Reviewer Agent
    Validates calculations, checks P/F/C energy consistency (Calories = 4*Protein + 9*Fat + 4*Carbs),
    and flags suspicious values or outliers.
    """
    def __init__(self):
        self.name = "AuditorAgent"

    def audit(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        non_food_keywords = [
            "дашборд", "даш борд", "оптимизируй", "оптимизация", "верстка", "верстк", "дизайн",
            "интерфейс", "кнопка", "сервер", "ошибка", "баг", "исправь", "настрой", "сделай",
            "разработчик", "версия", "мобилка", "мобильная", "фича", "код", "тест"
        ]

        audited_items = []
        for item in items:
            p_name = (item.get("product_name") or "").lower()

            # Skip items that are clearly technical instructions or system feedback
            if any(kw in p_name for kw in non_food_keywords):
                print(f"AuditorAgent filtered out non-food input: '{item.get('product_name')}'")
                continue

            p = float(item.get("protein_g", 0))
            f = float(item.get("fat_g", 0))
            c = float(item.get("carbs_g", 0))
            cal = float(item.get("calories", 0))

            # Macro energy check: 4 kcal per protein/carb, 9 kcal per fat
            expected_calories = int(round((p * 4.0) + (f * 9.0) + (c * 4.0)))

            # If discrepancy is > 20%, recalculate/adjust calories to ensure macro truth
            if cal > 0 and abs(cal - expected_calories) / cal > 0.20 and expected_calories > 0:
                item["calories"] = expected_calories
                item["audit_note"] = f"Calories corrected from {cal} to macro-based {expected_calories}"
            else:
                item["audit_note"] = "Audit verified OK"

            audited_items.append(item)

        return audited_items

auditor_agent = AuditorAgent()
