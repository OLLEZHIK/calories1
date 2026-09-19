import json
import io
import sys
from http.server import BaseHTTPRequestHandler

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from api.index import handler

class MockRequest:
    def __init__(self, body_bytes=b""):
        self.rfile = io.BytesIO(body_bytes)
        self.wfile = io.BytesIO()

def call_handler(method, path, body=None):
    body_bytes = json.dumps(body).encode("utf-8") if body else b""
    h = handler.__new__(handler)
    h.command = method
    h.path = path
    h.rfile = io.BytesIO(body_bytes)
    h.wfile = io.BytesIO()
    h.headers = {
        "Content-Length": str(len(body_bytes)),
        "Content-Type": "application/json"
    }
    
    # Capture send_response and headers
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

def test_api():
    print("=== Testing API Products Endpoints ===")
    
    # 1. GET /api/products
    status, data = call_handler("GET", "/api/products")
    assert status == 200, f"Expected 200, got {status}"
    assert data["status"] == "success"
    print(f"✓ GET /api/products OK: {len(data['products'])} products returned")

    # 2. POST /api/products/estimate
    status, data = call_handler("POST", "/api/products/estimate", {"product_name": "лосось стейк", "category": "fish"})
    assert status == 200, f"Expected 200, got {status}"
    assert data["data"]["calories_100g"] > 0
    print(f"✓ POST /api/products/estimate OK: {data['data']['product_name']} -> {data['data']['calories_100g']} kcal, P={data['data']['protein_100g']}g, score={data['data']['coach_score']}/10")

    # 3. POST /api/products (Add)
    prod_name = "тестовый сыр чеддер"
    status, data = call_handler("POST", "/api/products", {
        "action": "add",
        "product_name": prod_name,
        "price_rub": 3.49,
        "weight_g": 200.0,
        "category": "eggs_dairy",
        "protein_100g": 25.0,
        "fat_100g": 33.0,
        "carbs_100g": 1.0,
        "calories_100g": 401.0,
        "coach_score": 6,
        "coach_verdict": "Высокая жирность, но хороший белок."
    })
    assert status == 200, f"Add failed with status {status}: {data}"
    print(f"✓ POST /api/products (Add) OK: {data['message']}")

    # 4. POST /api/products/update
    status, data = call_handler("POST", "/api/products/update", {
        "product_name": prod_name,
        "price_rub": 3.19,
        "weight_g": 200.0,
        "category": "eggs_dairy",
        "protein_100g": 26.0,
        "fat_100g": 32.0,
        "carbs_100g": 0.5,
        "calories_100g": 394.0,
        "coach_score": 7,
        "coach_verdict": "Обновленный чеддер."
    })
    assert status == 200, f"Update failed with status {status}: {data}"
    print(f"✓ POST /api/products/update OK: {data['message']}")

    # 5. POST /api/products/delete
    status, data = call_handler("POST", "/api/products/delete", {
        "product_name": prod_name
    })
    assert status == 200, f"Delete failed with status {status}: {data}"
    print(f"✓ POST /api/products/delete OK: {data['message']}")

    print("\n=== ALL API PRODUCT TESTS PASSED! ===")

if __name__ == "__main__":
    test_api()
