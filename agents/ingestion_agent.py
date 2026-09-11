import os
import re
import json
import urllib.request
from typing import List, Dict, Any

# ── Shared Gemini helper ───────────────────────────────────────────────────────
def _call_gemini(prompt: str, system: str = "", model: str = "gemini-3.6-flash") -> str:
    """Call Gemini API via google-genai SDK. Returns response text or '' on error."""
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return ""
    try:
        from google import genai
        from google.genai import types
        client = genai.Client(api_key=api_key)
        contents = []
        if system:
            contents.append(types.Content(role="user",    parts=[types.Part(text=system)]))
            contents.append(types.Content(role="model",   parts=[types.Part(text="Understood.")]))
        contents.append(types.Content(role="user", parts=[types.Part(text=prompt)]))
        resp = client.models.generate_content(model=model, contents=contents)
        return resp.text or ""
    except Exception as e:
        print(f"Gemini call error: {e}")
        return ""


class IngestionAgent:
    """
    Agent 1: Ingestion & LLM Structuring Agent
    Uses Gemini 2.0 Flash (primary) or Groq compound-mini (fallback) to extract
    normalized product names and quantities from freeform Russian text / voice transcripts.
    Falls back to regex parser if no LLM key is available.
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

    def _parse_llm(self, raw_input: str, image_bytes: bytes = None) -> List[Dict[str, Any]]:
        """
        Uses Gemini 2.0 Flash (primary) or Groq compound-mini (fallback) to extract
        multi-meal items, filtering out conversational filler and self-corrections.
        """
        sys_prompt = """You are a nutrition extraction AI. Analyze transcribed voice input about food in Russian.
Your task is to return a valid JSON object with key "meals": a list of meal objects.

RULES:
1. Ignore conversational filler words, self-corrections, questions ("Смотри", "ой не 9 а 19", "и что еще?", "белки там").
2. If the user mentions multiple meals in one voice note (e.g. "на завтрак...\" AND "сейчас на обед..."), split them into separate meal objects with "meal_type": ("Завтрак", "Обед", "Ужин", "Перекус").
3. For each food item, extract:
   - "product_name": normalized Russian name (e.g. "куриное яйцо", "макароны", "бекон", "майонез", "сосиски", "моцарелла light", "помидор", "масло оливковое")
   - "quantity_g": total net weight in grams (number, e.g. 3 eggs = 165g, 1 mozzarella = 125g, tomato = 50g)
    - "explicit_kcal": total calories for item if specified, or null
   - "explicit_protein": total protein in grams if specified, or null
   - "explicit_fat": total fat in grams if specified, or null
   - "explicit_carbs": total carbs in grams if specified, or null
4. If the user mentions burned active calories, workouts, or activities (e.g., "потратил 500 ккал на пробежке", "Тренировка 300 ккал", "Активность 400"), create an item with:
   - "product_name": "Активность"
   - "quantity_g": 0
   - "explicit_kcal": -500 (make sure it's negative)
   - "explicit_protein": 0, "explicit_fat": 0, "explicit_carbs": 0
   And set the "meal_type" of this block to "Активность".

Return ONLY valid JSON, no markdown, no explanation:
{"meals": [{"meal_type": "Завтрак", "items": [{"product_name": "куриное яйцо", "quantity_g": 165, "explicit_kcal": null, "explicit_protein": null, "explicit_fat": null, "explicit_carbs": null}]}]}"""

        # ── 1. Try Gemini (primary) ───────────────────────────────────────────
        gemini_key = os.getenv("GEMINI_API_KEY", "").strip()
        if gemini_key:
            try:
                from google import genai
                from google.genai import types
                client = genai.Client(api_key=gemini_key)
                model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
                user_parts = []
                if image_bytes:
                    user_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
                user_parts.append(types.Part.from_text(text=raw_input or "Что на этом фото?"))

                resp = client.models.generate_content(
                    model=model,
                    contents=[
                        types.Content(role="user",  parts=[types.Part.from_text(text=sys_prompt)]),
                        types.Content(role="model", parts=[types.Part.from_text(text="Understood. I will return only valid JSON.")]),
                        types.Content(role="user",  parts=user_parts),
                    ],
                    config=types.GenerateContentConfig(
                        temperature=0.1,
                        max_output_tokens=1000,
                    )
                )
                content = resp.text or ""
                json_match = re.search(r'(\{[\s\S]*\})', content)
                if json_match:
                    parsed = json.loads(json_match.group(1))
                    meals = parsed.get("meals", [])
                    if meals:
                        return meals
            except Exception as e:
                print(f"Gemini ingestion error: {e}")

        # ── 2. Fallback: Groq compound-mini ──────────────────────────────────
        groq_key = os.getenv("GROQ_API_KEY", "").strip() or os.getenv("SPEECH_API_KEY", "").strip()
        if groq_key and groq_key.startswith("gsk_"):
            payload = {
                "model": "groq/compound-mini",
                "messages": [
                    {"role": "system", "content": sys_prompt},
                    {"role": "user",   "content": raw_input}
                ],
                "max_tokens": 800
            }
            req = urllib.request.Request(
                "https://api.groq.com/openai/v1/chat/completions",
                data=json.dumps(payload).encode('utf-8'),
                headers={
                    "Authorization": f"Bearer {groq_key}",
                    "Content-Type": "application/json",
                    "User-Agent": "curl/7.68.0"
                },
                method="POST"
            )
            try:
                with urllib.request.urlopen(req, timeout=25) as resp:
                    data = json.loads(resp.read().decode('utf-8'))
                    choice = data.get("choices", [{}])[0]
                    msg = choice.get("message", {})
                    content = msg.get("content", "") or msg.get("reasoning", "")
                    json_match = re.search(r'(\{[\s\S]*\})', content)
                    if json_match:
                        parsed = json.loads(json_match.group(1))
                        return parsed.get("meals", [])
                    parsed = json.loads(content)
                    return parsed.get("meals", [])
            except Exception as e:
                print(f"Groq ingestion fallback error: {e}")

        return []

    def parse(self, raw_input: str, image_bytes: bytes = None) -> List[Dict[str, Any]]:
        """
        Parses raw text/speech input into structured food items.
        Tries LLM parsing first, falls back to regex matching.
        """
        if not raw_input or not raw_input.strip():
            return []

        # 1. Try LLM Parsing
        llm_meals = self._parse_llm(raw_input, image_bytes=image_bytes)
        if llm_meals:
            all_items = []
            for m in llm_meals:
                all_items.extend(m.get("items", []))
            if all_items:
                return all_items

        # 2. Fallback Regex Parsing
        text_lower = raw_input.lower()
        food_units_pattern = r'(\d+[\.,]?\d*)\s*(г|гр|грамм|г.|g|кг|kg|шт|штук|яиц|яйца|стакан|ложка|ст.л|ч.л|ккал|kcal|калорий)'
        has_unit = re.search(food_units_pattern, text_lower) is not None

        known_food_keywords = [
            "яйцо", "яйца", "творог", "макароны", "бекон", "майонез", "сосиски", "моцарелла",
            "сыр", "курица", "мясо", "рыба", "рис", "гречка", "хлеб", "масло", "помидор",
            "огурец", "яблоко", "банан", "молоко", "сметана", "протеин", "каша", "суп", "салат"
        ]
        has_known_food = any(kw in text_lower for kw in known_food_keywords)

        if not (has_unit or has_known_food):
            return []

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
