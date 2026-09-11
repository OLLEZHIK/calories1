import re
from typing import List, Dict, Any

class IngestionAgent:
    """
    Agent 1: Ingestion & Structuring Agent
    Converts raw text, voice transcripts, or photo captions into structured meal ingredient items with quantities.
    """
    def __init__(self):
        self.name = "IngestionAgent"

    def parse(self, raw_input: str) -> List[Dict[str, Any]]:
        """
        Parses input string into a list of dictionaries with product_name and quantity_g.
        Uses rule-based heuristics and fallback AI pattern recognition.
        """
        if not raw_input or not raw_input.strip():
            return []

        items = []
        # Split by commas, 'and', 'плюс', newlines or 'и'
        parts = re.split(r'[,;\n\+]|\bи\b|\band\b', raw_input, flags=re.IGNORECASE)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            # Look for weight patterns like '500г', '200 грамм', '5 шт', '3 яйца'
            weight_match = re.search(r'(\d+[\.,]?\d*)\s*(г|гр|грамм|г.|g|кг|kg|шт|штук|яиц|яйца|стакан|ложка|ст.л|ч.л)?', part, re.IGNORECASE)
            
            product_name = part
            quantity_g = 100.0  # default assumption 100g

            if weight_match:
                val = float(weight_match.group(1).replace(',', '.'))
                unit = (weight_match.group(2) or '').lower()

                if unit in ['кг', 'kg']:
                    quantity_g = val * 1000
                elif unit in ['шт', 'штук', 'яиц', 'яйца']:
                    # Assuming average piece is ~55g (like an egg)
                    quantity_g = val * 55.0
                elif unit in ['ст.л', 'ложка']:
                    quantity_g = val * 20.0
                elif unit in ['ч.л']:
                    quantity_g = val * 7.0
                elif unit in ['стакан']:
                    quantity_g = val * 250.0
                elif val > 0:
                    quantity_g = val

                # Clean product name by removing the quantity part
                product_name = re.sub(r'(\d+[\.,]?\d*)\s*(г|гр|грамм|г.|g|кг|kg|шт|штук|яиц|яйца|стакан|ложка|ст.л|ч.л)?', '', part, flags=re.IGNORECASE).strip()

            if not product_name:
                product_name = part

            items.append({
                "product_name": product_name.strip(" -:"),
                "quantity_g": quantity_g,
                "raw_part": part
            })

        return items

ingestion_agent = IngestionAgent()
