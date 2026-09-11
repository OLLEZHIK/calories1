import os
import re
import json
import urllib.request
from typing import List, Dict, Any

class IngestionAgent:
    """
    Agent 1: Ingestion & LLM Structuring Agent
    Uses LLM (Groq / Gemini) to extract normalized product names and quantities in grams 
    from freeform Russian text or voice transcripts, with a robust regex fallback parser.
    """
    def __init__(self):
        self.name = "IngestionAgent"

    def parse_price_entry(self, raw_input: str) -> Dict[str, Any]:
        """
        Detects if user is logging a product price, e.g.:
        '500г макарон стоят 1.5€' or 'творог 200г 120 руб' or 'курица 1кг 4 евро'
        """
        price_match = re.search(
            r'(\d+[\.,]?\d*)\s*(€|\$|евро|euro|руб|рублей|р|rub)', 
            raw_input, 
            re.IGNORECASE
        )
        if not price_match:
            return None

        price_val = float(price_match.group(1).replace(',', '.'))
        currency = price_match.group(2).lower()

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

    def _parse_llm(self, raw_input: str) -> List[Dict[str, Any]]:
        """Uses LLM (Groq / Gemini) to extract food items and weight in grams."""
        groq_key = os.getenv("GROQ_API_KEY", "").strip() or os.getenv("SPEECH_API_KEY", "").strip()
        if not groq_key or not groq_key.startswith("gsk_"):
            return []

        sys_prompt = (
            "Ты — ИИ-нутрициолог. Извлеки список всех продуктов и их массу из описания еды на русском языке.\n"
            "Верни ТОЛЬКО валидный JSON объект формата:\n"
            '{"items": [{"product_name": "название продукта", "quantity_g": число_в_граммах}]}\n'
            "Пример перевода: 1 яйцо = 55г, 1 стакан = 250г, 1 ст.л = 20г, 1 порция = 200г, 1 шт = 100г.\n"
            "Не добавляй никакой другой текст вне JSON."
        )

        payload = {
            "model": "openai/gpt-oss-20b",
            "messages": [
                {"role": "system", "content": sys_prompt},
                {"role": "user", "content": raw_input}
            ],
            "max_tokens": 350,
            "response_format": {"type": "json_object"}
        }

        req = urllib.request.Request(
            "https://api.groq.com/openai/v1/chat/completions",
            data=json.dumps(payload).encode('utf-8'),
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CaloriesAI/1.0"
            },
            method="POST"
        )

        try:
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                content = data["choices"][0]["message"]["content"]
                parsed = json.loads(content)
                items = parsed.get("items", [])
                result = []
                for item in items:
                    name = item.get("product_name", "").strip()
                    qty = float(item.get("quantity_g", 100.0))
                    if name and qty > 0:
                        result.append({"product_name": name, "quantity_g": qty, "explicit_kcal": None})
                return result
        except Exception as e:
            print(f"LLM Ingestion parse warning: {e}")
            return []

    def parse(self, raw_input: str) -> List[Dict[str, Any]]:
        """
        Parses raw text/speech input into structured food items.
        Tries LLM parsing first, falls back to regex matching.
        """
        if not raw_input or not raw_input.strip():
            return []

        # 1. Try LLM Parsing
        llm_items = self._parse_llm(raw_input)
        if llm_items:
            return llm_items

        # 2. Fallback Regex Parsing
        items = []
        parts = re.split(r'[,;\n\+]|\bи\b|\band\b', raw_input, flags=re.IGNORECASE)

        for part in parts:
            part = part.strip()
            if not part:
                continue

            explicit_kcal = None
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

