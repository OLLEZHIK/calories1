# AGENTS.md - Antigravity Agent Guidelines

- All meal tracking logic is orchestrated by 6 specialized agents located in `agents/`.
- Database access is handled via `database/db.py` (SQLite or Supabase Cloud DB).
- `EconomyAgent` guards product/price tables against duplicates and validates macro/calorie physical consistency ($4P+9F+4C$).
- To log a meal or run an analysis, invoke `python mcp_server.py --add "<meal_text>"`.
- To audit the product catalog for duplicates and validity, invoke `python mcp_server.py --audit`.
- Keep the Web Dashboard (`dashboard/index.html`) synced whenever meals, products, or coach tips are updated.
