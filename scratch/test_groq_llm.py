import os
import sys
import json
import urllib.request

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


key = os.getenv("GROQ_API_KEY", "")

url = "https://api.groq.com/openai/v1/chat/completions"

sys_prompt = """Ты — ИИ-нутрициолог. Извлеки список всех продуктов и их массу из описания еды на русском языке.
Верни ТОЛЬКО валидный JSON с ключом "items", где каждый элемент содержит:
- "product_name": нормализованное название продукта на русском языке (например "куриное яйцо", "кефир", "куриное филе").
- "quantity_g": вес в граммах (число). Переводи штуки и порции в граммы (1 яйцо = 55г, 1 стакан = 250г, 1 ст.л = 20г, 1 шт = 100г).
"""

raw_text = "Я съел 3 яйца, 150г куриного филе и стакан кефира"
payload = {
    "model": "openai/gpt-oss-20b",
    "messages": [
        {"role": "system", "content": sys_prompt},
        {"role": "user", "content": raw_text}
    ],
    "max_tokens": 300,
    "response_format": {"type": "json_object"}

}


req = urllib.request.Request(
    url,
    data=json.dumps(payload).encode("utf-8"),
    headers={
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) CaloriesAI/1.0"
    }
)

try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        content = data["choices"][0]["message"]["content"]
        print("GROQ LLM PARSED RESULT:")
        print(content.encode('utf-8', errors='ignore').decode('utf-8'))
except Exception as e:
    import traceback
    err_body = ""
    if hasattr(e, "read"):
        try:
            err_body = e.read().decode('utf-8')
        except Exception:
            pass
    print("FAIL:", e, err_body, traceback.format_exc())


