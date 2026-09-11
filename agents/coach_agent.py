from typing import List, Dict, Any
from database.db import get_today_summary, get_recent_meals, save_coach_recommendation

class CoachAgent:
    """
    Agent 5: Personal Coach / Advisor Agent
    Analyzes eating patterns, identifies unhealthy fat/sugar sources (e.g. mayonnaise excess),
    evaluates protein goals, and generates actionable recommendations.
    """
    def __init__(self):
        self.name = "CoachAgent"

    def analyze(self) -> Dict[str, Any]:
        summary = get_today_summary()
        meals = get_recent_meals(limit=10)
        
        recommendations = []

        total_fat = summary.get("total_fat", 0)
        total_protein = summary.get("total_protein", 0)
        target_protein = summary["goals"]["protein_g"]
        target_fat = summary["goals"]["fat_g"]

        # Check for mayonnaise or butter overuse in meals
        mayo_fat = 0.0
        for m in meals:
            for item in m.get("items", []):
                p_name = item.get("product_name", "").lower()
                if "майонез" in p_name:
                    mayo_fat += item.get("fat_g", 0)

        if mayo_fat > 25:
            rec = f"Замечено высокое потребление жиров из майонеза ({round(mayo_fat, 1)}г жира). Попробуйте заменить майонез на 10-15% сметану, греческий йогурт или авокадо."
            save_coach_recommendation(topic="Качество жиров", recommendation=rec, severity="warning")
            recommendations.append({"severity": "warning", "message": rec})

        # Check protein goal progress
        if total_protein < target_protein * 0.5:
            rec = f"Текущий уровень белка ({total_protein}г) значительно ниже дневной цели ({target_protein}г). Добавьте творог, яйца или куриную грудку в следующий прием пищи."
            save_coach_recommendation(topic="Уровень белка", recommendation=rec, severity="tip")
            recommendations.append({"severity": "tip", "message": rec})

        # Check fat excess
        if total_fat > target_fat * 1.2:
            rec = f"Превышена дневная норма жиров ({total_fat}г из {target_fat}г). Рекомендуется снизить растительное масло и жирные соусы в вечернем приеме пищи."
            save_coach_recommendation(topic="Избыток жиров", recommendation=rec, severity="warning")
            recommendations.append({"severity": "warning", "message": rec})

        if not recommendations:
            rec = "Рацион выглядит сбалансированным! Отличная работа по соблюдению норм БЖУ."
            save_coach_recommendation(topic="Баланс", recommendation=rec, severity="info")
            recommendations.append({"severity": "info", "message": rec})

        return {
            "summary": summary,
            "recommendations": recommendations
        }

coach_agent = CoachAgent()
