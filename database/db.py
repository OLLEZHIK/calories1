import sqlite3
import json
import urllib.request
import urllib.error
from typing import List, Dict, Any, Optional
from datetime import datetime, date
from config import DB_PATH, SUPABASE_URL, SUPABASE_KEY, USE_SUPABASE
from pathlib import Path

def supabase_request(endpoint: str, method: str = "GET", data: Optional[Dict[str, Any]] = None) -> Any:
    """Executes HTTPS REST request to Supabase Database API."""
    if not SUPABASE_URL or not SUPABASE_KEY:
        return None

    url = f"{SUPABASE_URL.rstrip('/')}/rest/v1/{endpoint}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }

    body_bytes = json.dumps(data).encode("utf-8") if data else None
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req) as resp:
            resp_text = resp.read().decode("utf-8")
            return json.loads(resp_text) if resp_text else []
    except Exception as e:
        print(f"Supabase API Request Error: {e}")
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

def save_meal(raw_input: str, input_type: str, items: List[Dict[str, Any]]) -> int:
    """
    Saves a raw meal log and its parsed/calculated items into the database.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO meals (raw_input, input_type) VALUES (?, ?)",
            (raw_input, input_type)
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
        return meal_id

def get_today_summary(target_date: Optional[str] = None) -> Dict[str, Any]:
    if not target_date:
        target_date = date.today().isoformat()
        
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
        
        # Get user goals
        goals_row = cursor.execute("SELECT * FROM user_goals ORDER BY id DESC LIMIT 1").fetchone()
        goals = {
            "calories": goals_row["calories"] if goals_row else 2200,
            "protein_g": goals_row["protein_g"] if goals_row else 160,
            "fat_g": goals_row["fat_g"] if goals_row else 70,
            "carbs_g": goals_row["carbs_g"] if goals_row else 230,
        }
        
        return {
            "date": target_date,
            "total_calories": round(row["total_calories"], 1),
            "total_protein": round(row["total_protein"], 1),
            "total_fat": round(row["total_fat"], 1),
            "total_carbs": round(row["total_carbs"], 1),
            "goals": goals
        }

def get_recent_meals(limit: int = 10) -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
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
                "items": items,
                "total_calories": sum(i["calories"] for i in items),
                "total_protein": sum(i["protein_g"] for i in items),
                "total_fat": sum(i["fat_g"] for i in items),
                "total_carbs": sum(i["carbs_g"] for i in items),
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
                protein_per_100g = excluded.protein_per_100g,
                fat_per_100g = excluded.fat_per_100g,
                carbs_per_100g = excluded.carbs_per_100g,
                calories_per_100g = excluded.calories_per_100g,
                updated_at = CURRENT_TIMESTAMP
            """,
            (product_name, category, price_rub, weight_g, protein_100g, fat_100g, carbs_100g, calories_100g)
        )
        conn.commit()

def get_product_prices() -> List[Dict[str, Any]]:
    with get_connection() as conn:
        cursor = conn.cursor()
        rows = cursor.execute("SELECT *, price_per_100g FROM product_prices ORDER BY product_name").fetchall()
        return [dict(r) for r in rows]

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

# Initialize DB when module loaded
init_db()
