from typing import List, Dict, Any

# Built-in Reference Database per 100g
NUTRITION_DATABASE: Dict[str, Dict[str, float]] = {
    # Proteins & Dairy
    "яйцо": {"calories": 155, "protein": 13.0, "fat": 11.0, "carbs": 1.1, "category": "eggs_dairy"},
    "яйца": {"calories": 155, "protein": 13.0, "fat": 11.0, "carbs": 1.1, "category": "eggs_dairy"},
    "куриная грудка": {"calories": 165, "protein": 31.0, "fat": 3.6, "carbs": 0.0, "category": "meat"},
    "курица": {"calories": 190, "protein": 27.0, "fat": 8.0, "carbs": 0.0, "category": "meat"},
    "говядина": {"calories": 250, "protein": 26.0, "fat": 15.0, "carbs": 0.0, "category": "meat"},
    "свинина": {"calories": 242, "protein": 27.0, "fat": 14.0, "carbs": 0.0, "category": "meat"},
    "лосось": {"calories": 208, "protein": 20.0, "fat": 13.0, "carbs": 0.0, "category": "fish"},
    "рыба": {"calories": 150, "protein": 19.0, "fat": 6.0, "carbs": 0.0, "category": "fish"},
    "творог": {"calories": 121, "protein": 18.0, "fat": 5.0, "carbs": 3.0, "category": "eggs_dairy"},
    "творог 5%": {"calories": 121, "protein": 18.0, "fat": 5.0, "carbs": 3.0, "category": "eggs_dairy"},
    "творог 9%": {"calories": 159, "protein": 16.0, "fat": 9.0, "carbs": 3.0, "category": "eggs_dairy"},
    "сметана": {"calories": 160, "protein": 2.6, "fat": 15.0, "carbs": 3.6, "category": "eggs_dairy"},
    "майонез": {"calories": 627, "protein": 1.0, "fat": 67.0, "carbs": 2.6, "category": "fats_oils"},
    "масло сливочное": {"calories": 717, "protein": 0.8, "fat": 81.0, "carbs": 0.6, "category": "fats_oils"},
    "масло растительное": {"calories": 884, "protein": 0.0, "fat": 100.0, "carbs": 0.0, "category": "fats_oils"},
    "масло оливковое": {"calories": 884, "protein": 0.0, "fat": 100.0, "carbs": 0.0, "category": "fats_oils"},
    
    # Carbs & Grains
    "гречка": {"calories": 343, "protein": 13.0, "fat": 3.4, "carbs": 72.0, "category": "grains"},
    "рис": {"calories": 130, "protein": 2.7, "fat": 0.3, "carbs": 28.0, "category": "grains"},
    "овсянка": {"calories": 389, "protein": 16.9, "fat": 6.9, "carbs": 66.0, "category": "grains"},
    "хлеб": {"calories": 265, "protein": 9.0, "fat": 3.2, "carbs": 49.0, "category": "bakery"},
    "макароны": {"calories": 131, "protein": 5.0, "fat": 1.1, "carbs": 25.0, "category": "grains"},
    "картофель": {"calories": 77, "protein": 2.0, "fat": 0.1, "carbs": 17.0, "category": "vegetables"},

    # Nuts & Snacks
    "орехи": {"calories": 654, "protein": 15.0, "fat": 65.0, "carbs": 14.0, "category": "nuts"},
    "миндаль": {"calories": 579, "protein": 21.0, "fat": 49.0, "carbs": 22.0, "category": "nuts"},
    "протеин": {"calories": 380, "protein": 75.0, "fat": 4.0, "carbs": 8.0, "category": "supplements"},
}

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

            # Match against database
            matched_info = None
            for key, val in NUTRITION_DATABASE.items():
                if key in p_name or p_name in key:
                    matched_info = val
                    break

            if not matched_info:
                # Default average estimation if unknown product
                matched_info = {"calories": 150, "protein": 8.0, "fat": 5.0, "carbs": 18.0, "category": "general"}

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
