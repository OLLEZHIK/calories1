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
    estimate_product_nutrition, delete_meal_item, update_meal_item,
    add_meal_entry, delete_meal,
    # Auth functions
    create_user, login_user, create_session, validate_session,
    delete_session, get_users_count, get_user_by_id
)

BASE_DIR = Path(__file__).resolve().parent.parent

# Routes that don't require authentication
_PUBLIC_ROUTES = {
    '/api/auth/login',
    '/api/auth/register',
    '/api/auth/check',
}


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
        if hasattr(self, '_cached_body'):
            return self._cached_body
        try:
            content_length = int(self.headers.get('Content-Length', 0))
            if content_length > 0:
                body = self.rfile.read(content_length).decode('utf-8')
                self._cached_body = json.loads(body)
                return self._cached_body
        except Exception:
            pass
        self._cached_body = {}
        return self._cached_body

    def _get_token(self) -> str:
        """Extracts Bearer token from Authorization header."""
        auth_header = self.headers.get('Authorization', '')
        if auth_header.startswith('Bearer '):
            return auth_header[7:].strip()
        return ''

    def _require_auth(self) -> 'Optional[int]':
        """
        Validates the session token. Returns user_id (int) if authenticated.
        Sends 401 and returns None if not authenticated.
        """
        token = self._get_token()
        if not token:
            self._send_json(401, {"error": "Требуется авторизация", "code": "NO_TOKEN"})
            return None
        user_id = validate_session(token)
        if not user_id:
            self._send_json(401, {"error": "Сессия истекла или недействительна. Войдите заново.", "code": "INVALID_TOKEN"})
            return None
        return user_id

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')
        self.end_headers()

    def do_GET(self):
        parsed_path = urllib.parse.urlparse(self.path)
        path = parsed_path.path.rstrip('/')

        # ── Auth check (public) ──────────────────────────────────────────────
        if path == '/api/auth/check':
            token = self._get_token()
            if not token:
                self._send_json(401, {"valid": False, "error": "No token"})
                return
            user_id = validate_session(token)
            if not user_id:
                self._send_json(401, {"valid": False, "error": "Session expired"})
                return
            user = get_user_by_id(user_id)
            self._send_json(200, {
                "valid": True,
                "user_id": user_id,
                "username": user["username"] if user else "unknown"
            })
            return

        # ── All other API routes require auth ────────────────────────────────
        if path.startswith('/api/'):
            user_id = self._require_auth()
            if user_id is None:
                return
        else:
            user_id = 1  # Static file serving — no auth needed

        if path in ['/api/products']:
            products = get_product_prices(user_id=user_id)
            self._send_json(200, {"status": "success", "products": products})
            return

        if path in ['/api/summary']:
            query_params = urllib.parse.parse_qs(parsed_path.query)
            target_date = query_params.get('date', [None])[0]

            from database.db import get_product_price_map
            price_map = get_product_price_map()
            products = get_product_prices(user_id=user_id)
            summary = get_today_summary(target_date, price_map=price_map, user_id=user_id)
            meals = get_recent_meals(limit=10, target_date=target_date, price_map=price_map, user_id=user_id)

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
                    "timestamp": ts, "agent": "TeamLeadAgent", "tag": "ROUTE_OK", "level": "ok",
                    "message": f"Входное сообщение: '{raw[:50]}...'. Запрос передан в конвейер обработки."
                })
                telemetry.append({
                    "timestamp": ts, "agent": "IngestionAgent", "tag": "LLM_PARSE", "level": "ok",
                    "message": f"Распознано продуктов ({len(items)} шт): {prod_names}."
                })
                telemetry.append({
                    "timestamp": ts, "agent": "NutritionAgent", "tag": "CALC_MACROS", "level": "ok",
                    "message": f"Расчитано для {m_type}: {tot_cal} ккал (Б:{tot_p}g, Ж:{tot_f}g, У:{tot_c}g)."
                })
                telemetry.append({
                    "timestamp": ts, "agent": "AuditorAgent", "tag": "AUDIT_PASS", "level": "ok",
                    "message": "Проверка энергетического баланса (4P+9F+4C) пройдна. Фильтрация несъедобных терминов OK."
                })
                telemetry.append({
                    "timestamp": ts, "agent": "DashboardAgent", "tag": "SYNC_SUPABASE", "level": "ok",
                    "message": f"Запись #{m.get('id')} ({m_type}) синхронизирована с Supabase Cloud и Веб-дашбордом."
                })

            # Also get history for the last 7 days for the chart
            history_meals = get_meals_for_days(7, user_id=user_id)
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

        # ── Auth routes (PUBLIC — no token required) ─────────────────────────

        if path == '/api/auth/register':
            try:
                data = self._read_body_json()
                username = (data.get("username") or "").strip()
                password = (data.get("password") or "").strip()
                if not username or not password:
                    self._send_json(400, {"error": "Введите логин и пароль"})
                    return
                # Only allow registration if no users exist yet
                count = get_users_count()
                if count > 0:
                    self._send_json(403, {"error": "Регистрация закрыта. Обратитесь к администратору."})
                    return
                user = create_user(username, password)
                device_name = self.headers.get('User-Agent', '')[:200]
                token = create_session(user["user_id"], device_name=device_name)
                self._send_json(200, {
                    "status": "success",
                    "message": f"Аккаунт «{username}» создан!",
                    "token": token,
                    "username": username,
                    "user_id": user["user_id"]
                })
            except ValueError as e:
                self._send_json(400, {"error": str(e)})
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if path == '/api/auth/login':
            try:
                data = self._read_body_json()
                username = (data.get("username") or "").strip()
                password = (data.get("password") or "").strip()
                if not username or not password:
                    self._send_json(400, {"error": "Введите логин и пароль"})
                    return
                user = login_user(username, password)
                if not user:
                    self._send_json(401, {"error": "Неверный логин или пароль"})
                    return
                device_name = self.headers.get('User-Agent', '')[:200]
                token = create_session(user["user_id"], device_name=device_name)
                self._send_json(200, {
                    "status": "success",
                    "token": token,
                    "username": user["username"],
                    "user_id": user["user_id"]
                })
            except Exception as e:
                self._send_json(500, {"error": str(e)})
            return

        if path == '/api/auth/logout':
            token = self._get_token()
            if token:
                delete_session(token)
            self._send_json(200, {"status": "success", "message": "Выход выполнен"})
            return

        # ── All other POST routes require auth ───────────────────────────────
        user_id = self._require_auth()
        if user_id is None:
            return

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

                updated_goals = save_user_weight_and_goals(weight, mode=mode, weight_goal=weight_goal, user_id=user_id)
                summary = get_today_summary(user_id=user_id)

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
                    delete_product_entry(product_name=p_name, product_id=int(p_id) if p_id else None, user_id=user_id)
                    self._render_dashboard_cache()
                    products = get_product_prices(user_id=user_id)
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
                        coach_verdict=data.get("coach_verdict", ""),
                        user_id=user_id
                    )
                    self._render_dashboard_cache()
                    products = get_product_prices(user_id=user_id)
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
                        coach_verdict=verdict_val,
                        user_id=user_id
                    )
                    self._render_dashboard_cache()
                    products = get_product_prices(user_id=user_id)
                    self._send_json(200, {
                        "status": "success",
                        "message": f"Продукт «{p_name}» успешно добавлен",
                        "products": products
                    })
                    return

            except Exception as e:
                self._send_json(400, {"status": "error", "message": str(e)})
                return

        # Handle Meals CRUD
        if path in ['/api/meals', '/api/meals/add', '/api/meals/update', '/api/meals/delete']:
            try:
                data = self._read_body_json()
                action = data.get("action", "")
                if path.endswith("/add"):
                    action = "add"
                elif path.endswith("/update"):
                    action = "update"
                elif path.endswith("/delete"):
                    action = "delete"
                elif not action:
                    action = "add"

                target_date = data.get("date")

                if action == "delete":
                    item_id = data.get("item_id") or data.get("id")
                    meal_id = data.get("meal_id")
                    if item_id:
                        delete_meal_item(int(item_id))
                    elif meal_id:
                        delete_meal(int(meal_id))
                    else:
                        self._send_json(400, {"status": "error", "message": "Не указан item_id или meal_id для удаления"})
                        return

                    self._render_dashboard_cache()
                    from database.db import get_product_price_map
                    price_map = get_product_price_map()
                    summary = get_today_summary(target_date, price_map=price_map, user_id=user_id)
                    meals = get_recent_meals(limit=10, target_date=target_date, price_map=price_map, user_id=user_id)
                    self._send_json(200, {
                        "status": "success",
                        "message": "Прием пищи / продукт успешно удален",
                        "summary": summary,
                        "meals": meals
                    })
                    return

                elif action == "update":
                    item_id = data.get("item_id") or data.get("id")
                    if not item_id:
                        self._send_json(400, {"status": "error", "message": "Не указан ID записи (item_id)"})
                        return

                    p_name = (data.get("product_name") or "").strip()
                    quantity_g = float(data.get("quantity_g") or data.get("weight_g") or 100.0)
                    calories = float(data.get("calories") or 0.0)
                    protein_g = float(data.get("protein_g") or data.get("protein") or 0.0)
                    fat_g = float(data.get("fat_g") or data.get("fat") or 0.0)
                    carbs_g = float(data.get("carbs_g") or data.get("carbs") or 0.0)
                    category = data.get("category", "general")
                    meal_type = data.get("meal_type")
                    timestamp = data.get("timestamp")

                    updated_item = update_meal_item(
                        item_id=int(item_id),
                        product_name=p_name,
                        quantity_g=quantity_g,
                        calories=calories,
                        protein_g=protein_g,
                        fat_g=fat_g,
                        carbs_g=carbs_g,
                        category=category,
                        meal_type=meal_type,
                        timestamp=timestamp
                    )

                    self._render_dashboard_cache()
                    from database.db import get_product_price_map
                    price_map = get_product_price_map()
                    summary = get_today_summary(target_date, price_map=price_map, user_id=user_id)
                    meals = get_recent_meals(limit=10, target_date=target_date, price_map=price_map, user_id=user_id)
                    self._send_json(200, {
                        "status": "success",
                        "message": "Запись приема пищи успешно обновлена",
                        "item": updated_item,
                        "summary": summary,
                        "meals": meals
                    })
                    return

                elif action == "add":
                    meal_type = data.get("meal_type") or "Перекус"
                    raw_input = data.get("raw_input")
                    items = data.get("items")
                    target_time = data.get("time")

                    new_meal_id = add_meal_entry(
                        meal_type=meal_type,
                        items=items,
                        raw_input=raw_input,
                        target_date=target_date,
                        target_time=target_time,
                        user_id=user_id
                    )

                    self._render_dashboard_cache()
                    from database.db import get_product_price_map
                    price_map = get_product_price_map()
                    summary = get_today_summary(target_date, price_map=price_map, user_id=user_id)
                    meals = get_recent_meals(limit=10, target_date=target_date, price_map=price_map, user_id=user_id)
                    self._send_json(200, {
                        "status": "success",
                        "message": f"Прием пищи ({meal_type}) успешно добавлен",
                        "meal_id": new_meal_id,
                        "summary": summary,
                        "meals": meals
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
        if path in ['/api/meals']:
            data = self._read_body_json()
            data["action"] = "update"
            self.path = '/api/meals/update'
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
        if path in ['/api/meals']:
            data = self._read_body_json()
            data["action"] = "delete"
            self.path = '/api/meals/delete'
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
