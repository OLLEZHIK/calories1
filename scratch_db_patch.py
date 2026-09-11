import os

path = 'database/db.py'
with open(path, 'r', encoding='utf-8') as f:
    content = f.read()

new_funcs = """
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
            supabase_request("custom_products", method="POST", data={
                "product_name": product_name,
                "calories_100g": cal_100,
                "protein_100g": p_100,
                "fat_100g": f_100,
                "carbs_100g": c_100
            })
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

def save_meal("""

content = content.replace("def save_meal(", new_funcs)

with open(path, 'w', encoding='utf-8') as f:
    f.write(content)
print("Updated db.py")
