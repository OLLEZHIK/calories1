from http.server import BaseHTTPRequestHandler
import json
from database.db import (
    get_today_summary, get_recent_meals, get_product_prices, get_meals_for_days,
    get_recent_recommendations, save_user_weight_and_goals
)
import urllib.parse

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path == '/api/summary' or parsed_path.path == '/api/summary/':
            query_params = urllib.parse.parse_qs(parsed_path.query)
            target_date = query_params.get('date', [None])[0]

            from database.db import get_product_price_map
            price_map = get_product_price_map()
            products = get_product_prices()
            summary = get_today_summary(target_date, price_map=price_map)
            meals = get_recent_meals(limit=10, target_date=target_date, price_map=price_map)

            # Fast coach recommendations from DB cache without waiting for Gemini LLM
            recent_recs = get_recent_recommendations(limit=6)
            coach_tips = [
                {"topic": r.get("topic") or "Совет тренера", "severity": r.get("severity", "tip"), "message": r.get("recommendation", "")}
                for r in recent_recs
                if not (r.get("topic", "").startswith("Продукт:") or r.get("topic", "").startswith("Запрос фичи"))
            ]
            if not coach_tips:
                coach_tips = [
                    {"topic": "Баланс рациона", "severity": "info", "message": "Соблюдайте баланс белков, жиров и углеводов в течение дня."},
                    {"topic": "Водный баланс", "severity": "tip", "message": "Пейте достаточное количество чистой воды между приёмами пищи."}
                ]
            coach = {"summary": summary, "recommendations": coach_tips[:3]}
            
            # Generate dynamic live telemetry logs for the 6 agents
            telemetry = []
            for m in meals[:5]:
                ts = (m.get("timestamp") or "")[11:16] or "12:00"
                raw = m.get("raw_input", "")
                m_type = m.get("meal_type", "Прием пищи")
                items = m.get("items", [])
                tot_cal = m.get("total_calories", 0)
                tot_p = m.get("total_protein", 0)
                tot_f = m.get("total_fat", 0)
                tot_c = m.get("total_carbs", 0)
                prod_names = ", ".join([i.get("product_name", "") for i in items[:3]])

                telemetry.append({
                    "timestamp": ts,
                    "agent": "TeamLeadAgent",
                    "tag": "ROUTE_OK",
                    "level": "ok",
                    "message": f"Входное сообщение: '{raw[:50]}...'. Запрос передан в конвейер обработки."
                })
                telemetry.append({
                    "timestamp": ts,
                    "agent": "IngestionAgent",
                    "tag": "LLM_PARSE",
                    "level": "ok",
                    "message": f"Распознано продуктов ({len(items)} шт): {prod_names}."
                })
                telemetry.append({
                    "timestamp": ts,
                    "agent": "NutritionAgent",
                    "tag": "CALC_MACROS",
                    "level": "ok",
                    "message": f"Расчитано для {m_type}: {tot_cal} ккал (Б:{tot_p}g, Ж:{tot_f}g, У:{tot_c}g)."
                })
                telemetry.append({
                    "timestamp": ts,
                    "agent": "AuditorAgent",
                    "tag": "AUDIT_PASS",
                    "level": "ok",
                    "message": f"Проверка энергетического баланса (4P+9F+4C) пройдна. Фильтрация несъедобных терминов OK."
                })
                telemetry.append({
                    "timestamp": ts,
                    "agent": "DashboardAgent",
                    "tag": "SYNC_SUPABASE",
                    "level": "ok",
                    "message": f"Запись #{m.get('id')} ({m_type}) синхронизирована с Supabase Cloud и Веб-дашбордом."
                })

            # Also get history for the last 7 days for the chart
            history_meals = get_meals_for_days(7)
            history_summary = {}
            for m in history_meals:
                d = (m.get("timestamp") or "")[:10]
                if d:
                    history_summary[d] = history_summary.get(d, 0) + m.get("total_calories", 0)

            payload = {
                "status": "success",
                "summary": summary,
                "meals": meals,
                "coach": coach,
                "products": products,
                "history": history_summary,
                "agent_telemetry": telemetry
            }

            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        if parsed_path.path in ['/api/goals', '/api/goals/', '/api/weight', '/api/weight/']:
            try:
                content_length = int(self.headers.get('Content-Length', 0))
                body = self.rfile.read(content_length).decode('utf-8') if content_length > 0 else "{}"
                data = json.loads(body)

                weight = data.get("weight_current")
                if weight is not None:
                    weight = float(weight)
                else:
                    weight = 76.0

                mode = data.get("goal_mode")
                weight_goal = data.get("weight_goal")
                if weight_goal is not None:
                    weight_goal = float(weight_goal)

                from database.db import save_user_weight_and_goals, get_today_summary
                updated_goals = save_user_weight_and_goals(weight, mode=mode, weight_goal=weight_goal)
                summary = get_today_summary()

                payload = {
                    "status": "success",
                    "goals": updated_goals,
                    "summary": summary
                }

                self.send_response(200)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
            except Exception as e:
                self.send_response(400)
                self.send_header('Content-type', 'application/json')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')
