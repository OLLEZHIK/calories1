# AGENTS.md - Antigravity Agent Guidelines

- All meal tracking logic is orchestrated by 6 specialized agents located in `agents/`.
- Database access is handled via `database/db.py` (SQLite or Supabase Cloud DB).
- To log a meal or run an analysis, invoke `python mcp_server.py --add "<meal_text>"`.
- Keep the Web Dashboard (`dashboard/index.html`) synced whenever meals or coach tips are updated.
