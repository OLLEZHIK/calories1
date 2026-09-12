import sqlite3
import json
import urllib.request
import urllib.error
import urllib.parse
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from config import DB_PATH, SUPABASE_URL, SUPABASE_KEY, USE_SUPABASE, DEFAULT_GOALS
from pathlib import Path

def supabase_request(
    endpoint: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    prefer: str = "return=representation",
) -> Any:
    """Executes HTTPS REST request to Supabase Database API."""
    if not USE_SUPABASE or not SUPABASE_URL or not SUPABASE_KEY:
        return None

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{endpoint}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": prefer,
    }

    body_bytes = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            resp_text = resp.read().decode("utf-8")
            return json.loads(resp_text) if resp_text else []
    except Exception as e:
        # Avoid leaking request details or failing on a non-UTF-8 Windows console.
        print(f"Supabase API request failed: {type(e).__name__}")
        return None

def get_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    schema_file = Path(__file__).parent / "schema.sql"
    with open(schema_file, "r", encoding="utf-8") as f:
        sql_script = f.read()
    
    with get_connection() as conn:
        conn.executescript(sql_script)
        conn.commit()
        
        # Safely add new columns if they don't exist
        try:
            conn.execute("ALTER TABLE user_goals ADD COLUMN weight_current REAL DEFAULT 80.0")
            conn.execute("ALTER TABLE user_goals ADD COLUMN weight_goal REAL DEFAULT 75.0")
            conn.commit()
        except sqlite3.OperationalError:
            pass # Column already exists


def save_custom_product(product_name: str, cal_100: float, p_100: float, f_100: float, c_100: float):
    product_name = product_name.lower().strip()
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO custom_products (product_name, calories_100g, protein_100g, fat_100g, carbs_100g)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(product_name) DO UPDATE SET
                calories_100g = excluded.calories_100g,
                protein_100g = excluded.protein_100g,
                fat_100g = excluded.fat_100g,
                carbs_100g = excluded.carbs_100g,
                updated_at = CURRENT_TIMESTAMP
        ''', (product_name, cal_100, p_100, f_100, c_100))
        conn.commit()
        
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase_request("custom_products?on_conflict=product_name", method="POST", data={
                "product_name": product_name,
                "calories_100g": cal_100,
                "protein_100g": p_100,
                "fat_100g": f_100,
                "carbs_100g": c_100
            }, prefer="resolution=merge-duplicates,return=representation")
        except Exception as e:
            print(f"Supabase custom_product error: {e}")

def get_custom_product(product_name: str) -> Optional[Dict[str, float]]:
    product_name = product_name.lower().strip()
    # First check local
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT * FROM custom_products WHERE product_name LIKE ?", (f"%{product_name}%",)).fetchone()
        if row:
            return {
                "calories": float(row["calories_100g"]),
                "protein": float(row["protein_100g"]),
                "fat": float(row["fat_100g"]),
                "carbs": float(row["carbs_100g"]),
                "category": "custom"
            }
            
    # Then check Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_res = supabase_request(f"custom_products?product_name=ilike.*{urllib.parse.quote(product_name)}*&limit=1")
            if sp_res and isinstance(sp_res, list) and len(sp_res) > 0:
                row = sp_res[0]
                return {
                    "calories": float(row.get("calories_100g", 0)),
                    "protein": float(row.get("protein_100g", 0)),
                    "fat": float(row.get("fat_100g", 0)),
                    "carbs": float(row.get("carbs_100g", 0)),
                    "category": "custom"
                }
        except Exception:
            pass
            
    return None


def set_bot_session_mode(chat_id: int, mode: Optional[str]) -> None:
    """Persist the one-message Telegram interaction mode across Vercel cold starts."""
    chat_id = str(chat_id)
    with get_connection() as conn:
        if mode:
            conn.execute(
                "INSERT INTO bot_sessions (chat_id, mode) VALUES (?, ?) "
                "ON CONFLICT(chat_id) DO UPDATE SET mode = excluded.mode, updated_at = CURRENT_TIMESTAMP",
                (chat_id, mode),
            )
        else:
            conn.execute("DELETE FROM bot_sessions WHERE chat_id = ?", (chat_id,))
        conn.commit()

    if SUPABASE_URL and SUPABASE_KEY:
        encoded_id = urllib.parse.quote(chat_id, safe="")
        try:
            if mode:
                supabase_request(
                    "bot_sessions?on_conflict=chat_id",
                    method="POST",
                    data={"chat_id": chat_id, "mode": mode},
                    prefer="resolution=merge-duplicates,return=representation",
                )
            else:
                supabase_request(f"bot_sessions?chat_id=eq.{encoded_id}", method="DELETE")
        except Exception as exc:
            print(f"Supabase bot session sync warning: {exc}")


def get_bot_session_mode(chat_id: int) -> Optional[str]:
    """Return a persisted Telegram mode, preferring Supabase in serverless deployments."""
    chat_id = str(chat_id)
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            encoded_id = urllib.parse.quote(chat_id, safe="")
            result = supabase_request(f"bot_sessions?chat_id=eq.{encoded_id}&select=mode&limit=1")
            if result and isinstance(result, list):
                return result[0].get("mode")
        except Exception as exc:
            print(f"Supabase bot session read warning: {exc}")

    with get_connection() as conn:
        row = conn.execute("SELECT mode FROM bot_sessions WHERE chat_id = ?", (chat_id,)).fetchone()
    return row["mode"] if row else None

def save_meal(raw_input: str, input_type: str, items: List[Dict[str, Any]], meal_type: str = "Прием пищи") -> int:
    """
    Saves a raw meal log and its parsed/calculated items into SQLite and Supabase Cloud DB.
    """
    meal_id = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO meals (raw_input, input_type, notes) VALUES (?, ?, ?)",
            (raw_input, input_type, meal_type)
        )
        meal_id = cursor.lastrowid

        for item in items:
            cursor.execute(
                """
                INSERT INTO meal_items (meal_id, product_name, category, quantity_g, calories, protein_g, fat_g, carbs_g)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    meal_id,
                    item.get("product_name", "Unknown"),
                    item.get("category", "general"),
                    float(item.get("quantity_g", 0)),
                    float(item.get("calories", 0)),
                    float(item.get("protein_g", 0)),
                    float(item.get("fat_g", 0)),
                    float(item.get("carbs_g", 0))
                )
            )
        conn.commit()

    # Sync to Supabase Cloud DB for persistent Vercel state
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_meal = supabase_request("meals", method="POST", data={
                "raw_input": raw_input,
                "input_type": input_type,
                "notes": meal_type
            })
            if sp_meal and isinstance(sp_meal, list) and len(sp_meal) > 0:
                sp_id = sp_meal[0].get("id")
                for item in items:
                    supabase_request("meal_items", method="POST", data={
                        "meal_id": sp_id,
                        "product_name": item.get("product_name", "Unknown"),
                        "category": item.get("category", "general"),
                        "quantity_g": float(item.get("quantity_g", 0)),
                        "calories": float(item.get("calories", 0)),
                        "protein_g": float(item.get("protein_g", 0)),
                        "fat_g": float(item.get("fat_g", 0)),
                        "carbs_g": float(item.get("carbs_g", 0))
                    })
        except Exception as e:
            print(f"Supabase Meal Sync warning: {e}")

    return meal_id

def get_today_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    if not target_date:
        target_date = date.today().isoformat()

    # Query Supabase Cloud DB if configured
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            # Use next-day boundary for reliable range filtering in PostgREST
            next_date = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
            sp_meals = supabase_request(
                f"meals?select=*,meal_items(*)&created_at=gte.{target_date}&created_at=lt.{next_date}"
            )
            if sp_meals is not None and isinstance(sp_meals, list):
                tot_cal = 0.0
                tot_p = 0.0
                tot_f = 0.0
                tot_c = 0.0
                active_cal = 0.0

                for m in sp_meals:
                    is_active = m.get("notes") == "Активность"
                    for mi in m.get("meal_items", []):
                        cal = float(mi.get("calories", 0))
                        tot_cal += cal
                        tot_p += float(mi.get("protein_g", 0))
                        tot_f += float(mi.get("fat_g", 0))
                        tot_c += float(mi.get("carbs_g", 0))
                        if is_active:
                            active_cal += abs(cal)

                # Pull real user goals (incl. weight tracking) from Supabase instead of
                # always returning the hardcoded defaults.
                goals = dict(DEFAULT_GOALS)
                goals.setdefault("weight_current", None)
                goals.setdefault("weight_goal", None)
                try:
                    sp_goals = supabase_request("user_goals?select=*&order=id.desc&limit=1")
                    if sp_goals and isinstance(sp_goals, list) and len(sp_goals) > 0:
                        g = sp_goals[0]
                        goals = {
                            "calories": g.get("calories", DEFAULT_GOALS["calories"]),
                            "protein_g": g.get("protein_g", DEFAULT_GOALS["protein_g"]),
                            "fat_g": g.get("fat_g", DEFAULT_GOALS["fat_g"]),
                            "carbs_g": g.get("carbs_g", DEFAULT_GOALS["carbs_g"]),
                            "weight_current": g.get("weight_current"),
                            "weight_goal": g.get("weight_goal"),
                        }
                except Exception as e:
                    print(f"Supabase goals fetch error: {e}")

                return {
                    "date": target_date,
                    "total_calories": round(tot_cal, 1),
                    "total_protein": round(tot_p, 1),
                    "total_fat": round(tot_f, 1),
                    "total_carbs": round(tot_c, 1),
                    "active_calories": round(active_cal),
                    "goals": goals
                }
        except Exception as e:
            print(f"Supabase summary error: {e}")

    with get_connection() as conn:
        cursor = conn.cursor()
        query = """
            SELECT 
                COALESCE(SUM(mi.calories), 0) as total_calories,
                COALESCE(SUM(mi.protein_g), 0) as total_protein,
                COALESCE(SUM(mi.fat_g), 0) as total_fat,
                COALESCE(SUM(mi.carbs_g), 0) as total_carbs
            FROM meals m
            JOIN meal_items mi ON m.id = mi.meal_id
            WHERE DATE(m.timestamp) = DATE(?)
        """
        row = cursor.execute(query, (target_date,)).fetchone()

        goals_row = cursor.execute("SELECT * FROM user_goals ORDER BY id DESC LIMIT 1").fetchone()
        goals = {
            "calories": goals_row["calories"] if goals_row else 2200,
            "protein_g": goals_row["protein_g"] if goals_row else 160,
            "fat_g": goals_row["fat_g"] if goals_row else 70,
            "carbs_g": goals_row["carbs_g"] if goals_row else 230,
            "weight_current": goals_row["weight_current"] if (goals_row and "weight_current" in goals_row.keys()) else 80.0,
            "weight_goal": goals_row["weight_goal"] if (goals_row and "weight_goal" in goals_row.keys()) else 75.0,
        }

        # Calculate active calories (where notes = 'Активность' or similar)
        active_row = cursor.execute("""
            SELECT COALESCE(SUM(ABS(mi.calories)), 0) as active_cal
            FROM meals m
            JOIN meal_items mi ON m.id = mi.meal_id
            WHERE DATE(m.timestamp) = DATE(?) AND m.notes = 'Активность'
        """, (target_date,)).fetchone()
        active_calories = round(active_row["active_cal"]) if active_row else 0

        # Adjust total_calories if it includes negative active calories (we already added them as negative to the DB to subtract from daily balance)
        # But we still want to expose active_calories as a separate metric.

        return {
            "date": target_date,
            "total_calories": round(row["total_calories"], 1),
            "total_protein": round(row["total_protein"], 1),
            "total_fat": round(row["total_fat"], 1),
            "total_carbs": round(row["total_carbs"], 1),
            "active_calories": active_calories,
            "goals": goals
        }

def get_recent_meals(limit: int = 10, target_date: str = None) -> List[Dict[str, Any]]:
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            url = f"meals?select=*,meal_items(*)&order=created_at.desc&limit={limit}"
            if target_date:
                url += f"&created_at=gte.{target_date}T00:00:00&created_at=lte.{target_date}T23:59:59"
            sp_meals = supabase_request(url)
            if sp_meals and isinstance(sp_meals, list) and len(sp_meals) > 0:
                result = []
                for m in sp_meals:
                    items = m.get("meal_items", [])
                    result.append({
                        "id": m.get("id"),
                        "timestamp": (m.get("created_at") or "")[:16].replace("T", " "),
                        "raw_input": m.get("raw_input"),
                        "input_type": m.get("input_type"),
                        "meal_type": m.get("notes") or "Прием пищи",
                        "items": items,
                        "total_calories": int(round(sum(float(i.get("calories", 0)) for i in items))),
                        "total_protein": int(round(sum(float(i.get("protein_g", 0)) for i in items))),
                        "total_fat": int(round(sum(float(i.get("fat_g", 0)) for i in items))),
                        "total_carbs": int(round(sum(float(i.get("carbs_g", 0)) for i in items))),
                    })
                return result
        except Exception as e:
            print(f"Supabase recent meals warning: {e}")

    with get_connection() as conn:
        cursor = conn.cursor()
        if target_date:
            meals_rows = cursor.execute(
                "SELECT * FROM meals WHERE DATE(timestamp) = DATE(?) ORDER BY timestamp DESC LIMIT ?", (target_date, limit)
            ).fetchall()
        else:
            meals_rows = cursor.execute(
                "SELECT * FROM meals ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()

        result = []
        for m in meals_rows:
            items_rows = cursor.execute(
                "SELECT * FROM meal_items WHERE meal_id = ?", (m["id"],)
            ).fetchall()
            items = [dict(item) for item in items_rows]

            result.append({
                "id": m["id"],
                "timestamp": m["timestamp"],
                "raw_input": m["raw_input"],
                "input_type": m["input_type"],
                "meal_type": m["notes"] if m["notes"] else "Прием пищи",
                "items": items,
                "total_calories": int(round(sum(i["calories"] for i in items))),
                "total_protein": int(round(sum(i["protein_g"] for i in items))),
                "total_fat": int(round(sum(i["fat_g"] for i in items))),
                "total_carbs": int(round(sum(i["carbs_g"] for i in items))),
            })
        return result

def get_meals_for_days(days: int = 3) -> List[Dict[str, Any]]:
    target_date = (date.today() - timedelta(days=days)).isoformat()
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_meals = supabase_request(f"meals?select=*,meal_items(*)&created_at=gte.{target_date}&order=created_at.desc")
            if sp_meals and isinstance(sp_meals, list) and len(sp_meals) > 0:
                result = []
                for m in sp_meals:
                    items = m.get("meal_items", [])
                    result.append({
                        "id": m.get("id"),
                        "timestamp": (m.get("created_at") or "")[:16].replace("T", " "),
                        "raw_input": m.get("raw_input"),
                        "input_type": m.get("input_type"),
                        "meal_type": m.get("notes") or "Прием пищи",
                        "items": items,
                        "total_calories": int(round(sum(float(i.get("calories", 0)) for i in items))),
                        "total_protein": int(round(sum(float(i.get("protein_g", 0)) for i in items))),
                        "total_fat": int(round(sum(float(i.get("fat_g", 0)) for i in items))),
                        "total_carbs": int(round(sum(float(i.get("carbs_g", 0)) for i in items))),
                    })
                return result
        except Exception as e:
            print(f"Supabase historical meals warning: {e}")

    with get_connection() as conn:
        cursor = conn.cursor()
        meals_rows = cursor.execute(
            "SELECT * FROM meals WHERE timestamp >= ? ORDER BY timestamp DESC", (target_date,)
        ).fetchall()

        result = []
        for m in meals_rows:
            items_rows = cursor.execute(
                "SELECT * FROM meal_items WHERE meal_id = ?", (m["id"],)
            ).fetchall()
            items = [dict(item) for item in items_rows]

            result.append({
                "id": m["id"],
                "timestamp": m["timestamp"],
                "raw_input": m["raw_input"],
                "input_type": m["input_type"],
                "meal_type": m["notes"] if m["notes"] else "Прием пищи",
                "items": items,
                "total_calories": int(round(sum(i["calories"] for i in items))),
                "total_protein": int(round(sum(i["protein_g"] for i in items))),
                "total_fat": int(round(sum(i["fat_g"] for i in items))),
                "total_carbs": int(round(sum(i["carbs_g"] for i in items))),
            })
        return result

def save_product_price(product_name: str, price_rub: float, weight_g: float, category: str = "general",
                       protein_100g: float = 0, fat_100g: float = 0, carbs_100g: float = 0, calories_100g: float = 0):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            INSERT INTO product_prices 
            (product_name, category, price_rub, weight_g, protein_per_100g, fat_per_100g, carbs_per_100g, calories_per_100g)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_name) DO UPDATE SET
                price_rub = excluded.price_rub,
                weight_g = excluded.weight_g,
                category = excluded.category,
                updated_at = CURRENT_TIMESTAMP
            """,
            (product_name, category, price_rub, weight_g, protein_100g, fat_100g, carbs_100g, calories_100g)
        )
        conn.commit()

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase_request("product_prices", method="POST", data={
                "product_name": product_name,
                "category": category,
                "price_rub": price_rub,
                "weight_g": weight_g,
                "protein_per_100g": protein_100g,
                "fat_per_100g": fat_100g,
                "carbs_per_100g": carbs_100g,
                "calories_per_100g": calories_100g
            })
        except Exception as e:
            print(f"Supabase price sync warning: {e}")

def get_product_prices() -> List[Dict[str, Any]]:
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_products = supabase_request("product_prices?select=*&order=product_name.asc")
            if sp_products and isinstance(sp_products, list) and len(sp_products) > 0:
                result = []
                for d in sp_products:
                    p = float(d.get("protein_per_100g", 0))
                    f = float(d.get("fat_per_100g", 0))
                    c = float(d.get("carbs_per_100g", 0))
                    cal = float(d.get("calories_per_100g", 0))

                    protein_ratio = (p * 4.0) / cal if cal > 0 else 0.1
                    score = round(min(10.0, max(1.0, (protein_ratio * 12.0) + 3.0)), 1)
                    badge_class = "good" if score >= 7.5 else ("warn" if score >= 5.0 else "crit")
                    label = "Высокий" if score >= 7.5 else ("Средний" if score >= 5.0 else "Низкий")

                    d["calories_per_100g"] = int(round(cal))
                    d["protein_per_100g"] = int(round(p))
                    d["fat_per_100g"] = int(round(f))
                    d["carbs_per_100g"] = int(round(c))
                    d["efficiency_score"] = score
                    d["efficiency_label"] = label
                    d["badge_class"] = badge_class
                    result.append(d)
                return result
        except Exception as e:
            print(f"Supabase product prices warning: {e}")
    with get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT * FROM product_prices ORDER BY product_name").fetchall()
        result = []
        for r in rows:
            d = dict(r)
            p = float(d.get("protein_per_100g", 0))
            f = float(d.get("fat_per_100g", 0))
            c = float(d.get("carbs_per_100g", 0))
            cal = float(d.get("calories_per_100g", 0))

            # Compute Nutrition Efficiency Index (1.0 to 10.0 scale)
            protein_ratio = (p * 4.0) / cal if cal > 0 else 0.1
            score = round(min(10.0, max(1.0, (protein_ratio * 12.0) + 3.0)), 1)
            
            badge_class = "good" if score >= 7.5 else ("warn" if score >= 5.0 else "crit")
            label = "Высокий" if score >= 7.5 else ("Средний" if score >= 5.0 else "Низкий")

            d["calories_per_100g"] = int(round(cal))
            d["protein_per_100g"] = int(round(p))
            d["fat_per_100g"] = int(round(f))
            d["carbs_per_100g"] = int(round(c))
            d["efficiency_score"] = score
            d["efficiency_label"] = label
            d["badge_class"] = badge_class
            result.append(d)
        return result

def save_coach_recommendation(topic: str, recommendation: str, severity: str = "info"):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO coach_recommendations (topic, recommendation, severity) VALUES (?, ?, ?)",
            (topic, recommendation, severity)
        )
        conn.commit()

def get_recent_recommendations(limit: int = 5) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute(
            "SELECT * FROM coach_recommendations ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]

# Initialize DB safely when module loaded
try:
    init_db()
except Exception as _db_err:
    print(f"Warning: SQLite init failed ({_db_err}). Proceeding with cloud/fallback DB.")

