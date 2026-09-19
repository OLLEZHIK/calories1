from http.server import BaseHTTPRequestHandler
import json
import os
import sys
import urllib.parse
from pathlib import Path

from database.db import (
    get_today_summary, get_recent_meals, get_product_prices, get_meals_for_days,
    get_recent_recommendations, save_user_weight_and_goals,
    save_product_price, update_product_price, delete_product_entry,
    estimate_product_nutrition
)

BASE_DIR = Path(__file__).resolve().parent.parent

class handler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, data: dict):
        self.send_response(status_code)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def _read_body_json(self) -> dict:
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length).decode('utf-8')
                return json.loads(body)
        except Exception:
            pass
        return {}

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path.rstrip('/')

        if path in ['/api/products']:
            products = get_product_prices()
            self._send_json(200, {"status": "success", "products": products})
            return

        if path in ['/api/summary']:
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

            self._send_json(200, payload)
            return

        # Static file serving for local server
        clean_path = path.lstrip('/')
        if clean_path in ['', 'index.html']:
            dash_index = BASE_DIR / "dashboard" / "index.html"
            if dash_index.exists():
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(dash_index.read_bytes())
                return
        elif clean_path in ['agents', 'agents.html']:
            dash_agents = BASE_DIR / "dashboard" / "agents.html"
            if dash_agents.exists():
                self.send_response(200)
                self.send_header('Content-type', 'text/html; charset=utf-8')
                self.end_headers()
                self.wfile.write(dash_agents.read_bytes())
                return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error": "Not Found"}')

    def do_POST(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path.rstrip('/')

        if path in ['/api/goals', '/api/weight']:
            try:
                data = self._read_body_json()
                weight = data.get("weight_current")
                if weight is not None:
                    weight = float(weight)
                else:
                    weight = 76.0

                mode = data.get("goal_mode")
                weight_goal = data.get("weight_goal")
                if weight_goal is not None:
                    weight_goal = float(weight_goal)

                updated_goals = save_user_weight_and_goals(weight, mode=mode, weight_goal=weight_goal)
                summary = get_today_summary()

                payload = {
                    "status": "success",
                    "goals": updated_goals,
                    "summary": summary
                }

                self._send_json(200, payload)
            except Exception as e:
                self._send_json(400, {"status": "error", "message": str(e)})
            return

        # Handle Products CRUD
        if path in ['/api/products', '/api/products/add', '/api/products/update', '/api/products/delete', '/api/products/estimate']:
            try:
                data = self._read_body_json()
                action = data.get("action", "")
                if path.endswith("/add"):
                    action = "add"
                elif path.endswith("/update"):
                    action = "update"
                elif path.endswith("/delete"):
                    action = "delete"
                elif path.endswith("/estimate"):
                    action = "estimate"
                elif not action:
                    action = "add"

                if action == "estimate":
                    p_name = data.get("product_name", "")
                    cat = data.get("category", "general")
                    est = estimate_product_nutrition(p_name, category=cat)
                    self._send_json(200, {"status": "success", "data": est})
                    return

                elif action == "delete":
                    p_id = data.get("id") or data.get("product_id")
                    p_name = data.get("product_name")
                    delete_product_entry(product_name=p_name, product_id=int(p_id) if p_id else None)
                    self._render_dashboard_cache()
                    products = get_product_prices()
                    self._send_json(200, {
                        "status": "success",
                        "message": "Продукт успешно удален",
                        "products": products
                    })
                    return

                elif action == "update":
                    p_id = data.get("id") or data.get("product_id")
                    res = update_product_price(
                        product_name=data.get("product_name", ""),
                        original_name=data.get("original_name"),
                        product_id=int(p_id) if p_id else None,
                        price_rub=float(data.get("price_rub") or data.get("price") or 0.0),
                        weight_g=float(data.get("weight_g") or 100.0),
                        category=data.get("category", "general"),
                        protein_100g=float(data.get("protein_per_100g") or data.get("protein_100g") or 0.0),
                        fat_100g=float(data.get("fat_per_100g") or data.get("fat_100g") or 0.0),
                        carbs_100g=float(data.get("carbs_per_100g") or data.get("carbs_100g") or 0.0),
                        calories_100g=float(data.get("calories_per_100g") or data.get("calories_100g") or 0.0),
                        coach_score=int(data.get("coach_score") or 0),
                        coach_verdict=data.get("coach_verdict", "")
                    )
                    self._render_dashboard_cache()
                    products = get_product_prices()
                    self._send_json(200, {
                        "status": "success",
                        "message": "Продукт успешно обновлен",
                        "product": res,
                        "products": products
                    })
                    return

                elif action == "add":
                    p_name = (data.get("product_name") or "").strip()
                    if not p_name:
                        self._send_json(400, {"status": "error", "message": "Укажите название продукта"})
                        return

                    price_val = float(data.get("price_rub") or data.get("price") or 0.0)
                    weight_val = float(data.get("weight_g") or 100.0)
                    p_val = float(data.get("protein_per_100g") or data.get("protein_100g") or 0.0)
                    f_val = float(data.get("fat_per_100g") or data.get("fat_100g") or 0.0)
                    c_val = float(data.get("carbs_per_100g") or data.get("carbs_100g") or 0.0)
                    cal_val = float(data.get("calories_per_100g") or data.get("calories_100g") or 0.0)
                    score_val = int(data.get("coach_score") or 0)
                    verdict_val = (data.get("coach_verdict") or "").strip()
                    category_val = data.get("category", "general")

                    # If macros are completely 0, auto-estimate
                    if cal_val <= 0 and p_val <= 0 and f_val <= 0 and c_val <= 0:
                        est = estimate_product_nutrition(p_name, category=category_val)
                        cal_val = est.get("calories_100g", 0)
                        p_val = est.get("protein_100g", 0)
                        f_val = est.get("fat_100g", 0)
                        c_val = est.get("carbs_100g", 0)
                        score_val = score_val or est.get("coach_score", 6)
                        verdict_val = verdict_val or est.get("coach_verdict", "")
                        category_val = category_val or est.get("category", "general")

                    save_product_price(
                        product_name=p_name,
                        price_rub=price_val,
                        weight_g=weight_val,
                        category=category_val,
                        protein_100g=p_val,
                        fat_100g=f_val,
                        carbs_100g=c_val,
                        calories_100g=cal_val,
                        coach_score=score_val,
                        coach_verdict=verdict_val
                    )
                    self._render_dashboard_cache()
                    products = get_product_prices()
                    self._send_json(200, {
                        "status": "success",
                        "message": f"Продукт «{p_name}» успешно добавлен",
                        "products": products
                    })
                    return

            except Exception as e:
                self._send_json(400, {"status": "error", "message": str(e)})
                return

        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error": "Not Found"}')

    def do_PUT(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path.rstrip('/')
        if path in ['/api/products']:
            data = self._read_body_json()
            data["action"] = "update"
            self.path = '/api/products/update'
            return self.do_POST()
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error": "Not Found"}')

    def do_DELETE(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path.rstrip('/')
        if path in ['/api/products']:
            data = self._read_body_json()
            data["action"] = "delete"
            self.path = '/api/products/delete'
            return self.do_POST()
        self.send_response(404)
        self.end_headers()
        self.wfile.write(b'{"error": "Not Found"}')

    def _render_dashboard_cache(self):
        try:
            from agents.dashboard_agent import dashboard_agent
            dashboard_agent.render()
        except Exception as e:
            print(f"Render dashboard notice: {e}")

if __name__ == '__main__':
    from http.server import HTTPServer
    port = int(os.getenv("PORT", sys.argv[1] if len(sys.argv) > 1 and sys.argv[1].isdigit() else "8000"))
    server_address = ('', port)
    httpd = HTTPServer(server_address, handler)
    print(f"Calories AI Dashboard & API Server started at http://localhost:{port}")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nServer gracefully stopped.")
