import urllib.request
import urllib.parse
import json
from typing import List, Dict, Any

# Built-in Reference Database per 100g
NUTRITION_DATABASE: Dict[str, Dict[str, float]] = {
    # Meats & Delicatessen
    "бекон": {"calories": 541, "protein": 37.0, "fat": 42.0, "carbs": 1.4, "category": "meat"},
    "ветчина": {"calories": 145, "protein": 16.0, "fat": 8.0, "carbs": 1.5, "category": "meat"},
    "колбаса": {"calories": 300, "protein": 12.0, "fat": 27.0, "carbs": 1.0, "category": "meat"},
    "сосиски": {"calories": 260, "protein": 11.0, "fat": 23.0, "carbs": 1.5, "category": "meat"},
    "куриная грудка": {"calories": 165, "protein": 31.0, "fat": 3.6, "carbs": 0.0, "category": "meat"},
    "курица": {"calories": 190, "protein": 27.0, "fat": 8.0, "carbs": 0.0, "category": "meat"},
    "индейка": {"calories": 135, "protein": 29.0, "fat": 1.6, "carbs": 0.0, "category": "meat"},
    "говядина": {"calories": 250, "protein": 26.0, "fat": 15.0, "carbs": 0.0, "category": "meat"},
    "свинина": {"calories": 242, "protein": 27.0, "fat": 14.0, "carbs": 0.0, "category": "meat"},
    
    # Fish & Seafood
    "лосось": {"calories": 208, "protein": 20.0, "fat": 13.0, "carbs": 0.0, "category": "fish"},
    "тунец": {"calories": 130, "protein": 28.0, "fat": 1.0, "carbs": 0.0, "category": "fish"},
    "креветки": {"calories": 99, "protein": 24.0, "fat": 0.3, "carbs": 0.2, "category": "fish"},
    "рыба": {"calories": 150, "protein": 19.0, "fat": 6.0, "carbs": 0.0, "category": "fish"},

    # Eggs & Dairy
    "яйцо": {"calories": 155, "protein": 13.0, "fat": 11.0, "carbs": 1.1, "category": "eggs_dairy"},
    "яйца": {"calories": 155, "protein": 13.0, "fat": 11.0, "carbs": 1.1, "category": "eggs_dairy"},
    "творог": {"calories": 121, "protein": 18.0, "fat": 5.0, "carbs": 3.0, "category": "eggs_dairy"},
    "творог 5%": {"calories": 121, "protein": 18.0, "fat": 5.0, "carbs": 3.0, "category": "eggs_dairy"},
    "творог 9%": {"calories": 159, "protein": 16.0, "fat": 9.0, "carbs": 3.0, "category": "eggs_dairy"},
    "сыр": {"calories": 360, "protein": 24.0, "fat": 28.0, "carbs": 1.3, "category": "eggs_dairy"},
    "молоко": {"calories": 60, "protein": 3.2, "fat": 3.2, "carbs": 4.8, "category": "eggs_dairy"},
    "сметана": {"calories": 160, "protein": 2.6, "fat": 15.0, "carbs": 3.6, "category": "eggs_dairy"},
    "майонез": {"calories": 627, "protein": 1.0, "fat": 67.0, "carbs": 2.6, "category": "fats_oils"},
    "масло сливочное": {"calories": 717, "protein": 0.8, "fat": 81.0, "carbs": 0.6, "category": "fats_oils"},
    "масло растительное": {"calories": 884, "protein": 0.0, "fat": 100.0, "carbs": 0.0, "category": "fats_oils"},

    # Fruits & Vegetables
    "авокадо": {"calories": 160, "protein": 2.0, "fat": 14.7, "carbs": 8.5, "category": "vegetables"},
    "банан": {"calories": 89, "protein": 1.1, "fat": 0.3, "carbs": 22.8, "category": "fruit"},
    "яблоко": {"calories": 52, "protein": 0.3, "fat": 0.2, "carbs": 13.8, "category": "fruit"},
    "картофель": {"calories": 77, "protein": 2.0, "fat": 0.1, "carbs": 17.0, "category": "vegetables"},
    
    # Carbs & Grains
    "гречка": {"calories": 343, "protein": 13.0, "fat": 3.4, "carbs": 72.0, "category": "grains"},
    "рис": {"calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28.0, "category": "grains"},
    "овсянка": {"calories": 389, "protein": 16.9, "fat": 6.9, "carbs": 66.0, "category": "grains"},
    "хлеб": {"calories": 265, "protein": 9.0, "fat": 3.2, "carbs": 49.0, "category": "bakery"},
    "макароны": {"calories": 131, "protein": 5.0, "fat": 1.1, "carbs": 25.0, "category": "grains"},

    # Nuts & Supplements
    "орехи": {"calories": 654, "protein": 15.0, "fat": 65.0, "carbs": 14.0, "category": "nuts"},
    "миндаль": {"calories": 579, "protein": 21.0, "fat": 49.0, "carbs": 22.0, "category": "nuts"},
    "протеин": {"calories": 380, "protein": 75.0, "fat": 4.0, "carbs": 8.0, "category": "supplements"},
}

def fetch_openfoodfacts_nutrition(product_name: str) -> Dict[str, float]:
    """Fallback: Queries Open Food Facts API for accurate macro values per 100g."""
    try:
        query = urllib.parse.quote(product_name)
        url = f"https://world.openfoodfacts.org/cgi/search.pl?search_terms={query}&search_simple=1&action=process&json=1&page_size=1"
        req = urllib.request.Request(url, headers={"User-Agent": "CaloriesAI/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode('utf-8'))
            products = data.get("products", [])
            if products:
                nutriments = products[0].get("nutriments", {})
                cal = float(nutriments.get("energy-kcal_100g", nutriments.get("energy-kcal", 150)))
                p = float(nutriments.get("proteins_100g", 8.0))
                f = float(nutriments.get("fat_100g", 5.0))
                c = float(nutriments.get("carbohydrates_100g", 18.0))
                return {"calories": cal, "protein": p, "fat": f, "carbs": c, "category": "openfoodfacts"}
    except Exception:
        pass
    return {"calories": 150, "protein": 8.0, "fat": 5.0, "carbs": 18.0, "category": "general"}

class NutritionAgent:
    """
    Agent 2: Nutrition Calculation Agent
    Calculates detailed nutritional macros (Calories, Protein, Fat, Carbs) based on product weight.
    """
    def __init__(self):
        self.name = "NutritionAgent"

    def calculate(self, items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        calculated_items = []
        for item in items:
            p_name = item.get("product_name", "").lower().strip()
            qty_g = float(item.get("quantity_g", 100))

            matched_info = None
            for key, val in NUTRITION_DATABASE.items():
                if key in p_name or p_name in key:
                    matched_info = val
                    break

            if not matched_info:
                matched_info = fetch_openfoodfacts_nutrition(p_name)

            ratio = qty_g / 100.0
            cal = round(matched_info["calories"] * ratio, 1)
            prot = round(matched_info["protein"] * ratio, 1)
            fat = round(matched_info["fat"] * ratio, 1)
            carbs = round(matched_info["carbs"] * ratio, 1)

            calculated_items.append({
                "product_name": item.get("product_name"),
                "category": matched_info.get("category", "general"),
                "quantity_g": qty_g,
                "calories": cal,
                "protein_g": prot,
                "fat_g": fat,
                "carbs_g": carbs
            })

        return calculated_items

nutrition_agent = NutritionAgent()
