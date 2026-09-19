import sqlite3
import json
import re
import time
import urllib.request
import urllib.error
import urllib.parse
from difflib import SequenceMatcher
from typing import List, Dict, Any, Optional
from datetime import datetime, date, timedelta
from config import DB_PATH, SUPABASE_URL, SUPABASE_KEY, USE_SUPABASE, DEFAULT_GOALS
from pathlib import Path

_MEM_CACHE: Dict[str, Dict[str, Any]] = {}

def cache_get(key: str, ttl: float = 60.0) -> Any:
    """Returns cached value if within TTL, else None."""
    entry = _MEM_CACHE.get(key)
    if entry and (time.time() - entry["ts"]) < ttl:
        return entry["val"]
    return None

def cache_set(key: str, val: Any) -> None:
    """Stores value in memory with current timestamp."""
    _MEM_CACHE[key] = {"val": val, "ts": time.time()}

def cache_invalidate(*keys: str) -> None:
    """Evicts keys from memory cache. If no keys given, clears entire cache."""
    if not keys:
        _MEM_CACHE.clear()
    else:
        for k in keys:
            _MEM_CACHE.pop(k, None)


def supabase_request(
    endpoint: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    prefer: str = "return=representation",
) -> Any:
    """Executes HTTPS REST request to Supabase Database API."""
    if not USE_SUPABASE or not SUPABASE_URL or not SUPABASE_KEY:
        return None

    quoted_endpoint = urllib.parse.quote(endpoint, safe="/?=&:*+,%")
    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{quoted_endpoint}"
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

        try:
            conn.execute("ALTER TABLE user_goals ADD COLUMN goal_mode TEXT DEFAULT 'loss_300'")
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS weight_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    weight REAL NOT NULL,
                    goal_mode TEXT,
                    notes TEXT
                )
            """)
            conn.commit()
        except sqlite3.OperationalError:
            pass

        try:
            conn.execute("ALTER TABLE product_prices ADD COLUMN coach_score INTEGER DEFAULT 0")
            conn.execute("ALTER TABLE product_prices ADD COLUMN coach_verdict TEXT DEFAULT ''")
            conn.commit()
        except sqlite3.OperationalError:
            pass


def stem_product_word(w: str) -> str:
    """Stem Russian food words by stripping adjective and plural/case endings."""
    w = w.strip().lower()
    if w.startswith("свин"):
        return "свин"
    if w.startswith("куриц") or w.startswith("курин") or (w.startswith("кур") and len(w) <= 6):
        return "кур"
    if w.startswith("говяд"):
        return "говяд"
    if w.startswith("индейк") or w.startswith("индей"):
        return "индей"
    w = re.sub(r'(?:ые|ие|ое|ее|ая|яя|ый|ий|ой|ых|их|ым|им|ую|юю)$', '', w)
    w = re.sub(r'(?:ами|ями|ов|ев|ей|ам|ям|ах|ях)$', '', w)
    w = re.sub(r'(?:цы|ки|лы|ры|сы|ты|ды|бы|пы|мы|ны|вы|зы)$', lambda m: m.group(0)[0], w)
    w = re.sub(r'(?:ца|ки|ка|ко|це|цо|це|о|е|а|я|ы|и)$', '', w)
    return w


def are_product_duplicates(name1: str, name2: str) -> bool:
    """
    Checks if two product names refer to the same food item:
    1. Exact lower-case match.
    2. Domain mapping (shashlik pork, svinina, svinina poluzhirnaya).
    3. Normalized token set match (ignoring word order and Russian plural/case inflections).
    4. High fuzzy string similarity (> 0.82).
    """
    n1 = name1.strip().lower()
    n2 = name2.strip().lower()
    if n1 == n2:
        return True

    # Domain canonical matching: pork dishes -> raw svinina
    is_pork1 = ("шашлык" in n1 and "свин" in n1) or (n1 in ["свинина", "свинина полужирная", "шашлык свиной"])
    is_pork2 = ("шашлык" in n2 and "свин" in n2) or (n2 in ["свинина", "свинина полужирная", "шашлык свиной"])
    if is_pork1 and is_pork2:
        return True

    toks1 = sorted([stem_product_word(t) for t in re.sub(r'[^\w\s%]', ' ', n1).split() if len(t) > 1])
    toks2 = sorted([stem_product_word(t) for t in re.sub(r'[^\w\s%]', ' ', n2).split() if len(t) > 1])
    if toks1 and toks2 and toks1 == toks2:
        return True

    if SequenceMatcher(None, n1, n2).ratio() > 0.82:
        return True

    return False


def validate_product_values(protein_100g: float, fat_100g: float, carbs_100g: float,
                            calories_100g: float, price_rub: float = 0.0, weight_g: float = 100.0,
                            coach_score: int = 0) -> Dict[str, Any]:
    """
    Sanitizes and enforces physical & nutritional constraints:
    - P, F, C >= 0.
    - P + F + C <= 100g per 100g (normalized if exceeded).
    - Calories = 4*P + 9*F + 4*C (aligned if <= 0 or > 20% deviation).
    - Calories clamped to max 900 kcal (pure fat).
    - Weight > 0 (defaults to 100g), price >= 0.
    - Coach score clamped to [1, 10] if set.
    """
    p = max(0.0, float(protein_100g or 0))
    f = max(0.0, float(fat_100g or 0))
    c = max(0.0, float(carbs_100g or 0))

    tot_m = p + f + c
    if tot_m > 100.0:
        ratio = 100.0 / tot_m
        p = round(p * ratio, 1)
        f = round(f * ratio, 1)
        c = round(c * ratio, 1)

    expected_cal = int(round((p * 4.0) + (f * 9.0) + (c * 4.0)))
    cal = float(calories_100g or 0)
    if cal <= 0 or (expected_cal > 0 and abs(cal - expected_cal) / max(1.0, cal) > 0.20):
        cal = expected_cal
    cal = min(900, max(0, int(round(cal))))

    w = max(1.0, float(weight_g or 100.0))
    pr = max(0.0, float(price_rub or 0.0))
    score = int(coach_score or 0)
    if score > 0:
        score = min(10, max(1, score))

    return {
        "protein_100g": p,
        "fat_100g": f,
        "carbs_100g": c,
        "calories_100g": cal,
        "price_rub": pr,
        "weight_g": w,
        "coach_score": score
    }


def save_custom_product(product_name: str, cal_100: float, p_100: float, f_100: float, c_100: float):
    product_name = product_name.lower().strip()
    val = validate_product_values(protein_100g=p_100, fat_100g=f_100, carbs_100g=c_100, calories_100g=cal_100)
    cal_100 = val["calories_100g"]
    p_100 = val["protein_100g"]
    f_100 = val["fat_100g"]
    c_100 = val["carbs_100g"]

    with get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT product_name FROM custom_products").fetchall()
        for r in rows:
            ex_name = r["product_name"]
            if ex_name != product_name and are_product_duplicates(ex_name, product_name):
                product_name = ex_name
                break

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

def save_meal(raw_input: str, input_type: str, items: List[Dict[str, Any]], meal_type: str = "Прием пищи", custom_timestamp: Optional[str] = None) -> int:
    """
    Saves a raw meal log and its parsed/calculated items into SQLite and Supabase Cloud DB.
    Supports explicit custom_timestamp (e.g. 'YYYY-MM-DD HH:MM:SS').
    """
    meal_id = 0
    with get_connection() as conn:
        cursor = conn.cursor()
        if custom_timestamp:
            cursor.execute(
                "INSERT INTO meals (raw_input, input_type, notes, timestamp) VALUES (?, ?, ?, ?)",
                (raw_input, input_type, meal_type, custom_timestamp)
            )
        else:
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
            meal_data = {
                "raw_input": raw_input,
                "input_type": input_type,
                "notes": meal_type
            }
            if custom_timestamp:
                meal_data["timestamp"] = custom_timestamp

            sp_meal = supabase_request("meals", method="POST", data=meal_data)
            if sp_meal and isinstance(sp_meal, list) and len(sp_meal) > 0:
                sp_id = sp_meal[0].get("id")
                if sp_id:
                    meal_id = sp_id
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

def calculate_nutrition_goals(weight_current: float, mode: str = "loss_300", weight_goal: Optional[float] = None) -> Dict[str, Any]:
    """
    Scientifically calculates daily calorie and macro (P/F/C) goals based on body weight and goal mode:
    Modes:
      - 'loss_200': -200g/week (-220 kcal/day deficit)
      - 'loss_300': -300g/week (-330 kcal/day deficit)
      - 'loss_400': -400g/week (-440 kcal/day deficit)
      - 'gain': muscle hypertrophy / 'качаться' (+250 kcal/day clean surplus, protein 2.1g/kg)

    Strictly satisfies physical energy equation: 4*P + 9*F + 4*C == final_calories!
    """
    w = max(30.0, min(300.0, float(weight_current)))
    valid_modes = ["loss_200", "loss_300", "loss_400", "gain"]
    if mode not in valid_modes:
        mode = "loss_300"

    tdee = round(w * 31.5)

    if mode == "loss_200":
        delta_kcal = -220
        p_per_kg = 2.0
        mode_title = "Снижение веса (-200г / неделю)"
    elif mode == "loss_300":
        delta_kcal = -330
        p_per_kg = 2.0
        mode_title = "Снижение веса (-300г / неделю)"
    elif mode == "loss_400":
        delta_kcal = -440
        p_per_kg = 2.0
        mode_title = "Снижение веса (-400г / неделю)"
    elif mode == "gain":
        delta_kcal = 250
        p_per_kg = 2.1
        mode_title = "Набор массы / Качаться (+250 ккал / день)"
    else:
        delta_kcal = -330
        p_per_kg = 2.0
        mode_title = "Снижение веса (-300г / неделю)"

    target_cal = max(1200, tdee + delta_kcal)
    p = int(round(w * p_per_kg))
    f = int(round(w * 0.9))
    carb_kcal = max(0, target_cal - (4 * p + 9 * f))
    c = int(round(carb_kcal / 4.0))

    # Re-sync target calories so 4P + 9F + 4C matches exactly
    final_cal = 4 * p + 9 * f + 4 * c

    return {
        "calories": final_cal,
        "protein_g": p,
        "fat_g": f,
        "carbs_g": c,
        "weight_current": round(w, 1),
        "weight_goal": round(float(weight_goal), 1) if weight_goal else None,
        "goal_mode": mode,
        "goal_title": mode_title,
        "tdee": tdee,
        "delta_kcal": delta_kcal,
        "energy_check": f"4×{p} + 9×{f} + 4×{c} = {final_cal} ккал"
    }

def get_user_goals() -> Dict[str, Any]:
    """Returns the user's active goals, current weight, and goal mode (cached 60s)."""
    cached = cache_get("user_goals", ttl=60.0)
    if cached is not None:
        return cached

    weight_current = 76.0
    weight_goal = 67.0
    goal_mode = "loss_300"

    # Try local sqlite first
    try:
        with get_connection() as conn:
            row = conn.execute("SELECT * FROM user_goals ORDER BY id DESC LIMIT 1").fetchone()
            if row:
                keys = row.keys()
                if "weight_current" in keys and row["weight_current"] is not None:
                    weight_current = float(row["weight_current"])
                if "weight_goal" in keys and row["weight_goal"] is not None:
                    weight_goal = float(row["weight_goal"])
                if "goal_mode" in keys and row["goal_mode"]:
                    goal_mode = str(row["goal_mode"])
    except Exception as e:
        print(f"Local user_goals read error: {e}")

    # Check Supabase if active
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_goals = supabase_request("user_goals?select=*&order=id.desc&limit=1")
            if sp_goals and isinstance(sp_goals, list) and len(sp_goals) > 0:
                g = sp_goals[0]
                if g.get("weight_current") is not None:
                    weight_current = float(g["weight_current"])
                if g.get("weight_goal") is not None:
                    weight_goal = float(g["weight_goal"])
            sp_mode = supabase_request("bot_sessions?chat_id=eq.goal_mode")
            if sp_mode and isinstance(sp_mode, list) and len(sp_mode) > 0:
                m = sp_mode[0].get("mode")
                if m in ["loss_200", "loss_300", "loss_400", "gain"]:
                    goal_mode = m
        except Exception as e:
            print(f"Supabase user_goals read error: {e}")

    goals = calculate_nutrition_goals(weight_current, mode=goal_mode, weight_goal=weight_goal)
    cache_set("user_goals", goals)
    return goals

def save_user_weight_and_goals(weight_current: float, mode: Optional[str] = None, weight_goal: Optional[float] = None) -> Dict[str, Any]:
    """
    Saves user weight and calculates/persists corresponding daily calorie and macro goals.
    Persists to SQLite (user_goals + weight_log) and Supabase Cloud DB.
    """
    current_g = get_user_goals()
    if not mode:
        mode = current_g.get("goal_mode", "loss_300")
    if weight_goal is None:
        weight_goal = current_g.get("weight_goal")

    goals = calculate_nutrition_goals(weight_current, mode=mode, weight_goal=weight_goal)

    # 1. Save to SQLite
    try:
        with get_connection() as conn:
            existing = conn.execute("SELECT id FROM user_goals LIMIT 1").fetchone()
            if existing:
                conn.execute("""
                    UPDATE user_goals SET 
                        calories = ?, protein_g = ?, fat_g = ?, carbs_g = ?,
                        weight_current = ?, weight_goal = ?, goal_mode = ?
                    WHERE id = ?
                """, (
                    goals["calories"], goals["protein_g"], goals["fat_g"], goals["carbs_g"],
                    goals["weight_current"], goals["weight_goal"], goals["goal_mode"], existing["id"]
                ))
            else:
                conn.execute("""
                    INSERT INTO user_goals (calories, protein_g, fat_g, carbs_g, weight_current, weight_goal, goal_mode)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    goals["calories"], goals["protein_g"], goals["fat_g"], goals["carbs_g"],
                    goals["weight_current"], goals["weight_goal"], goals["goal_mode"]
                ))

            conn.execute("""
                INSERT INTO weight_log (weight, goal_mode, notes)
                VALUES (?, ?, ?)
            """, (goals["weight_current"], goals["goal_mode"], f"Target: {goals['calories']} kcal"))
            conn.commit()
    except Exception as e:
        print(f"SQLite save_user_weight_and_goals error: {e}")

    # 2. Save to Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase_request(
                "user_goals?id=eq.1",
                method="PATCH",
                data={
                    "calories": goals["calories"],
                    "protein_g": goals["protein_g"],
                    "fat_g": goals["fat_g"],
                    "carbs_g": goals["carbs_g"],
                    "weight_current": goals["weight_current"],
                    "weight_goal": goals["weight_goal"],
                    "goal_mode": goals["goal_mode"],
                }
            )
            supabase_request(
                "bot_sessions?on_conflict=chat_id",
                method="POST",
                data={"chat_id": "goal_mode", "mode": goals["goal_mode"]},
                prefer="resolution=merge-duplicates,return=representation"
            )
        except Exception as e:
            print(f"Supabase save_user_weight_and_goals error: {e}")

    # Update dashboard HTML
    try:
        from agents.dashboard_agent import dashboard_agent
        dashboard_agent.render()
    except Exception:
        pass

    cache_invalidate("user_goals")
    return goals

def get_today_summary(target_date: Optional[str] = None, price_map: Optional[Dict[str, float]] = None, goals: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not target_date:
        target_date = date.today().isoformat()
    if price_map is None:
        price_map = get_product_price_map()
    if goals is None:
        goals = get_user_goals()

    # Query Supabase Cloud DB if configured
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            # Use next-day boundary for reliable range filtering in PostgREST
            next_date = (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()
            sp_meals = supabase_request(
                f"meals?select=*,meal_items(*)&timestamp=gte.{target_date}&timestamp=lt.{next_date}"
            )
            if sp_meals is not None and isinstance(sp_meals, list):
                tot_cal = 0.0
                tot_p = 0.0
                tot_f = 0.0
                tot_c = 0.0
                active_cal = 0.0
                tot_cost = 0.0
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
                        else:
                            q = float(mi.get("quantity_g", 0))
                            pn = mi.get("product_name", "")
                            pr100 = find_item_price_per_100g(pn, price_map)
                            if pr100 is not None and q > 0:
                                tot_cost += (q / 100.0) * pr100

                return {
                    "date": target_date,
                    "total_calories": round(tot_cal, 1),
                    "total_protein": round(tot_p, 1),
                    "total_fat": round(tot_f, 1),
                    "total_carbs": round(tot_c, 1),
                    "active_calories": round(active_cal),
                    "total_cost_eur": round(tot_cost, 2),
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

        if goals is None:
            goals = get_user_goals()

        # Calculate active calories (where notes = 'Активность' or similar)
        active_row = cursor.execute("""
            SELECT COALESCE(SUM(ABS(mi.calories)), 0) as active_cal
            FROM meals m
            JOIN meal_items mi ON m.id = mi.meal_id
            WHERE DATE(m.timestamp) = DATE(?) AND m.notes = 'Активность'
        """, (target_date,)).fetchone()
        active_calories = round(active_row["active_cal"]) if active_row else 0

        # Calculate total cost for local sqlite meals
        tot_cost = 0.0
        if price_map is None:
            price_map = get_product_price_map()
        items_today = cursor.execute("""
            SELECT mi.product_name, mi.quantity_g 
            FROM meals m
            JOIN meal_items mi ON m.id = mi.meal_id
            WHERE DATE(m.timestamp) = DATE(?) AND m.notes != 'Активность'
        """, (target_date,)).fetchall()
        for it in items_today:
            q = float(it["quantity_g"] or 0)
            pn = it["product_name"] or ""
            pr100 = find_item_price_per_100g(pn, price_map)
            if pr100 is not None and q > 0:
                tot_cost += (q / 100.0) * pr100

        return {
            "date": target_date,
            "total_calories": round(row["total_calories"], 1),
            "total_protein": round(row["total_protein"], 1),
            "total_fat": round(row["total_fat"], 1),
            "total_carbs": round(row["total_carbs"], 1),
            "active_calories": active_calories,
            "total_cost_eur": round(tot_cost, 2),
            "goals": goals
        }

def get_recent_meals(limit: int = 10, target_date: str = None, price_map: Optional[Dict[str, float]] = None) -> List[Dict[str, Any]]:
    if price_map is None:
        price_map = get_product_price_map()
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            url = f"meals?select=*,meal_items(*)&order=timestamp.desc&limit={limit}"
            if target_date:
                url += f"&timestamp=gte.{target_date}T00:00:00&timestamp=lte.{target_date}T23:59:59"
            sp_meals = supabase_request(url)
            if sp_meals and isinstance(sp_meals, list) and len(sp_meals) > 0:
                result = []
                for m in sp_meals:
                    items = m.get("meal_items", [])
                    enriched_items = []
                    meal_cost = 0.0
                    for i in items:
                        item_dict = dict(i)
                        q = float(item_dict.get("quantity_g", 0))
                        p_name = item_dict.get("product_name", "")
                        pr100 = find_item_price_per_100g(p_name, price_map)
                        cost = round((q / 100.0) * pr100, 2) if (pr100 is not None and q > 0) else 0.0
                        item_dict["price_per_100g"] = pr100
                        item_dict["cost_eur"] = cost
                        meal_cost += cost
                        enriched_items.append(item_dict)

                    result.append({
                        "id": m.get("id"),
                        "timestamp": (m.get("timestamp") or m.get("created_at") or "")[:16].replace("T", " "),
                        "raw_input": m.get("raw_input"),
                        "input_type": m.get("input_type"),
                        "meal_type": m.get("notes") or "Прием пищи",
                        "items": enriched_items,
                        "total_calories": int(round(sum(float(i.get("calories", 0)) for i in items))),
                        "total_protein": int(round(sum(float(i.get("protein_g", 0)) for i in items))),
                        "total_fat": int(round(sum(float(i.get("fat_g", 0)) for i in items))),
                        "total_carbs": int(round(sum(float(i.get("carbs_g", 0)) for i in items))),
                        "total_cost_eur": round(meal_cost, 2),
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
            enriched_items = []
            meal_cost = 0.0
            for i in items:
                q = float(i.get("quantity_g", 0))
                p_name = i.get("product_name", "")
                pr100 = find_item_price_per_100g(p_name, price_map)
                cost = round((q / 100.0) * pr100, 2) if (pr100 is not None and q > 0) else 0.0
                i["price_per_100g"] = pr100
                i["cost_eur"] = cost
                meal_cost += cost
                enriched_items.append(i)

            result.append({
                "id": m["id"],
                "timestamp": m["timestamp"],
                "raw_input": m["raw_input"],
                "input_type": m["input_type"],
                "meal_type": m["notes"] if m["notes"] else "Прием пищи",
                "items": enriched_items,
                "total_calories": int(round(sum(i["calories"] for i in items))),
                "total_protein": int(round(sum(i["protein_g"] for i in items))),
                "total_fat": int(round(sum(i["fat_g"] for i in items))),
                "total_carbs": int(round(sum(i["carbs_g"] for i in items))),
                "total_cost_eur": round(meal_cost, 2),
            })
        return result

def get_meals_for_days(days: int = 3) -> List[Dict[str, Any]]:
    target_date = (date.today() - timedelta(days=days)).isoformat()
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_meals = supabase_request(f"meals?select=*,meal_items(*)&timestamp=gte.{target_date}&order=timestamp.desc")
            if sp_meals and isinstance(sp_meals, list) and len(sp_meals) > 0:
                result = []
                for m in sp_meals:
                    items = m.get("meal_items", [])
                    result.append({
                        "id": m.get("id"),
                        "timestamp": (m.get("timestamp") or m.get("created_at") or "")[:16].replace("T", " "),
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

def delete_meal(meal_id: int) -> bool:
    """Deletes a meal and its associated items by meal_id from SQLite and Supabase."""
    with get_connection() as conn:
        conn.execute("DELETE FROM meal_items WHERE meal_id = ?", (meal_id,))
        conn.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
        conn.commit()

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase_request(f"meal_items?meal_id=eq.{meal_id}", method="DELETE")
            supabase_request(f"meals?id=eq.{meal_id}", method="DELETE")
        except Exception as e:
            print(f"Supabase delete meal warning: {e}")

    return True

def delete_meal_item(item_id: int) -> bool:
    """
    Deletes a single meal_item by item_id from SQLite and Supabase.
    If no items remain in the parent meal, deletes the parent meal record too.
    """
    meal_id = None
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT meal_id FROM meal_items WHERE id = ?", (item_id,)).fetchone()
        if row:
            meal_id = row["meal_id"]
        cursor.execute("DELETE FROM meal_items WHERE id = ?", (item_id,))
        conn.commit()

        if meal_id:
            rem = cursor.execute("SELECT COUNT(*) as cnt FROM meal_items WHERE meal_id = ?", (meal_id,)).fetchone()
            if rem and rem["cnt"] == 0:
                cursor.execute("DELETE FROM meals WHERE id = ?", (meal_id,))
                conn.commit()

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_item = supabase_request(f"meal_items?id=eq.{item_id}&select=meal_id")
            sp_meal_id = sp_item[0].get("meal_id") if (sp_item and isinstance(sp_item, list) and len(sp_item) > 0) else None

            supabase_request(f"meal_items?id=eq.{item_id}", method="DELETE")
            if sp_meal_id:
                rem_sp = supabase_request(f"meal_items?meal_id=eq.{sp_meal_id}&select=id")
                if isinstance(rem_sp, list) and len(rem_sp) == 0:
                    supabase_request(f"meals?id=eq.{sp_meal_id}", method="DELETE")
        except Exception as e:
            print(f"Supabase delete meal_item warning: {e}")

    return True

def update_meal_item(
    item_id: int,
    product_name: str,
    quantity_g: float,
    calories: float,
    protein_g: float,
    fat_g: float,
    carbs_g: float,
    category: str = "general",
    meal_type: Optional[str] = None,
    timestamp: Optional[str] = None
) -> Dict[str, Any]:
    """
    Updates an existing meal_item in SQLite and Supabase.
    Optionally updates the parent meal's meal_type (notes) and timestamp.
    """
    meal_id = None
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute("SELECT meal_id FROM meal_items WHERE id = ?", (item_id,)).fetchone()
        if row:
            meal_id = row["meal_id"]

        cursor.execute("""
            UPDATE meal_items
            SET product_name = ?,
                quantity_g = ?,
                calories = ?,
                protein_g = ?,
                fat_g = ?,
                carbs_g = ?,
                category = ?
            WHERE id = ?
        """, (
            product_name.strip(),
            float(quantity_g),
            float(calories),
            float(protein_g),
            float(fat_g),
            float(carbs_g),
            category,
            item_id
        ))

        if meal_id:
            if meal_type and timestamp:
                cursor.execute("UPDATE meals SET notes = ?, timestamp = ? WHERE id = ?", (meal_type, timestamp, meal_id))
            elif meal_type:
                cursor.execute("UPDATE meals SET notes = ? WHERE id = ?", (meal_type, meal_id))
            elif timestamp:
                cursor.execute("UPDATE meals SET timestamp = ? WHERE id = ?", (timestamp, meal_id))

        conn.commit()

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_item = supabase_request(f"meal_items?id=eq.{item_id}&select=meal_id")
            sp_meal_id = sp_item[0].get("meal_id") if (sp_item and isinstance(sp_item, list) and len(sp_item) > 0) else None
            if sp_meal_id:
                meal_id = sp_meal_id

            supabase_request(f"meal_items?id=eq.{item_id}", method="PATCH", data={
                "product_name": product_name.strip(),
                "quantity_g": float(quantity_g),
                "calories": float(calories),
                "protein_g": float(protein_g),
                "fat_g": float(fat_g),
                "carbs_g": float(carbs_g),
                "category": category
            })
            if sp_meal_id and (meal_type or timestamp):
                m_patch = {}
                if meal_type:
                    m_patch["notes"] = meal_type
                if timestamp:
                    m_patch["timestamp"] = timestamp
                supabase_request(f"meals?id=eq.{sp_meal_id}", method="PATCH", data=m_patch)
        except Exception as e:
            print(f"Supabase update meal_item warning: {e}")

    return {
        "id": item_id,
        "meal_id": meal_id,
        "product_name": product_name.strip(),
        "quantity_g": float(quantity_g),
        "calories": float(calories),
        "protein_g": float(protein_g),
        "fat_g": float(fat_g),
        "carbs_g": float(carbs_g),
        "category": category,
        "meal_type": meal_type
    }

def add_meal_entry(
    meal_type: str = "Перекус",
    items: Optional[List[Dict[str, Any]]] = None,
    raw_input: Optional[str] = None,
    target_date: Optional[str] = None,
    target_time: Optional[str] = None
) -> int:
    """
    Creates a new meal entry with structured items or by parsing raw text.
    Binds to specified date/time if provided.
    """
    ts = None
    if target_date:
        t_time = target_time or datetime.now().strftime("%H:%M:%S")
        if len(t_time) == 5:
            t_time += ":00"
        ts = f"{target_date} {t_time}"

    if items and len(items) > 0:
        raw_text = raw_input or ", ".join([f"{i.get('product_name')} {int(i.get('quantity_g', 100))}г" for i in items])
        return save_meal(
            raw_input=raw_text,
            input_type="manual",
            items=items,
            meal_type=meal_type,
            custom_timestamp=ts
        )

    if raw_input:
        from agents.ingestion_agent import ingestion_agent
        from agents.nutrition_agent import nutrition_agent
        from agents.auditor_agent import auditor_agent

        parsed_items = ingestion_agent.parse_input(raw_input)
        if not parsed_items:
            parsed_items = [{"product_name": raw_input.strip(), "quantity_g": 100}]
        
        calculated_items = nutrition_agent.calculate(parsed_items)
        audited_items = auditor_agent.audit(calculated_items)

        return save_meal(
            raw_input=raw_input,
            input_type="text",
            items=audited_items,
            meal_type=meal_type,
            custom_timestamp=ts
        )

    return 0

def clear_recent_meals(limit: int = 5) -> int:
    """Deletes the last N meals from SQLite and Supabase."""
    recent = get_recent_meals(limit=limit)
    count = 0
    for m in recent:
        mid = m.get("id")
        if mid:
            delete_meal(mid)
            count += 1
    return count

def delete_product_entry(product_name: Optional[str] = None, product_id: Optional[int] = None) -> bool:
    """Deletes a product by product_name or product_id from product_prices, custom_products, and coach_recommendations."""
    target_name = (product_name or "").strip().lower()
    with get_connection() as conn:
        cursor = conn.cursor()
        if product_id and not target_name:
            row = cursor.execute("SELECT product_name FROM product_prices WHERE id = ?", (product_id,)).fetchone()
            if row:
                target_name = str(row["product_name"]).strip().lower()

        if product_id:
            cursor.execute("DELETE FROM product_prices WHERE id = ?", (product_id,))
        if target_name:
            cursor.execute("DELETE FROM product_prices WHERE LOWER(product_name) = ?", (target_name,))
            cursor.execute("DELETE FROM custom_products WHERE LOWER(product_name) = ?", (target_name,))
            cursor.execute("DELETE FROM coach_recommendations WHERE LOWER(topic) LIKE ?", (f"%{target_name}%",))
        conn.commit()

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            if product_id:
                supabase_request(f"product_prices?id=eq.{product_id}", method="DELETE")
            if target_name:
                enc = urllib.parse.quote(target_name)
                supabase_request(f"product_prices?product_name=ilike.{enc}", method="DELETE")
                supabase_request(f"custom_products?product_name=ilike.{enc}", method="DELETE")
                supabase_request(f"coach_recommendations?topic=ilike.*{enc}*", method="DELETE")
        except Exception as e:
            print(f"Supabase delete product warning: {e}")

    cache_invalidate("product_prices", "product_price_map", "coach_product_verdicts")
    return True

def delete_product(product_name: str) -> bool:
    """Deletes a product from product_prices, custom_products, and coach_recommendations."""
    return delete_product_entry(product_name=product_name)

def _evaluate_fallback_coach_macros(product_name: str, cal_100: float, p_100: float, f_100: float, c_100: float, category: str = "general"):
    prot_cal = p_100 * 4.0
    fat_cal = f_100 * 9.0
    carb_cal = c_100 * 4.0
    tot_cal = max(cal_100, prot_cal + fat_cal + carb_cal, 1.0)
    prot_ratio = prot_cal / tot_cal

    if category == "sweets" or (c_100 > 40 and f_100 > 15):
        score = 2
        verdict = f"Десерт с избытком сахаров ({c_100:.0f}г) и насыщенных жиров ({f_100:.0f}г). Провоцирует скачки инсулина и отложение жира. Употребляйте умеренно."
    elif prot_ratio >= 0.45:
        score = 10
        verdict = f"Превосходный источник чистого белка ({p_100:.1f}г). Идеально подходит для насыщения, защиты мышц и похудения."
    elif prot_ratio >= 0.25:
        score = 8
        verdict = f"Качественный белковый продукт ({p_100:.1f}г белка). Отлично вписывается в сбалансированный спортивный рацион."
    elif category in ["vegetables", "fruit"]:
        score = 8
        verdict = "Богат витаминами и клетчаткой, полезен для пищеварения и иммунитета."
    elif fat_cal / tot_cal > 0.65:
        score = 4
        verdict = f"Высокая плотность жиров ({f_100:.1f}г). Контролируйте размер порции, чтобы не выбиться из дневного калоража."
    else:
        score = 6
        verdict = "Базовый продукт питания. Употребляйте в рамках вашей дневной нормы калорий и БЖУ."
    return score, verdict

def update_product_price(
    product_name: str,
    original_name: Optional[str] = None,
    product_id: Optional[int] = None,
    price_rub: float = 0.0,
    weight_g: float = 100.0,
    category: str = "general",
    protein_100g: float = 0.0,
    fat_100g: float = 0.0,
    carbs_100g: float = 0.0,
    calories_100g: float = 0.0,
    coach_score: int = 0,
    coach_verdict: str = ""
) -> Dict[str, Any]:
    """
    Updates an existing product in SQLite and Supabase with exact values,
    validating energy integrity (4P + 9F + 4C) and updating custom_products + coach tips.
    Supports renaming product when original_name is provided.
    """
    new_name = product_name.strip()
    orig_name = (original_name or "").strip()

    with get_connection() as conn:
        cursor = conn.cursor()
        if product_id and not orig_name:
            row = cursor.execute("SELECT product_name FROM product_prices WHERE id = ?", (product_id,)).fetchone()
            if row:
                orig_name = str(row["product_name"]).strip()

    if not orig_name:
        orig_name = new_name

    val = validate_product_values(
        protein_100g=protein_100g,
        fat_100g=fat_100g,
        carbs_100g=carbs_100g,
        calories_100g=calories_100g,
        price_rub=price_rub,
        weight_g=weight_g,
        coach_score=coach_score
    )
    p_100 = val["protein_100g"]
    f_100 = val["fat_100g"]
    c_100 = val["carbs_100g"]
    cal_100 = val["calories_100g"]
    pr_rub = val["price_rub"]
    w_g = val["weight_g"]
    score = val["coach_score"]
    
    if score <= 0 or not coach_verdict:
        f_score, f_verdict = _evaluate_fallback_coach_macros(new_name, cal_100, p_100, f_100, c_100, category)
        score = score or f_score
        coach_verdict = coach_verdict or f_verdict

    with get_connection() as conn:
        cursor = conn.cursor()
        # If product is being renamed, clean up old entry in custom_products
        if orig_name and orig_name.lower() != new_name.lower():
            cursor.execute("DELETE FROM custom_products WHERE LOWER(product_name) = ?", (orig_name.lower(),))
            cursor.execute("DELETE FROM coach_recommendations WHERE LOWER(topic) LIKE ?", (f"%{orig_name.lower()}%",))

        # Check if updating by ID or by name
        updated = False
        if product_id:
            cursor.execute("""
                UPDATE product_prices
                SET product_name = ?,
                    category = ?,
                    price_rub = ?,
                    weight_g = ?,
                    protein_per_100g = ?,
                    fat_per_100g = ?,
                    carbs_per_100g = ?,
                    calories_per_100g = ?,
                    coach_score = ?,
                    coach_verdict = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
            """, (new_name.lower(), category, pr_rub, w_g, p_100, f_100, c_100, cal_100, score, coach_verdict, product_id))
            if cursor.rowcount > 0:
                updated = True

        if not updated:
            cursor.execute("""
                UPDATE product_prices
                SET product_name = ?,
                    category = ?,
                    price_rub = ?,
                    weight_g = ?,
                    protein_per_100g = ?,
                    fat_per_100g = ?,
                    carbs_per_100g = ?,
                    calories_per_100g = ?,
                    coach_score = ?,
                    coach_verdict = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE LOWER(product_name) = ?
            """, (new_name.lower(), category, pr_rub, w_g, p_100, f_100, c_100, cal_100, score, coach_verdict, orig_name.lower()))
            if cursor.rowcount == 0:
                # If product didn't exist, insert it
                cursor.execute("""
                    INSERT INTO product_prices
                    (product_name, category, price_rub, weight_g, protein_per_100g, fat_per_100g, carbs_per_100g, calories_per_100g, coach_score, coach_verdict)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (new_name.lower(), category, pr_rub, w_g, p_100, f_100, c_100, cal_100, score, coach_verdict))
        conn.commit()

    # Sync custom_products table
    save_custom_product(new_name, cal_100, p_100, f_100, c_100)

    # Save coach verdict if present
    if coach_verdict:
        severity = "info" if score >= 7 else ("warning" if score <= 4 else "tip")
        save_coach_recommendation(
            topic=f"Продукт: {new_name.capitalize()} ({score}/10)",
            recommendation=coach_verdict,
            severity=severity
        )

    # Sync with Supabase
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            if orig_name and orig_name.lower() != new_name.lower():
                enc_orig = urllib.parse.quote(orig_name.lower())
                supabase_request(f"product_prices?product_name=ilike.{enc_orig}", method="DELETE")
                supabase_request(f"custom_products?product_name=ilike.{enc_orig}", method="DELETE")

            supabase_request("product_prices?on_conflict=product_name", method="POST", data={
                "product_name": new_name.lower(),
                "category": category,
                "price_rub": pr_rub,
                "weight_g": w_g,
                "protein_per_100g": p_100,
                "fat_per_100g": f_100,
                "carbs_per_100g": c_100,
                "calories_per_100g": cal_100
            }, prefer="resolution=merge-duplicates,return=representation")
        except Exception as e:
            print(f"Supabase update price warning: {e}")

    cache_invalidate("product_prices", "product_price_map", "coach_product_verdicts")

    price_100 = round((pr_rub / w_g) * 100, 2) if w_g > 0 else 0.0
    return {
        "product_name": new_name.lower(),
        "category": category,
        "price_rub": pr_rub,
        "weight_g": w_g,
        "price_per_100g": price_100,
        "protein_per_100g": p_100,
        "fat_per_100g": f_100,
        "carbs_per_100g": c_100,
        "calories_per_100g": cal_100,
        "coach_score": score,
        "coach_verdict": coach_verdict
    }

def estimate_product_nutrition(product_name: str, category: Optional[str] = None) -> Dict[str, Any]:
    """Estimates macros, calories, category, coach score and verdict for a given product name."""
    p_name = (product_name or "").strip()
    if not p_name:
        return {
            "product_name": "",
            "category": "general",
            "calories_100g": 100,
            "protein_100g": 5,
            "fat_100g": 2,
            "carbs_100g": 15,
            "coach_score": 6,
            "coach_verdict": "Базовый продукт питания."
        }

    # Check if we already have it in custom_products or product_prices
    with get_connection() as conn:
        cursor = conn.cursor()
        row = cursor.execute(
            "SELECT * FROM product_prices WHERE LOWER(product_name) = ? OR product_name LIKE ?",
            (p_name.lower(), f"%{p_name.lower()}%")
        ).fetchone()
        if row:
            d = dict(row)
            return {
                "product_name": d.get("product_name"),
                "category": d.get("category") or "general",
                "calories_100g": d.get("calories_per_100g") or 0,
                "protein_100g": d.get("protein_per_100g") or 0,
                "fat_100g": d.get("fat_per_100g") or 0,
                "carbs_100g": d.get("carbs_per_100g") or 0,
                "price_rub": d.get("price_rub") or 0,
                "weight_g": d.get("weight_g") or 100,
                "coach_score": d.get("coach_score") or 6,
                "coach_verdict": d.get("coach_verdict") or ""
            }

    # Try nutrition_agent calculation
    try:
        from agents.nutrition_agent import nutrition_agent
        calc = nutrition_agent.calculate([{"product_name": p_name, "quantity_g": 100}])
        if calc and len(calc) > 0:
            m = calc[0]
            cat = category or m.get("category") or "general"
            cal = float(m.get("calories", 0))
            p = float(m.get("protein_g", 0))
            f = float(m.get("fat_g", 0))
            c = float(m.get("carbs_g", 0))
            score, verdict = _evaluate_fallback_coach_macros(p_name, cal, p, f, c, cat)
            return {
                "product_name": p_name,
                "category": cat,
                "calories_100g": int(round(cal)),
                "protein_100g": round(p, 1),
                "fat_100g": round(f, 1),
                "carbs_100g": round(c, 1),
                "coach_score": score,
                "coach_verdict": verdict
            }
    except Exception as e:
        print(f"Estimate nutrition error: {e}")

    score, verdict = _evaluate_fallback_coach_macros(p_name, 120, 4, 3, 18, category or "general")
    return {
        "product_name": p_name,
        "category": category or "general",
        "calories_100g": 120,
        "protein_100g": 4.0,
        "fat_100g": 3.0,
        "carbs_100g": 18.0,
        "coach_score": score,
        "coach_verdict": verdict
    }

def save_product_price(product_name: str, price_rub: float, weight_g: float = 100.0,
                       category: str = "general", protein_100g: float = 0, fat_100g: float = 0,
                       carbs_100g: float = 0, calories_100g: float = 0, coach_score: int = 0,
                       coach_verdict: str = ""):
    product_name = product_name.lower().strip()
    val = validate_product_values(
        protein_100g=protein_100g,
        fat_100g=fat_100g,
        carbs_100g=carbs_100g,
        calories_100g=calories_100g,
        price_rub=price_rub,
        weight_g=weight_g,
        coach_score=coach_score
    )
    protein_100g = val["protein_100g"]
    fat_100g = val["fat_100g"]
    carbs_100g = val["carbs_100g"]
    calories_100g = val["calories_100g"]
    price_rub = val["price_rub"]
    weight_g = val["weight_g"]
    coach_score = val["coach_score"]

    with get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT product_name FROM product_prices").fetchall()
        for r in rows:
            ex_name = r["product_name"]
            if ex_name != product_name and are_product_duplicates(ex_name, product_name):
                product_name = ex_name
                break

        cursor.execute(
            """
            INSERT INTO product_prices 
            (product_name, category, price_rub, weight_g, protein_per_100g, fat_per_100g, carbs_per_100g, calories_per_100g, coach_score, coach_verdict)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(product_name) DO UPDATE SET
                price_rub = excluded.price_rub,
                weight_g = excluded.weight_g,
                category = excluded.category,
                protein_per_100g = CASE WHEN excluded.protein_per_100g > 0 THEN excluded.protein_per_100g ELSE product_prices.protein_per_100g END,
                fat_per_100g = CASE WHEN excluded.fat_per_100g > 0 THEN excluded.fat_per_100g ELSE product_prices.fat_per_100g END,
                carbs_per_100g = CASE WHEN excluded.carbs_per_100g > 0 THEN excluded.carbs_per_100g ELSE product_prices.carbs_per_100g END,
                calories_per_100g = CASE WHEN excluded.calories_per_100g > 0 THEN excluded.calories_per_100g ELSE product_prices.calories_per_100g END,
                coach_score = CASE WHEN excluded.coach_score > 0 THEN excluded.coach_score ELSE product_prices.coach_score END,
                coach_verdict = CASE WHEN length(excluded.coach_verdict) > 0 THEN excluded.coach_verdict ELSE product_prices.coach_verdict END,
                updated_at = CURRENT_TIMESTAMP
            """,
            (product_name, category, price_rub, weight_g, protein_100g, fat_100g, carbs_100g, calories_100g, coach_score, coach_verdict)
        )
        conn.commit()

    if coach_verdict:
        severity = "info" if coach_score >= 7 else ("warning" if coach_score <= 4 else "tip")
        save_coach_recommendation(
            topic=f"Продукт: {product_name.capitalize()} ({coach_score}/10)",
            recommendation=coach_verdict,
            severity=severity
        )

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase_request("product_prices?on_conflict=product_name", method="POST", data={
                "product_name": product_name,
                "category": category,
                "price_rub": price_rub,
                "weight_g": weight_g,
                "protein_per_100g": protein_100g,
                "fat_per_100g": fat_100g,
                "carbs_per_100g": carbs_100g,
                "calories_per_100g": calories_100g
            }, prefer="resolution=merge-duplicates,return=representation")
        except Exception as e:
            print(f"Supabase price sync warning: {e}")

    cache_invalidate("product_prices", "product_price_map", "coach_product_verdicts")

def _load_coach_product_verdicts() -> Dict[str, Dict[str, Any]]:
    cached = cache_get("coach_product_verdicts", ttl=60.0)
    if cached is not None:
        return cached

    verdicts: Dict[str, Dict[str, Any]] = {}
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            recs = supabase_request("coach_recommendations?topic=ilike.*Продукт*&order=id.desc")
            if recs and isinstance(recs, list):
                for r in recs:
                    top = r.get("topic", "")
                    if "(" in top and "/10" in top:
                        m = re.search(r"Продукт:\s*(.+?)\s*\((\d+)/10\)", top)
                        if m:
                            p_name = m.group(1).strip().lower()
                            if p_name not in verdicts:
                                verdicts[p_name] = {"score": int(m.group(2)), "verdict": r.get("recommendation", "")}
                    elif top.startswith("Продукт:"):
                        p_name = top.split("Продукт:", 1)[1].strip().lower()
                        if p_name not in verdicts:
                            verdicts[p_name] = {"score": None, "verdict": r.get("recommendation", "")}
        except Exception:
            pass

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            rows = cursor.execute("SELECT topic, recommendation FROM coach_recommendations WHERE topic LIKE 'Продукт:%' ORDER BY id DESC").fetchall()
            for r in rows:
                top = r["topic"]
                if "(" in top and "/10" in top:
                    m = re.search(r"Продукт:\s*(.+?)\s*\((\d+)/10\)", top)
                    if m:
                        p_name = m.group(1).strip().lower()
                        if p_name not in verdicts:
                            verdicts[p_name] = {"score": int(m.group(2)), "verdict": r["recommendation"]}
                elif top.startswith("Продукт:"):
                    p_name = top.split("Продукт:", 1)[1].strip().lower()
                    if p_name not in verdicts:
                        verdicts[p_name] = {"score": None, "verdict": r["recommendation"]}
    except Exception:
        pass
    cache_set("coach_product_verdicts", verdicts)
    return verdicts

def get_product_prices() -> List[Dict[str, Any]]:
    cached = cache_get("product_prices", ttl=60.0)
    if cached is not None:
        return cached

    coach_verdicts = _load_coach_product_verdicts()
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
                    price_rub = float(d.get("price_rub", 0))
                    weight_g = float(d.get("weight_g", 0))
                    price_100g = float(d.get("price_per_100g") or 0)
                    if price_100g <= 0 and weight_g > 0:
                        price_100g = round((price_rub / weight_g) * 100, 2)
                    d["price_per_100g"] = price_100g
                    d["currency"] = "€"

                    protein_ratio = (p * 4.0) / cal if cal > 0 else 0.1
                    score = round(min(10.0, max(1.0, (protein_ratio * 12.0) + 3.0)), 1)
                    badge_class = "good" if score >= 7.5 else ("warn" if score >= 5.0 else "crit")
                    label = "Высокий" if score >= 7.5 else ("Средний" if score >= 5.0 else "Низкий")

                    p_name = d.get("product_name", "").strip().lower()
                    c_info = coach_verdicts.get(p_name, {})

                    d["calories_per_100g"] = int(round(cal))
                    d["protein_per_100g"] = int(round(p))
                    d["fat_per_100g"] = int(round(f))
                    d["carbs_per_100g"] = int(round(c))
                    d["efficiency_score"] = score
                    d["coach_score"] = int(d.get("coach_score") or c_info.get("score") or round(score))
                    d["coach_verdict"] = d.get("coach_verdict") or c_info.get("verdict") or ""
                    d["efficiency_label"] = label
                    d["badge_class"] = badge_class
                    result.append(d)
                cache_set("product_prices", result)
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
            price_rub = float(d.get("price_rub", 0))
            weight_g = float(d.get("weight_g", 0))
            price_100g = float(d.get("price_per_100g") or 0)
            if price_100g <= 0 and weight_g > 0:
                price_100g = round((price_rub / weight_g) * 100, 2)
            d["price_per_100g"] = price_100g
            d["currency"] = "€"

            # Compute Nutrition Efficiency Index (1.0 to 10.0 scale)
            protein_ratio = (p * 4.0) / cal if cal > 0 else 0.1
            score = round(min(10.0, max(1.0, (protein_ratio * 12.0) + 3.0)), 1)
            
            badge_class = "good" if score >= 7.5 else ("warn" if score >= 5.0 else "crit")
            label = "Высокий" if score >= 7.5 else ("Средний" if score >= 5.0 else "Низкий")

            p_name = d.get("product_name", "").strip().lower()
            c_info = coach_verdicts.get(p_name, {})

            d["calories_per_100g"] = int(round(cal))
            d["protein_per_100g"] = int(round(p))
            d["fat_per_100g"] = int(round(f))
            d["carbs_per_100g"] = int(round(c))
            d["efficiency_score"] = score
            d["coach_score"] = int(d.get("coach_score") or c_info.get("score") or round(score))
            d["coach_verdict"] = d.get("coach_verdict") or c_info.get("verdict") or ""
            d["efficiency_label"] = label
            d["badge_class"] = badge_class
            result.append(d)
        cache_set("product_prices", result)
        return result

def get_product_price_map() -> Dict[str, float]:
    """Returns mapping of product name to price per 100g in EUR (€). Cached for 60s."""
    cached = cache_get("product_price_map", ttl=60.0)
    if cached is not None:
        return cached

    prices = get_product_prices()
    pm: Dict[str, float] = {}
    for p in prices:
        name = (p.get("product_name") or "").strip().lower()
        p100 = float(p.get("price_per_100g") or 0.0)
        if name and p100 > 0:
            pm[name] = p100
    cache_set("product_price_map", pm)
    return pm

def find_item_price_per_100g(item_name: str, price_map: Optional[Dict[str, float]] = None) -> Optional[float]:
    """Finds price per 100g for an ingredient using exact, canonical duplicate, or token matching."""
    if price_map is None:
        price_map = get_product_price_map()
    n = (item_name or "").strip().lower()
    if not n or not price_map:
        return None

    if n in price_map:
        return price_map[n]

    # Rule: Raw pork / shashlik pork mapping -> matches 'свинина полужирная' or 'свинина'
    if ("шашлык" in n and "свин" in n) or n == "свинина" or n.startswith("свин"):
        for p_name, pr in price_map.items():
            if "свин" in p_name:
                return pr

    for p_name, pr in price_map.items():
        if are_product_duplicates(n, p_name):
            return pr

    toks = set(stem_product_word(t) for t in re.sub(r'[^\w\s]', '', n).split() if len(t) > 1)
    for p_name, pr in price_map.items():
        p_toks = set(stem_product_word(t) for t in re.sub(r'[^\w\s]', '', p_name).split() if len(t) > 1)
        if toks and p_toks and toks.intersection(p_toks):
            return pr

    return None

def calculate_item_cost(product_name: str, quantity_g: float, price_map: Optional[Dict[str, float]] = None) -> float:
    """Calculates EUR cost for an ingredient amount."""
    pr100 = find_item_price_per_100g(product_name, price_map)
    if pr100 is not None and quantity_g > 0:
        return round((quantity_g / 100.0) * pr100, 2)
    return 0.0

def save_coach_recommendation(topic: str, recommendation: str, severity: str = "info"):
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO coach_recommendations (topic, recommendation, severity) VALUES (?, ?, ?)",
            (topic, recommendation, severity)
        )
        conn.commit()

    if SUPABASE_URL and SUPABASE_KEY:
        try:
            supabase_request("coach_recommendations", method="POST", data={
                "topic": topic,
                "recommendation": recommendation,
                "severity": severity
            })
        except Exception as e:
            print(f"Supabase coach sync warning: {e}")

def get_recent_recommendations(limit: int = 5) -> List[Dict[str, Any]]:
    if SUPABASE_URL and SUPABASE_KEY:
        try:
            sp_recs = supabase_request(f"coach_recommendations?select=*&order=timestamp.desc&limit={limit}")
            if sp_recs and isinstance(sp_recs, list) and len(sp_recs) > 0:
                return [
                    {
                        "id": r.get("id"),
                        "timestamp": (r.get("timestamp") or "")[:16].replace("T", " "),
                        "topic": r.get("topic", ""),
                        "recommendation": r.get("recommendation", ""),
                        "severity": r.get("severity", "info"),
                    }
                    for r in sp_recs
                ]
        except Exception as e:
            print(f"Supabase recent recommendations warning: {e}")

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

