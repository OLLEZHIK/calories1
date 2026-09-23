import os
import re
import json
import urllib.request
from typing import List, Dict, Any, Optional, Tuple

try:
    import config  # noqa: F401 - ensures .env is loaded into os.environ
except ImportError:
    pass

# ── Shared Gemini helper ───────────────────────────────────────────────────────
def _call_gemini(prompt: str, system: str = "", model: str = "gemini-3.6-flash") -> str:
    """Call Gemini API via google-genai SDK. Returns response text or '' on error."""
    from gemini_client import get_genai_client
    client = get_genai_client()
    if not client:
        return ""
    try:
        from google.genai import types
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


def apply_fried_egg_oil_rule(items: List[Dict[str, Any]], raw_text: str = "") -> List[Dict[str, Any]]:
    """
    Automatic culinary rule: For every fried egg, automatically count 2g of butter/oil.
    E.g., 3 fried eggs = 3 eggs (165g) + 6g butter.
    """
    has_oil = any("масло" in (i.get("product_name") or "").lower() for i in items)
    if has_oil:
        return items

    raw_lower = (raw_text or "").lower()
    fried_eggs_count = 0

    for item in items:
        p_name = (item.get("product_name") or "").lower()
        is_egg = "яйц" in p_name
        is_fried = any(w in p_name for w in ["жарен", "яичниц", "глазунь", "омлет"]) or (is_egg and any(w in raw_lower for w in ["жарен", "яичниц", "глазунь", "пожар"]))
        if is_egg and is_fried:
            qty = float(item.get("quantity_g") or 55.0)
            count = max(1, int(round(qty / 55.0)))
            fried_eggs_count += count

    if fried_eggs_count > 0:
        oil_g = round(fried_eggs_count * 2.0, 1)
        items.append({
            "product_name": "масло сливочное",
            "quantity_g": oil_g,
            "category": "fats_oils",
            "explicit_kcal": None,
            "explicit_protein": None,
            "explicit_fat": None,
            "explicit_carbs": None
        })

    return items


def normalize_raw_food_names(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Culinary Rule: The user specifies portions and prices in RAW form.
    Maps 'шашлык свиной', 'шашлык из свинины', 'шашлык свиная шея', 'свиной стейк', etc.
    directly to 'свинина' so that raw pork nutrition and price are always applied.
    """
    for item in items:
        p_name = (item.get("product_name") or "").strip().lower()
        if "шашлык" in p_name and ("свин" in p_name or "ше" in p_name or "мяс" in p_name or p_name == "шашлык"):
            item["product_name"] = "свинина"
        elif any(k in p_name for k in ["свиной стейк", "стейк из свинины", "свиная вырезка", "свиная шея", "жареная свинина"]):
            item["product_name"] = "свинина"
    return items


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
2. Meal category ("meal_type": "Завтрак", "Обед", "Ужин", "Перекус"):
   - Match phrases like "к обеду", "на обед", "в обед", "пообедал" -> "Обед".
   - Match "к завтраку", "на завтрак", "утром" -> "Завтрак".
   - Match "к ужину", "на ужин", "вечером", "поужинал" -> "Ужин".
   - Match "к перекусу", "на перекус", "полдник", "десерт" -> "Перекус".
   If multiple meals are mentioned in one voice note (e.g. "на завтрак...\" AND "сейчас к обеду..."), split them into separate meal objects.
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
5. FRIED EGGS RULE: If the user mentions fried eggs ("жареное яйцо", "жареные яйца", "яичница", "глазунья", "пожарил N яиц"), extract the eggs (approx 55g per egg) AND automatically add a companion food item: "масло сливочное" with quantity_g = 2g per egg (e.g. 3 fried eggs = 3 eggs (165g) + 6g масло сливочное), unless user explicitly specified another oil amount.
6. RAW FOODS & PORK RULE (СЫРОЙ ВИД И СВИНИНА):
   - The user ALWAYS specifies weights, portions, and prices in RAW form (в сыром виде продуктов).
   - If the user mentions "шашлык свиной", "шашлык из свинины", "шашлык свиная шея", "свиная шея", "свиной стейк", "жареная свинина" or similar cooked pork dishes, ALWAYS normalize the product_name directly to "свинина". If the user says "шашлык свиной 100 г", this means exactly 100g of raw "свинина".

Return ONLY valid JSON, no markdown, no explanation:
{"meals": [{"meal_type": "Завтрак", "items": [{"product_name": "куриное яйцо", "quantity_g": 165, "explicit_kcal": null, "explicit_protein": null, "explicit_fat": null, "explicit_carbs": null}]}]}"""

        # ── 1. Try Gemini (primary) ───────────────────────────────────────────
        from gemini_client import get_genai_client
        client = get_genai_client()
        if client:
            try:
                from google.genai import types
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
                        max_output_tokens=2048,
                    )
                )
                content = resp.text or ""
                json_match = re.search(r'(\{[\s\S]*\})', content)
                if json_match:
                    parsed = json.loads(json_match.group(1))
                    meals = parsed.get("meals", [])
                    if meals:
                        for m in meals:
                            m["items"] = normalize_raw_food_names(apply_fried_egg_oil_rule(m.get("items", []), raw_input))
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
                        meals = parsed.get("meals", [])
                        for m in meals:
                            m["items"] = normalize_raw_food_names(apply_fried_egg_oil_rule(m.get("items", []), raw_input))
                        return meals
                    parsed = json.loads(content)
                    meals = parsed.get("meals", [])
                    for m in meals:
                        m["items"] = normalize_raw_food_names(apply_fried_egg_oil_rule(m.get("items", []), raw_input))
                    return meals
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
                product_name = re.sub(r'^(?:добавь|запиши|съел|съела|на\s+обед|к\s+обеду|в\s+обед|на\s+завтрак|к\s+завтраку|на\s+ужин|к\s+ужину|на\s+перекус|к\s+перекусу)\s+', '', product_name, flags=re.IGNORECASE).strip()

            if not product_name:
                product_name = part

            items.append({
                "product_name": product_name.strip(" -:()"),
                "quantity_g": quantity_g,
                "explicit_kcal": explicit_kcal,
                "raw_part": part
            })

        return normalize_raw_food_names(apply_fried_egg_oil_rule(items, raw_input))


ingestion_agent = IngestionAgent()


def _evaluate_fallback_coach(product_name: str, cal_100: float, p_100: float, f_100: float, c_100: float, category: str):
    prot_cal = p_100 * 4.0
    fat_cal = f_100 * 9.0
    carb_cal = c_100 * 4.0
    tot_cal = max(cal_100, prot_cal + fat_cal + carb_cal, 1.0)
    prot_ratio = prot_cal / tot_cal

    if category == "sweets" or (c_100 > 40 and f_100 > 15):
        score = 2
        verdict = f"Десерт с избытком сахаров ({c_100:.0f}г) и насыщенных жиров ({f_100:.0f}г). Провоцирует скачки инсулина и отложение жира. Употребляйте умеренно и редко."
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


def process_add_product(raw_text: str = "", image_bytes: bytes = None) -> str:
    """
    Multimodal AI product processing (via Gemini 3.6 Flash).
    Analyzes packaging photos, price tags, text, or voice transcripts to extract
    product name, weight, price in EUR (€), exact or estimated macros per 100g,
    and a personal trainer health/fitness utility rating (1-10 + verdict).
    Saves to both custom_products and product_prices tables in SQLite and Supabase.
    """
    from gemini_client import get_genai_client
    from database.db import save_custom_product, save_product_price

    client = get_genai_client()
    parsed_data = None

    if client:
        try:
            from google.genai import types
            model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

            sys_prompt = """You are an expert nutrition and personal fitness trainer AI.
The user is adding a food item to their personal database using a description, speech transcript, photo of packaging/nutrition table, photo of price tag, or photo of the food.

Your task is to analyze the input and extract or realistically estimate the product's nutritional values, price in EUR (€), and coach health utility score.

CRITICAL RULES:
1. "product_name": Clean, concise Russian name (e.g. "Торт Медовик", "Творог 5%", "Куриное филе").
   STRIP ALL conversational filler like "запиши в список", "добавь", "купил", "цена за", "стоит", etc.
2. "weight_g": Total net weight of the product or package in grams (e.g., 800g -> 800, 1kg -> 1000, 500г -> 500). If not mentioned or visible, default to 100.
3. "price": Numeric price in EUR (€). If currency is not stated or given in rubles/other, convert or normalize to numeric EUR (e.g., 7.5).
4. "currency": Always "€".
5. "calories_100g", "protein_100g", "fat_100g", "carbs_100g":
   - If visible on nutrition table in photo or stated by user in text, extract EXACT numbers per 100g.
   - If NOT stated, use your expert culinary and nutritional knowledge to provide ACCURATE, REALISTIC values per 100g for this specific product (e.g., for "Торт Медовик": calories ~390, protein ~5.5, fat ~16, carbs ~56).
6. "category": Choose best fit from: "meat", "fish", "eggs_dairy", "fats_oils", "vegetables", "fruit", "grains", "bakery", "sweets", "general".
7. "coach_score": An integer from 1 to 10 evaluating the product's nutritional fitness value and healthiness for a person aiming for fitness, weight loss, or muscle health:
   - 1-3: High sugar, trans/saturated fats, ultra-processed empty calories (e.g. sweets, fast food).
   - 4-6: Moderate or calorie-dense, acceptable in moderation.
   - 7-8: Wholesome nutrient-dense whole food (whole grains, vegetables, fruit, natural dairy).
   - 9-10: Elite fitness foods (lean chicken breast, white/salmon fish, eggs, low-fat cottage cheese).
8. "coach_verdict": 1-2 concise Russian sentences from a personal fitness trainer with clear advice on this product, analyzing the BJU ratio and fitness impact.
9. "is_estimated": true if macros were estimated by AI; false if read directly from package table/user input.

Return ONLY a valid JSON object in this exact format:
{
  "product_name": "Торт Медовик",
  "category": "sweets",
  "weight_g": 800.0,
  "price": 7.5,
  "currency": "€",
  "calories_100g": 390.0,
  "protein_100g": 5.5,
  "fat_100g": 16.0,
  "carbs_100g": 56.0,
  "coach_score": 2,
  "coach_verdict": "Высококалорийный десерт с избытком простых сахаров и насыщенных жиров при крайне низком белке. Провоцирует скачки инсулина и отложение жира.",
  "is_estimated": true
}"""

            user_parts = []
            if image_bytes:
                user_parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))
            user_parts.append(types.Part.from_text(text=raw_text or "Извлеки информацию о продукте, весе, цене в евро и КБЖУ, а также дай оценку тренера."))

            resp = client.models.generate_content(
                model=model,
                contents=[
                    types.Content(role="user", parts=[types.Part.from_text(text=sys_prompt)]),
                    types.Content(role="model", parts=[types.Part.from_text(text="Understood. I will return only valid JSON.")]),
                    types.Content(role="user", parts=user_parts),
                ],
                config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=2048)
            )
            raw_output = (resp.text or "").strip()
            if "```json" in raw_output:
                raw_output = raw_output.split("```json")[1].split("```")[0].strip()
            elif "```" in raw_output:
                raw_output = raw_output.split("```")[1].split("```")[0].strip()

            json_match = re.search(r'(\{[\s\S]*\})', raw_output)
            if json_match:
                parsed_data = json.loads(json_match.group(1))
        except Exception as e:
            print(f"Gemini process_add_product error: {e}")

    # Fallback if Gemini failed or is not configured
    if not parsed_data:
        p_info = ingestion_agent.parse_price_entry(raw_text or "")
        p_name = p_info["product_name"] if p_info else (raw_text or "Новый продукт")
        w_g = p_info["weight_g"] if p_info else 100.0
        price_val = p_info["price"] if p_info else None

        from agents.nutrition_agent import nutrition_agent
        calc = nutrition_agent.calculate([{"product_name": p_name, "quantity_g": 100}])
        m = calc[0] if calc else {"calories": 150, "protein_g": 5, "fat_g": 5, "carbs_g": 20, "category": "general"}
        parsed_data = {
            "product_name": p_name,
            "category": m.get("category", "general"),
            "weight_g": w_g,
            "price": price_val,
            "currency": "€",
            "calories_100g": m.get("calories", 150),
            "protein_100g": m.get("protein_g", 5),
            "fat_100g": m.get("fat_g", 5),
            "carbs_100g": m.get("carbs_g", 20),
            "coach_score": None,
            "coach_verdict": "",
            "is_estimated": True
        }

    product_name = (parsed_data.get("product_name") or "Продукт").strip()
    category = parsed_data.get("category", "general")
    weight_g = float(parsed_data.get("weight_g") or 100.0)
    if weight_g <= 0:
        weight_g = 100.0
    price = float(parsed_data["price"]) if parsed_data.get("price") is not None else None
    currency = "€"
    cal_100 = float(parsed_data.get("calories_100g") or 0.0)
    p_100 = float(parsed_data.get("protein_100g") or 0.0)
    f_100 = float(parsed_data.get("fat_100g") or 0.0)
    c_100 = float(parsed_data.get("carbs_100g") or 0.0)
    is_estimated = bool(parsed_data.get("is_estimated", False))

    # If calories/macros were not estimated or null, fill them in via nutrition agent
    if cal_100 <= 0 and p_100 <= 0 and f_100 <= 0 and c_100 <= 0:
        from agents.nutrition_agent import nutrition_agent
        calc = nutrition_agent.calculate([{"product_name": product_name, "quantity_g": 100}])
        if calc:
            m = calc[0]
            cal_100 = float(m.get("calories", 0))
            p_100 = float(m.get("protein_g", 0))
            f_100 = float(m.get("fat_g", 0))
            c_100 = float(m.get("carbs_g", 0))
            is_estimated = True

    # Coach evaluation: calculate fallback if missing
    coach_score = int(parsed_data.get("coach_score") or 0)
    coach_verdict = (parsed_data.get("coach_verdict") or "").strip()
    if coach_score <= 0 or not coach_verdict:
        f_score, f_verdict = _evaluate_fallback_coach(product_name, cal_100, p_100, f_100, c_100, category)
        coach_score = coach_score or f_score
        coach_verdict = coach_verdict or f_verdict

    # Save to custom_products
    save_custom_product(product_name, cal_100, p_100, f_100, c_100)

    # Save to product_prices
    price_val = price if price is not None else 0.0
    price_per_100g = round((price_val / weight_g) * 100, 2) if (price is not None and weight_g > 0) else None
    save_product_price(product_name, price_val, weight_g, category, p_100, f_100, c_100, cal_100, coach_score, coach_verdict)
    try:
        from agents.economy_agent import economy_agent
        economy_agent.audit_and_clean_catalog()
    except Exception as e:
        print(f"Catalog audit warning: {e}")

    # Calculate totals for entire package/weight
    ratio = weight_g / 100.0
    total_cal = int(round(cal_100 * ratio))
    total_p = round(p_100 * ratio, 1)
    total_f = round(f_100 * ratio, 1)
    total_c = round(c_100 * ratio, 1)

    macro_tag = " *(оценка ИИ)*" if is_estimated else ""

    if coach_score >= 8:
        score_badge = "🟢 Отличный выбор"
    elif coach_score >= 5:
        score_badge = "🟡 Умеренно"
    else:
        score_badge = "🔴 Не рекомендуется"

    price_str = f"{price:.2f} €" if price is not None else "Не указана"
    price_100_str = f" ({price_per_100g:.2f} € за 100г)" if price_per_100g is not None else ""

    # Build a single-item table for this product
    prod_data = [{
        "product_name": product_name,
        "calories_per_100g": cal_100,
        "protein_per_100g": p_100,
        "fat_per_100g": f_100,
        "carbs_per_100g": c_100,
        "price_per_100g": price_per_100g or 0,
        "coach_score": coach_score
    }]
    table_str = build_products_ascii_table(prod_data)

    lines = [
        "✅ **Продукт добавлен в таблицу базы!**\n",
        f"```\n{table_str}\n```",
    ]

    if abs(weight_g - 100.0) > 1.0 or (price is not None and price > 0):
        pkg_parts = []
        if abs(weight_g - 100.0) > 1.0:
            pkg_parts.append(f"Упаковка: **{int(round(weight_g))}г**")
        if price is not None and price > 0:
            pkg_parts.append(f"Цена: **{price:.2f} €**")
        if abs(weight_g - 100.0) > 1.0:
            pkg_parts.append(f"КБЖУ: **{total_cal} ккал** (Б:{total_p}г | Ж:{total_f}г | У:{total_c}г)")
        lines.append(f"📦 {' | '.join(pkg_parts)}")

    lines.append(f"🏋️ **Оценка полезности тренера:** {score_badge} **{coach_score}/10**")
    lines.append(f"💬 _{coach_verdict}_")
    lines.append(f"\n💾 Продукт сохранён в таблице. Теперь можно просто писать: *«съел 150г {product_name.lower()}»*.")
    lines.append("🌐 [Открыть Таблицу на Vercel](https://fatcaunter.vercel.app)")

    return "\n".join(lines)


def build_products_ascii_table(products: List[Dict[str, Any]]) -> str:
    """
    Renders an ASCII table with the 7 columns:
    1. Название продукта
    2. Ккал (на 100г)
    3. Белки
    4. Жиры
    5. Углеводы
    6. Цена за 100г (€)
    7. Оценка тренера (1-10)
    """
    w_name = 14
    w_cal = 5
    w_p = 4
    w_f = 4
    w_c = 4
    w_pr = 7
    w_sc = 7

    top    = f"┌{'─'*(w_name+2)}┬{'─'*(w_cal+2)}┬{'─'*(w_p+2)}┬{'─'*(w_f+2)}┬{'─'*(w_c+2)}┬{'─'*(w_pr+2)}┬{'─'*(w_sc+2)}┐"
    header = f"│ {'Продукт':<{w_name}} │ {'Ккал':>{w_cal}} │ {'Б':>{w_p}} │ {'Ж':>{w_f}} │ {'У':>{w_c}} │ {'Цена':>{w_pr}} │ {'Тренер':^{w_sc}} │"
    sep    = f"├{'─'*(w_name+2)}┼{'─'*(w_cal+2)}┼{'─'*(w_p+2)}┼{'─'*(w_f+2)}┼{'─'*(w_c+2)}┼{'─'*(w_pr+2)}┼{'─'*(w_sc+2)}┤"
    bot    = f"└{'─'*(w_name+2)}┴{'─'*(w_cal+2)}┴{'─'*(w_p+2)}┴{'─'*(w_f+2)}┴{'─'*(w_c+2)}┴{'─'*(w_pr+2)}┴{'─'*(w_sc+2)}┘"

    rows = [top, header, sep]
    for p in products:
        name = (p.get("product_name") or "Продукт").capitalize()
        if len(name) > w_name:
            name = name[:w_name-1] + "…"
        cal = str(int(round(float(p.get("calories_per_100g") or 0))))
        prot = str(round(float(p.get("protein_per_100g") or 0), 1) if float(p.get("protein_per_100g") or 0) % 1 else int(round(float(p.get("protein_per_100g") or 0))))
        fat = str(round(float(p.get("fat_per_100g") or 0), 1) if float(p.get("fat_per_100g") or 0) % 1 else int(round(float(p.get("fat_per_100g") or 0))))
        carb = str(round(float(p.get("carbs_per_100g") or 0), 1) if float(p.get("carbs_per_100g") or 0) % 1 else int(round(float(p.get("carbs_per_100g") or 0))))
        price_100 = float(p.get("price_per_100g") or 0)
        pr_str = f"{price_100:.2f}€" if price_100 > 0 else "-"
        score = int(p.get("coach_score") or p.get("efficiency_score") or 5)
        badge = "🟢" if score >= 8 else ("🟡" if score >= 5 else "🔴")
        sc_str = f"{badge}{score:>2}/10"

        row = f"│ {name:<{w_name}} │ {cal:>{w_cal}} │ {prot:>{w_p}} │ {fat:>{w_f}} │ {carb:>{w_c}} │ {pr_str:>{w_pr}} │ {sc_str:^{w_sc}} │"
        rows.append(row)
    rows.append(bot)
    return "\n".join(rows)


def format_products_catalog() -> str:
    """Format the full list of products stored in database as a table with macros in 100g, EUR price, and coach rating."""
    from database.db import get_product_prices
    products = get_product_prices()
    if not products:
        return (
            "📋 **В вашей базе пока нет продуктов.**\n\n"
            "Нажмите кнопку **«➕ Добавить продукт»**, чтобы добавить первый продукт (текстом, голосом или фото)!"
        )

    table_str = build_products_ascii_table(products)

    lines = [
        "📊 **Таблица продуктов (пищевая ценность на 100 г):**\n",
        f"```\n{table_str}\n```\n",
        "💬 **Оценка полезности и вердикты тренера:**"
    ]

    for i, p in enumerate(products, 1):
        name = p.get("product_name", "Продукт").capitalize()
        score = int(p.get("coach_score") or p.get("efficiency_score") or 5)
        badge = "🟢" if score >= 8 else ("🟡" if score >= 5 else "🔴")
        verdict = p.get("coach_verdict") or ""
        lines.append(f"• **{name}** ({badge} {score}/10): _{verdict}_")

    lines.append("\n💡 Чтобы добавить продукт, нажмите кнопку **«➕ Добавить продукт»**.")
    lines.append("🌐 [Открыть онлайн-таблицу на Vercel](https://fatcaunter.vercel.app)")
    return "\n".join(lines)


def fetch_internet_product_nutrition(product_name: str) -> Dict[str, Any]:
    """
    Searches or estimates accurate commercial nutritional parameters (per 100g),
    typical package weight, category, and coach rating for a food product via Gemini AI or OpenFoodFacts.
    """
    from gemini_client import get_genai_client
    from database.db import validate_product_values, estimate_product_nutrition

    cleaned_name = product_name.strip()
    client = get_genai_client()

    if client:
        try:
            from google.genai import types
            model = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

            prompt = f"""You are an expert nutrition database and personal fitness coach.
The user is adding or has eaten a food item: "{cleaned_name}".

Find or accurately estimate the actual commercial nutritional values per 100g in Europe/CIS:
- "product_name": Clean Russian title (e.g. "Протеиновый пудинг Ehrmann", "Сыр Сулугуни", "Овсяное молоко").
- "calories_100g": Energy in kcal per 100g.
- "protein_100g": Protein in grams per 100g.
- "fat_100g": Fat in grams per 100g.
- "carbs_100g": Carbohydrates in grams per 100g.
- "weight_g": Standard package or typical portion net weight in grams (e.g. 200 for pudding, 100 for bar/chocolate, 500 for milk, 800 for cake. Default 100 if unknown).
- "category": Best match among: "meat", "fish", "eggs_dairy", "fats_oils", "vegetables", "fruit", "grains", "bakery", "sweets", "general".
- "coach_score": Fitness rating from 1 to 10 (1-3 empty calories/high sugar/trans-fat, 4-6 moderate, 7-8 wholesome whole food, 9-10 top fitness protein food).
- "coach_verdict": 1-2 concise Russian sentences analyzing the BJU ratio and fitness suitability.

Return ONLY a valid JSON object:
{{
  "product_name": "{cleaned_name}",
  "calories_100g": 120.0,
  "protein_100g": 10.0,
  "fat_100g": 1.5,
  "carbs_100g": 15.0,
  "weight_g": 200.0,
  "category": "eggs_dairy",
  "coach_score": 8,
  "coach_verdict": "Отличный источник белка с низким содержанием жира."
}}"""

            resp = client.models.generate_content(
                model=model,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1, max_output_tokens=1000)
            )
            raw = (resp.text or "").strip()
            if "```json" in raw:
                raw = raw.split("```json")[1].split("```")[0].strip()
            elif "```" in raw:
                raw = raw.split("```")[1].split("```")[0].strip()

            m = re.search(r'(\{[\s\S]*\})', raw)
            if m:
                data = json.loads(m.group(1))
                cal = float(data.get("calories_100g") or 0.0)
                p = float(data.get("protein_100g") or 0.0)
                f = float(data.get("fat_100g") or 0.0)
                c = float(data.get("carbs_100g") or 0.0)
                w = float(data.get("weight_g") or 100.0)
                if w <= 0:
                    w = 100.0
                score = int(data.get("coach_score") or 6)
                cat = data.get("category") or "general"
                verdict = (data.get("coach_verdict") or "").strip()
                val = validate_product_values(
                    protein_100g=p,
                    fat_100g=f,
                    carbs_100g=c,
                    calories_100g=cal,
                    weight_g=w,
                    coach_score=score
                )
                return {
                    "product_name": data.get("product_name") or cleaned_name,
                    "calories_100g": val["calories_100g"],
                    "protein_100g": val["protein_100g"],
                    "fat_100g": val["fat_100g"],
                    "carbs_100g": val["carbs_100g"],
                    "weight_g": val["weight_g"],
                    "category": cat,
                    "coach_score": val["coach_score"],
                    "coach_verdict": verdict or "Питательный продукт, подходит для сбалансированного рациона."
                }
        except Exception as e:
            print(f"fetch_internet_product_nutrition Gemini error: {e}")

    # Fallback to local / OpenFoodFacts calculation
    est = estimate_product_nutrition(cleaned_name)
    return {
        "product_name": cleaned_name,
        "calories_100g": est.get("calories_100g", 150),
        "protein_100g": est.get("protein_100g", 5.0),
        "fat_100g": est.get("fat_100g", 5.0),
        "carbs_100g": est.get("carbs_100g", 20.0),
        "weight_g": 100.0,
        "category": est.get("category", "general"),
        "coach_score": est.get("coach_score", 6),
        "coach_verdict": est.get("coach_verdict", "Информация рассчитана по справочным данным.")
    }


def parse_entered_price(text: str) -> Optional[float]:
    """
    Extracts numeric price from user response like '2.50', '2,5 евро', '150 руб', '3€', etc.
    Returns float or None if cancelled/invalid.
    """
    t = text.strip().lower()
    if any(w in t for w in ["отмена", "отменить", "пропустить", "skip", "не надо", "нет"]):
        return None

    # Handle rubles: e.g. "200 руб", "150 рублей", "200р" -> convert roughly to EUR (~100 RUB = 1 EUR)
    m_rub = re.search(r'(\d+(?:[.,]\d+)?)\s*(?:руб|р\b)', t)
    if m_rub:
        rub_val = float(m_rub.group(1).replace(",", "."))
        return round(max(0.01, rub_val / 100.0), 2)

    # Check standard euro or naked number: e.g. "2.5", "2,50", "2.50 €", "2.5 евро", "€2.5"
    m = re.search(r'(\d+(?:[.,]\d+)?)', t)
    if m:
        try:
            val = float(m.group(1).replace(",", "."))
            if val > 0:
                return round(val, 2)
        except ValueError:
            pass
    return None


def format_new_product_prompt(product_info: Dict[str, Any]) -> Tuple[str, Dict[str, Any]]:
    """
    Formats Telegram markdown message asking user to confirm product KBJU and enter price.
    Returns (message_text, inline_markup_dict).
    """
    name = (product_info.get("product_name") or "Продукт").strip().capitalize()
    cal = int(round(float(product_info.get("calories_100g") or 0)))
    p = round(float(product_info.get("protein_100g") or 0), 1)
    f = round(float(product_info.get("fat_100g") or 0), 1)
    c = round(float(product_info.get("carbs_100g") or 0), 1)
    w = int(round(float(product_info.get("weight_g") or 100)))
    score = int(product_info.get("coach_score") or 7)
    verdict = (product_info.get("coach_verdict") or "").strip()

    score_emoji = "🟢" if score >= 8 else ("🟡" if score >= 5 else "🔴")

    msg = (
        f"🔍 **Обнаружен новый продукт, которого нет в каталоге!**\n\n"
        f"Вы имеете в виду: **«{name}»**?\n\n"
        f"📊 **КБЖУ из сети (на 100г)**:\n"
        f"• 🔥 Калории: **{cal} ккал**\n"
        f"• 🥩 Белки: **{p} г**\n"
        f"• 🥑 Жиры: **{f} г**\n"
        f"• 🍚 Углеводы: **{c} г**\n"
        f"{score_emoji} *Тренер ({score}/10)*: _{verdict}_\n\n"
        f"💰 **Введите цену** за упаковку ({w}г) или за 100г (например: *«2.50»* или *«2.5 евро»*), и я автоматически сохраню его в каталог!\n\n"
        f"_(Или нажмите кнопку «Пропустить» ниже)_"
    )
    markup = {
        "inline_keyboard": [
            [{"text": "❌ Пропустить добавление цены", "callback_data": "skip_pending_product"}]
        ]
    }
    return msg, markup

