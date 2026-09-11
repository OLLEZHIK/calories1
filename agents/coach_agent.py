from typing import List, Dict, Any
import os
import json
from database.db import get_today_summary, get_recent_meals, save_coach_recommendation

class CoachAgent:
    """
    Agent 5: Personal Coach / Advisor Agent
    Uses Gemini to analyze eating patterns, identify unhealthy fat/sugar sources,
    evaluate protein goals, and generate actionable recommendations.
    """
    def __init__(self):
        self.name = "CoachAgent"

    def analyze(self) -> Dict[str, Any]:
        summary = get_today_summary()
        meals = get_recent_meals(limit=10)
        
        recommendations = []
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()

        if gemini_key:
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=gemini_key)
                model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
                
                prompt = f"""You are a professional nutrition coach. Analyze the user's daily food intake and recent meals in Russian.
Provide exactly 1-3 short, actionable recommendations.
Return ONLY a valid JSON object with key "recommendations": a list of objects with "severity" ("info", "tip", "warning") and "message" (short string in Russian).

Today's summary:
Calories: {summary.get('total_calories', 0)} / {summary['goals']['calories']}
Protein: {summary.get('total_protein', 0)}g / {summary['goals']['protein_g']}g
Fat: {summary.get('total_fat', 0)}g / {summary['goals']['fat_g']}g
Carbs: {summary.get('total_carbs', 0)}g / {summary['goals']['carbs_g']}g

Recent meals:
{json.dumps(meals, ensure_ascii=False)}"""

                resp = client.models.generate_content(
                    model=model,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.2, max_output_tokens=300)
                )
                
                content = resp.text or ""
                import re
                json_match = re.search(r'(\{[\s\S]*\})', content)
                if json_match:
                    parsed = json.loads(json_match.group(1))
                    for rec in parsed.get("recommendations", []):
                        save_coach_recommendation(topic="Gemini Coach", recommendation=rec["message"], severity=rec.get("severity", "tip"))
                        recommendations.append({"severity": rec.get("severity", "tip"), "message": rec["message"]})
                
                if recommendations:
                    return {"summary": summary, "recommendations": recommendations}
            except Exception as e:
                print(f"Gemini Coach Error: {e}")

        # Fallback rules if Gemini fails or is missing
        total_fat = summary.get("total_fat", 0)
        total_protein = summary.get("total_protein", 0)
        target_protein = summary["goals"]["protein_g"]
        target_fat = summary["goals"]["fat_g"]

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

        if total_protein < target_protein * 0.5:
            rec = f"Текущий уровень белка ({total_protein}г) значительно ниже дневной цели ({target_protein}г). Добавьте творог, яйца или куриную грудку в следующий прием пищи."
            save_coach_recommendation(topic="Уровень белка", recommendation=rec, severity="tip")
            recommendations.append({"severity": "tip", "message": rec})

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
