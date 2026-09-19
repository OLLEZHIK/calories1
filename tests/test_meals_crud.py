import sys
import io
import json
from datetime import datetime

# Ensure UTF-8 output encoding for Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from api.index import handler
from database.db import (
    add_meal_entry, update_meal_item, delete_meal_item,
    get_recent_meals, get_today_summary,
    create_user, create_session, login_user
)

_TEST_TOKEN = None

def get_test_token():
    global _TEST_TOKEN
    if not _TEST_TOKEN:
        u = login_user("test_crud_user", "test_pass_123")
        if not u:
            try:
                u = create_user("test_crud_user", "test_pass_123")
            except Exception:
                u = login_user("test_crud_user", "test_pass_123")
        _TEST_TOKEN = create_session(u["user_id"] if u else 1, device_name="TestRunner")
    return _TEST_TOKEN

def call_handler(method, path, body=None):
    body_bytes = json.dumps(body).encode("utf-8") if body else b""
    h = handler.__new__(handler)
    h.command = method
    h.path = path
    h.rfile = io.BytesIO(body_bytes)
    h.wfile = io.BytesIO()
    h.headers = {
        "Content-Length": str(len(body_bytes)),
        "Content-Type": "application/json",
        "Authorization": f"Bearer {get_test_token()}"
    }
    
    h._headers_sent = []
    def mock_send_response(code):
        h._status_code = code
    def mock_send_header(k, v):
        h._headers_sent.append((k, v))
    def mock_end_headers():
        pass
    h.send_response = mock_send_response
    h.send_header = mock_send_header
    h.end_headers = mock_end_headers

    if method == "GET":
        h.do_GET()
    elif method == "POST":
        h.do_POST()
    elif method == "PUT":
        h.do_PUT()
    elif method == "DELETE":
        h.do_DELETE()

    res_bytes = h.wfile.getvalue()
    res_data = json.loads(res_bytes.decode("utf-8")) if res_bytes else {}
    return h._status_code, res_data

def test_meals_crud():
    print("=== 1. Testing DB Meals CRUD Functions ===")
    today = datetime.now().strftime("%Y-%m-%d")
    
    # 1. Add structured meal
    items = [
        {"product_name": "Тестовый завтрак омлет", "quantity_g": 150, "calories": 225, "protein_g": 18, "fat_g": 15, "carbs_g": 3, "category": "eggs_dairy"}
    ]
    meal_id = add_meal_entry(meal_type="Завтрак", items=items, target_date=today)
    assert meal_id > 0, "Meal ID must be > 0"
    print(f"✓ add_meal_entry created meal ID {meal_id}")

    recent = get_recent_meals(limit=5, target_date=today)
    found_meal = next((m for m in recent if m["id"] == meal_id), None)
    assert found_meal is not None, "Created meal must be present in recent meals"
    assert len(found_meal["items"]) == 1
    item = found_meal["items"][0]
    item_id = item["id"]
    print(f"✓ Found meal item ID {item_id}: {item['product_name']} ({item['quantity_g']}g, {item['calories']} kcal)")

    # 2. Update meal item
    updated = update_meal_item(
        item_id=item_id,
        product_name="Тестовый омлет с зеленью",
        quantity_g=200,
        calories=300,
        protein_g=24,
        fat_g=20,
        carbs_g=4,
        category="eggs_dairy",
        meal_type="Завтрак"
    )
    assert updated["product_name"] == "Тестовый омлет с зеленью"
    assert updated["quantity_g"] == 200
    assert updated["calories"] == 300
    print("✓ update_meal_item updated name, weight, and macros successfully")

    # 3. Delete meal item
    del_ok = delete_meal_item(item_id)
    assert del_ok is True
    print(f"✓ delete_meal_item deleted item ID {item_id}")

    # Verify parent meal was cascaded
    recent_after = get_recent_meals(limit=10, target_date=today)
    assert not any(m["id"] == meal_id for m in recent_after), "Parent meal should be cascaded when 0 items remain"
    print("✓ Cascade deletion of parent meal verified")

    print("\n=== 2. Testing API /api/meals Endpoints ===")
    # 4. POST /api/meals/add
    add_payload = {
        "meal_type": "Обед",
        "date": today,
        "items": [
            {"product_name": "Тестовая индейка гриль", "quantity_g": 180, "calories": 270, "protein_g": 45, "fat_g": 6, "carbs_g": 0, "category": "meat"}
        ]
    }
    status, res_add = call_handler("POST", "/api/meals/add", add_payload)
    assert status == 200, f"Expected 200, got {status}: {res_add}"
    assert res_add["status"] == "success"
    api_meal_id = res_add["meal_id"]
    print(f"✓ POST /api/meals/add created meal ID {api_meal_id}")

    # Retrieve added item
    meals_list = res_add.get("meals", [])
    added_meal = next((m for m in meals_list if m["id"] == api_meal_id or "индейка" in m.get("raw_input", "")), None)
    assert added_meal is not None, f"Could not find added meal in {meals_list}"
    api_item_id = added_meal["items"][0]["id"]

    # 5. POST /api/meals/update
    update_payload = {
        "item_id": api_item_id,
        "product_name": "Тестовая индейка су-вид",
        "quantity_g": 220,
        "calories": 330,
        "protein_g": 55,
        "fat_g": 7,
        "carbs_g": 0,
        "category": "meat",
        "meal_type": "Обед",
        "date": today
    }
    status, res_update = call_handler("POST", "/api/meals/update", update_payload)
    assert status == 200, f"Expected 200, got {status}: {res_update}"
    assert res_update["status"] == "success"
    assert res_update["item"]["product_name"] == "Тестовая индейка су-вид"
    print(f"✓ POST /api/meals/update updated item ID {api_item_id}")

    # 6. DELETE /api/meals
    status, res_del = call_handler("DELETE", "/api/meals", {"item_id": api_item_id, "date": today})
    assert status == 200, f"Expected 200, got {status}: {res_del}"
    assert res_del["status"] == "success"
    print(f"✓ DELETE /api/meals deleted item ID {api_item_id}")

    print("\n🎉 All Meals CRUD tests passed flawlessly!")

if __name__ == "__main__":
    test_meals_crud()
