from typing import List, Dict, Any
from database.db import save_product_price, get_product_prices

class EconomyAgent:
    """
    Agent 4: Price & Economy Agent
    Tracks product costs, computes RUB per 100g and RUB per gram of protein/fat/carbs,
    and identifies cost-effective protein/fat sources.
    """
    def __init__(self):
        self.name = "EconomyAgent"

    def record_price(self, product_name: str, price_rub: float, weight_g: float,
                     protein_100g: float = 0, fat_100g: float = 0, carbs_100g: float = 0, calories_100g: float = 0):
        save_product_price(
            product_name=product_name,
            price_rub=price_rub,
            weight_g=weight_g,
            protein_100g=protein_100g,
            fat_100g=fat_100g,
            carbs_100g=carbs_100g,
            calories_100g=calories_100g
        )

    def analyze_economy(self) -> Dict[str, Any]:
        prices = get_product_prices()
        if not prices:
            return {"best_protein_sources": [], "best_fat_sources": [], "message": "No price records available."}

        analyzed = []
        for p in prices:
            price_100g = p.get("price_per_100g", 0)
            prot = p.get("protein_per_100g", 0)
            fat = p.get("fat_per_100g", 0)

            rub_per_g_protein = round(price_100g / prot, 2) if prot > 0 else None
            rub_per_g_fat = round(price_100g / fat, 2) if fat > 0 else None

            analyzed.append({
                "product_name": p.get("product_name"),
                "price_rub": p.get("price_rub"),
                "weight_g": p.get("weight_g"),
                "price_per_100g": round(price_100g, 2),
                "rub_per_g_protein": rub_per_g_protein,
                "rub_per_g_fat": rub_per_g_fat,
            })

        # Sort best protein sources (lowest RUB per gram of protein)
        best_protein = sorted([a for a in analyzed if a["rub_per_g_protein"] is not None], key=lambda x: x["rub_per_g_protein"])
        best_fats = sorted([a for a in analyzed if a["rub_per_g_fat"] is not None], key=lambda x: x["rub_per_g_fat"])

        return {
            "all_products": analyzed,
            "best_protein_sources": best_protein[:3],
            "best_fat_sources": best_fats[:3]
        }

economy_agent = EconomyAgent()
