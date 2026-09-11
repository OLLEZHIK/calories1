import json
from pathlib import Path
from typing import Dict, Any
from database.db import get_today_summary, get_recent_meals, get_product_prices, get_recent_recommendations

class DashboardAgent:
    """
    Agent 6: Coder / Dashboard Agent
    Generates and updates the mobile-friendly HTML Web Dashboard with live DB data.
    """
    def __init__(self):
        self.name = "DashboardAgent"

    def render(self) -> str:
        summary = get_today_summary()
        meals = get_recent_meals(limit=10)
        prices = get_product_prices()
        recommendations = get_recent_recommendations(limit=5)

        html_template = f"""<!DOCTYPE html>
<html lang="ru">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Calories AI Dashboard</title>
    <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {{
            --bg-dark: #0f172a;
            --card-bg: rgba(30, 41, 59, 0.7);
            --border-glow: rgba(56, 189, 248, 0.2);
            --accent-cyan: #38bdf8;
            --accent-purple: #a855f7;
            --accent-green: #22c55e;
            --accent-orange: #f97316;
            --accent-red: #ef4444;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
        }}
        * {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'Outfit', sans-serif; }}
        body {{
            background: linear-gradient(135deg, #0b0f19 0%, #1e1b4b 50%, #0f172a 100%);
            color: var(--text-main);
            min-height: 100vh;
            padding: 16px;
        }}
        .container {{ max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; gap: 20px; }}
        header {{ text-align: center; margin-bottom: 10px; }}
        header h1 {{ font-size: 1.8rem; font-weight: 700; background: linear-gradient(90deg, #38bdf8, #a855f7); -webkit-background-clip: text; -webkit-text-fill-color: transparent; }}
        header p {{ color: var(--text-muted); font-size: 0.9rem; margin-top: 4px; }}
        
        .card {{
            background: var(--card-bg);
            backdrop-filter: blur(12px);
            border: 1px solid var(--border-glow);
            border-radius: 20px;
            padding: 20px;
            box-shadow: 0 10px 30px rgba(0,0,0,0.3);
        }}
        
        .grid-stats {{ display: grid; grid-template-columns: repeat(2, 1fr); gap: 12px; }}
        .stat-box {{ background: rgba(15, 23, 42, 0.6); padding: 14px; border-radius: 14px; text-align: center; border: 1px solid rgba(255,255,255,0.05); }}
        .stat-val {{ font-size: 1.4rem; font-weight: 700; margin-top: 4px; }}
        .stat-lbl {{ font-size: 0.8rem; color: var(--text-muted); text-transform: uppercase; letter-spacing: 1px; }}
        
        .progress-bar-container {{ margin-top: 8px; background: rgba(255,255,255,0.1); height: 8px; border-radius: 4px; overflow: hidden; }}
        .progress-fill {{ height: 100%; border-radius: 4px; transition: width 0.5s ease; }}
        
        .meal-list {{ display: flex; flex-direction: column; gap: 12px; }}
        .meal-item {{ background: rgba(15, 23, 42, 0.4); border-left: 4px solid var(--accent-cyan); padding: 12px; border-radius: 10px; }}
        .meal-time {{ font-size: 0.75rem; color: var(--text-muted); }}
        .meal-raw {{ font-weight: 600; margin: 4px 0; color: #e2e8f0; }}
        .meal-macros {{ font-size: 0.82rem; color: var(--accent-cyan); display: flex; gap: 12px; margin-top: 4px; }}

        .coach-box {{ background: rgba(168, 85, 247, 0.1); border: 1px solid rgba(168, 85, 247, 0.3); padding: 14px; border-radius: 14px; margin-bottom: 8px; }}
        .coach-title {{ color: var(--accent-purple); font-weight: 600; font-size: 0.95rem; display: flex; align-items: center; gap: 6px; }}
        .coach-desc {{ font-size: 0.88rem; color: #cbd5e1; margin-top: 4px; }}

        .badge {{ padding: 2px 8px; border-radius: 6px; font-size: 0.7rem; font-weight: 700; display: inline-block; }}
        .badge-warning {{ background: rgba(239, 68, 68, 0.2); color: var(--accent-red); }}
        .badge-tip {{ background: rgba(34, 197, 94, 0.2); color: var(--accent-green); }}
        .badge-info {{ background: rgba(56, 189, 248, 0.2); color: var(--accent-cyan); }}
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Calories AI Dashboard</h1>
            <p>Мультиагентный счетчик калорий & БЖУ | {summary['date']}</p>
        </header>

        <!-- Dynamic Macro Stats -->
        <div class="card">
            <h3 style="margin-bottom: 14px; font-size: 1rem; color: var(--text-muted);">Итоги за сегодня</h3>
            <div class="grid-stats">
                <div class="stat-box">
                    <div class="stat-lbl">Калории</div>
                    <div class="stat-val" style="color: var(--accent-cyan);">{summary['total_calories']} / {summary['goals']['calories']}</div>
                    <div class="progress-bar-container">
                        <div class="progress-fill" style="width: {min(100, int((summary['total_calories']/summary['goals']['calories'])*100))}%; background: var(--accent-cyan);"></div>
                    </div>
                </div>

                <div class="stat-box">
                    <div class="stat-lbl">Белок</div>
                    <div class="stat-val" style="color: var(--accent-green);">{summary['total_protein']}g / {summary['goals']['protein_g']}g</div>
                    <div class="progress-bar-container">
                        <div class="progress-fill" style="width: {min(100, int((summary['total_protein']/summary['goals']['protein_g'])*100))}%; background: var(--accent-green);"></div>
                    </div>
                </div>

                <div class="stat-box">
                    <div class="stat-lbl">Жиры</div>
                    <div class="stat-val" style="color: var(--accent-orange);">{summary['total_fat']}g / {summary['goals']['fat_g']}g</div>
                    <div class="progress-bar-container">
                        <div class="progress-fill" style="width: {min(100, int((summary['total_fat']/summary['goals']['fat_g'])*100))}%; background: var(--accent-orange);"></div>
                    </div>
                </div>

                <div class="stat-box">
                    <div class="stat-lbl">Углеводы</div>
                    <div class="stat-val" style="color: var(--accent-purple);">{summary['total_carbs']}g / {summary['goals']['carbs_g']}g</div>
                    <div class="progress-bar-container">
                        <div class="progress-fill" style="width: {min(100, int((summary['total_carbs']/summary['goals']['carbs_g'])*100))}%; background: var(--accent-purple);"></div>
                    </div>
                </div>
            </div>
        </div>

        <!-- Coach Recommendations -->
        <div class="card">
            <h3 style="margin-bottom: 14px; font-size: 1rem; color: var(--accent-purple);">💡 Советы Личного Тренера (Coach Agent)</h3>
            {"".join([f'''
            <div class="coach-box">
                <div class="coach-title">
                    <span class="badge badge-{r.get('severity', 'info')}">{r.get('severity', 'info').upper()}</span>
                    {r.get('topic')}
                </div>
                <div class="coach-desc">{r.get('recommendation')}</div>
            </div>
            ''' for r in recommendations]) if recommendations else '<p style="color: var(--text-muted);">Пока нет новых рекомендаций.</p>'}
        </div>

        <!-- Meal History -->
        <div class="card">
            <h3 style="margin-bottom: 14px; font-size: 1rem; color: var(--text-muted);">🍽 Приемы пищи</h3>
            <div class="meal-list">
            {"".join([f'''
                <div class="meal-item">
                    <div class="meal-time">{m["timestamp"]}</div>
                    <div class="meal-raw">{m["raw_input"]}</div>
                    <div class="meal-macros">
                        <span>🔥 {round(m["total_calories"])} ккал</span>
                        <span>🥩 Б: {round(m["total_protein"],1)}g</span>
                        <span>🥑 Ж: {round(m["total_fat"],1)}g</span>
                        <span>🍚 У: {round(m["total_carbs"],1)}g</span>
                    </div>
                </div>
            ''' for m in meals]) if meals else '<p style="color: var(--text-muted);">Приемов пищи пока не зарегистрировано.</p>'}
            </div>
        </div>
    </div>
</body>
</html>
"""
        out_file = Path(__file__).resolve().parent.parent / "dashboard" / "index.html"
        out_file.parent.mkdir(parents=True, exist_ok=True)
        with open(out_file, "w", encoding="utf-8") as f:
            f.write(html_template)

        return str(out_file)

dashboard_agent = DashboardAgent()
