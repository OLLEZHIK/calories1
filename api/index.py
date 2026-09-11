from http.server import BaseHTTPRequestHandler
import json
from database.db import get_today_summary, get_recent_meals, get_product_prices
from agents.coach_agent import coach_agent

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/api/summary' or self.path == '/api/summary/':
            summary = get_today_summary()
            meals = get_recent_meals(limit=10)
            coach = coach_agent.analyze()
            products = get_product_prices()
            
            payload = {
                "status": "success",
                "summary": summary,
                "meals": meals,
                "coach": coach,
                "products": products
            }

            
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(payload, ensure_ascii=False).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
            self.wfile.write(b'{"error": "Not Found"}')
