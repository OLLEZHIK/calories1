import json
import sys
from typing import Dict, Any

# Ensure UTF-8 output formatting for Windows consoles
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


from bot.telegram_bot import process_user_meal_input
from database.db import get_today_summary, get_recent_meals
from agents.coach_agent import coach_agent
from agents.economy_agent import economy_agent
from agents.dashboard_agent import dashboard_agent

def mcp_call(method: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """
    Model Context Protocol (MCP) tool handler for Claude Code & Antigravity agents.
    """
    if method == "add_meal":
        raw_text = params.get("text", "")
        res = process_user_meal_input(raw_text, input_type=params.get("input_type", "mcp"))
        return {"status": "success", "result": res}

    elif method == "get_today_summary":
        summary = get_today_summary()
        return {"status": "success", "summary": summary}

    elif method == "get_coach_advice":
        advice = coach_agent.analyze()
        return {"status": "success", "advice": advice}

    elif method == "get_economy_stats":
        economy = economy_agent.analyze_economy()
        return {"status": "success", "economy": economy}

    elif method == "render_dashboard":
        path = dashboard_agent.render()
        return {"status": "success", "dashboard_path": path}

    elif method == "audit_catalog":
        res = economy_agent.audit_and_clean_catalog()
        return {"status": "success", "audit": res}

    elif method == "add_product":
        from database.db import save_product_price
        save_product_price(
            product_name=params.get("product_name", ""),
            price_rub=float(params.get("price_rub") or params.get("price") or 0.0),
            weight_g=float(params.get("weight_g") or 100.0),
            category=params.get("category", "general"),
            protein_100g=float(params.get("protein_100g") or 0.0),
            fat_100g=float(params.get("fat_100g") or 0.0),
            carbs_100g=float(params.get("carbs_100g") or 0.0),
            calories_100g=float(params.get("calories_100g") or 0.0),
            coach_score=int(params.get("coach_score") or 0),
            coach_verdict=params.get("coach_verdict", "")
        )
        dashboard_agent.render()
        return {"status": "success", "message": f"Product '{params.get('product_name')}' added"}

    elif method == "update_product":
        from database.db import update_product_price
        res = update_product_price(
            product_name=params.get("product_name", ""),
            original_name=params.get("original_name"),
            product_id=params.get("id") or params.get("product_id"),
            price_rub=float(params.get("price_rub") or params.get("price") or 0.0),
            weight_g=float(params.get("weight_g") or 100.0),
            category=params.get("category", "general"),
            protein_100g=float(params.get("protein_100g") or 0.0),
            fat_100g=float(params.get("fat_100g") or 0.0),
            carbs_100g=float(params.get("carbs_100g") or 0.0),
            calories_100g=float(params.get("calories_100g") or 0.0),
            coach_score=int(params.get("coach_score") or 0),
            coach_verdict=params.get("coach_verdict", "")
        )
        dashboard_agent.render()
        return {"status": "success", "product": res}

    elif method == "delete_product":
        from database.db import delete_product_entry
        delete_product_entry(
            product_name=params.get("product_name"),
            product_id=params.get("id") or params.get("product_id")
        )
        dashboard_agent.render()
        return {"status": "success", "message": "Product deleted"}

    else:
        return {"status": "error", "message": f"Unknown method {method}"}

if __name__ == "__main__":
    if len(sys.argv) > 1:
        cmd = sys.argv[1]
        arg_text = " ".join(sys.argv[2:]) if len(sys.argv) > 2 else ""
        if cmd == "--add":
            print(process_user_meal_input(arg_text))
        elif cmd == "--summary":
            print(json.dumps(get_today_summary(), indent=2, ensure_ascii=False))
        elif cmd == "--coach":
            print(json.dumps(coach_agent.analyze(), indent=2, ensure_ascii=False))
        elif cmd in ("--audit", "--audit-catalog"):
            print(economy_agent.run_audit_command())
        elif cmd == "--dashboard":
            print(f"Dashboard updated: {dashboard_agent.render()}")
    else:
        print("MCP Server ready. Methods: add_meal, get_today_summary, get_coach_advice, render_dashboard")
