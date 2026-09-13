import json
import re
from pathlib import Path
from typing import Dict, Any
from database.db import (
    get_today_summary, get_recent_meals, get_product_prices, get_meals_for_days,
    get_recent_recommendations
)
from agents.coach_agent import coach_agent

class DashboardAgent:
    """
    Agent 6: Coder / Dashboard Agent
    Maintains and updates the Web Dashboard with live dynamic JS sync.
    """
    def __init__(self):
        self.name = "DashboardAgent"

    def render(self) -> str:
        out_file = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"
        if not out_file.exists():
            return str(out_file)

        try:
            summary = get_today_summary()
            meals = get_recent_meals(limit=10)
            recent_recs = get_recent_recommendations(limit=6)
            coach_tips = [
                {"severity": r.get("severity", "tip"), "message": r.get("recommendation", "")}
                for r in recent_recs
                if not (r.get("topic", "").startswith("Продукт:") or r.get("topic", "").startswith("Запрос фичи"))
            ]
            if not coach_tips:
                coach_tips = [
                    {"severity": "info", "message": "Соблюдайте баланс белков, жиров и углеводов в течение дня."},
                    {"severity": "tip", "message": "Старайтесь распределить дневную норму белка (160 г) равномерно между 3–4 приемами пищи."}
                ]
            coach = {"summary": summary, "recommendations": coach_tips[:3]}
            products = get_product_prices()

            history_meals = get_meals_for_days(7)
            history_summary = {}
            for m in history_meals:
                d = (m.get("timestamp") or "")[:10]
                if d:
                    history_summary[d] = history_summary.get(d, 0) + m.get("total_calories", 0)

            data = {
                "status": "success",
                "summary": summary,
                "meals": meals,
                "coach": coach,
                "products": products,
                "history": history_summary,
            }

            content = out_file.read_text(encoding="utf-8")
            json_str = json.dumps(data, ensure_ascii=False)
            initial_data_script = f"window.INITIAL_DATA = {json_str};\n"

            if "window.INITIAL_DATA =" in content:
                content = re.sub(
                    r'window\.INITIAL_DATA\s*=[\s\S]*?;\n',
                    initial_data_script,
                    content,
                    count=1
                )
            else:
                content = content.replace("<script>\n", f"<script>\n{initial_data_script}", 1)

            out_file.write_text(content, encoding="utf-8")
        except Exception as e:
            print(f"DashboardAgent render error: {e}")

        return str(out_file)

dashboard_agent = DashboardAgent()
