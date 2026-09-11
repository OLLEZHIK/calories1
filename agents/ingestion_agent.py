import re
from typing import List, Dict, Any

class IngestionAgent:
    """
    Agent 1: Ingestion & Structuring Agent
    Converts raw text, voice transcripts, or photo captions into structured meal ingredient items
    AND detects product price entries (e.g. '500г макарон стоят 1.50€').
    """
    def __init__(self):
        self.name = "IngestionAgent"

    def parse_price_entry(self, raw_input: str) -> Dict[str, Any]:
        """
        Detects if user is logging a product price, e.g.:
        '500г макарон стоят 1.5€' or 'творог 200г 120 руб' or 'курица 1кг 4 евро'
        Returns price dictionary or None.
        """
        # Look for currency symbols or words: €, $, евро, euro, руб, р, rub
        price_match = re.search(
            r'(\d+[\.,]?\d*)\s*(€|\$|евро|euro|руб|рублей|р|rub)', 
            raw_input, 
            re.IGNORECASE
        )
        if not price_match:
            return None

        price_val = float(price_match.group(1).replace(',', '.'))
        currency = price_match.group(2).lower()

        # Look for weight (500g, 1kg, 200 грамм)
        weight_match = re.search(
            r'(\d+[\.,]?\d*)\s*(г|гр|грамм|г.|g|кг|kg|шт|штук)?', 
            raw_input, 
            re.IGNORECASE
        )
        weight_g = 100.0
        if weight_match:
            w_val = float(weight_match.group(1).replace(',', '.'))
            w_unit = (weight_match.group(2) or '').lower()
            if w_unit in ['кг', 'kg']:
                weight_g = w_val * 1000.0
            elif w_val > 0 and w_val != price_val:
                weight_g = w_val

        # Clean product name by stripping price and weight terms
        cleaned_name = re.sub(
            r'(\d+[\.,]?\d*)\s*(€|\$|евро|euro|руб|рублей|р|rub|стоят|стоимость|цена|за|г|гр|грамм|г.|g|кг|kg)', 
            '', 
            raw_input, 
            flags=re.IGNORECASE
        ).strip(" -:,.на")

        if not cleaned_name:
            cleaned_name = "Продукт"

        return {
            "product_name": cleaned_name,
            "price": price_val,
            "currency": "€" if currency in ["€", "евро", "euro"] else ("$" if currency == "$" else "руб"),
            "weight_g": weight_g,
            "price_per_100g": round((price_val / weight_g) * 100, 3)
        }

    def parse(self, raw_input: str) -> List[Dict[str, Any]]:
        """
        Parses input string into a list of dictionaries with product_name, quantity_g, and explicit macros if given.
        """
        if not raw_input or not raw_input.strip():
            return []

        items = []
        parts = re.split(r'[,;\n\+]|\bи\b|\band\b', raw_input, flags=re.IGNORECASE)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Check if explicit macros are given e.g. "творог 200г (150ккал, 30g белков)"
            explicit_kcal = None
            explicit_p = None
            explicit_f = None
            explicit_c = None

            kcal_match = re.search(r'(\d+[\.,]?\d*)\s*(ккал|kcal|калорий)', part, re.IGNORECASE)
            if kcal_match:
                explicit_kcal = float(kcal_match.group(1).replace(',', '.'))

            weight_match = re.search(r'(\d+[\.,]?\d*)\s*(г|гр|грамм|г.|g|кг|kg|шт|штук|яиц|яйца|стакан|ложка|ст.л|ч.л)?', part, re.IGNORECASE)
            
            product_name = part
            quantity_g = 100.0

            if weight_match:
                val = float(weight_match.group(1).replace(',', '.'))
                unit = (weight_match.group(2) or '').lower()

                if unit in ['кг', 'kg']:
                    quantity_g = val * 1000
                elif unit in ['шт', 'штук', 'яиц', 'яйца']:
                    quantity_g = val * 55.0
                elif unit in ['ст.л', 'ложка']:
                    quantity_g = val * 20.0
                elif unit in ['ч.л']:
                    quantity_g = val * 7.0
                elif unit in ['стакан']:
                    quantity_g = val * 250.0
                elif val > 0:
                    quantity_g = val

                product_name = re.sub(r'(\d+[\.,]?\d*)\s*(г|гр|грамм|г.|g|кг|kg|шт|штук|яиц|яйца|стакан|ложка|ст.л|ч.л)?', '', part, flags=re.IGNORECASE).strip()

            if not product_name:
                product_name = part

            items.append({
                "product_name": product_name.strip(" -:()"),
                "quantity_g": quantity_g,
                "explicit_kcal": explicit_kcal,
                "raw_part": part
            })

        return items

ingestion_agent = IngestionAgent()
