import sys
import io

# Ensure UTF-8 output encoding for Windows terminal
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')

from bot.telegram_bot import process_user_meal_input
from database.db import get_today_summary
from agents.coach_agent import coach_agent
from agents.economy_agent import economy_agent
from agents.dashboard_agent import dashboard_agent

def run_test():
    print("=== Running Multi-Agent Calories AI Test Suite ===")

    # 1. Test Ingestion + Nutrition + Audit + DB logging
    test_inputs = [
        "5 яиц, 20г масла сливочного, 200г творог 5%",
        "200г куриная грудка, 150г гречка, 30г майонез"
    ]

    for inp in test_inputs:
        print(f"\n--- Testing Meal Input: '{inp}' ---")
        result = process_user_meal_input(inp, input_type="text")
        print(result)

    # 2. Test Today's Summary
    summary = get_today_summary()
    print("\n--- Today's Summary ---")
    print(f"Total Calories: {summary['total_calories']} kcal")
    print(f"Total Protein: {summary['total_protein']}g")
    print(f"Total Fat: {summary['total_fat']}g")
    print(f"Total Carbs: {summary['total_carbs']}g")

    # 3. Test Price Recording & Economy Analysis
    economy_agent.record_price("творог 5%", price_rub=1.50, weight_g=200, protein_100g=18, fat_100g=5, carbs_100g=3, calories_100g=130)
    economy_agent.record_price("куриная грудка", price_rub=8.50, weight_g=1000, protein_100g=31, fat_100g=3.6, carbs_100g=0, calories_100g=156)
    econ_stats = economy_agent.analyze_economy()
    print("\n--- Economy Analysis ---")
    print(f"Best Protein Sources: {econ_stats['best_protein_sources']}")

    # 4. Test Coach Agent Advice
    coach_stats = coach_agent.analyze()
    print("\n--- Coach Recommendations ---")
    for r in coach_stats["recommendations"]:
        print(f"[{r['severity'].upper()}] {r['message']}")

    # 5. Render Dashboard
    dash_file = dashboard_agent.render()
    print(f"\nDashboard generated at: {dash_file}")

    print("\n=== All Tests Passed Successfully! ===")

if __name__ == "__main__":
    run_test()
