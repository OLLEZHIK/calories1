import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from database.db import calculate_nutrition_goals, get_user_goals, save_user_weight_and_goals
from agents.teamlead_agent import TeamLeadAgent

def test_goals_calculation():
    print("Testing calculations for 75 kg:")
    for mode in ["loss_200", "loss_300", "loss_400", "gain"]:
        g = calculate_nutrition_goals(75.0, mode)
        formula_cal = 4 * g["protein_g"] + 9 * g["fat_g"] + 4 * g["carbs_g"]
        assert formula_cal == g["calories"], f"Formula mismatch for {mode}: {formula_cal} != {g['calories']}"
        print(f"  Mode: {mode:8s} | Cal: {g['calories']} | P: {g['protein_g']}g | F: {g['fat_g']}g | C: {g['carbs_g']}g | 4P+9F+4C={formula_cal} OK")

def test_telegram_parsing():
    print("\nTesting TeamLeadAgent weight and mode parsing:")
    lead = TeamLeadAgent()
    test_phrases = [
        "мой вес 76.5 кг",
        "вешу 78",
        "77.2 кг",
        "режим 400",
        "переключи на 200г",
        "хочу качаться",
        "режим набор веса"
    ]
    for p in test_phrases:
        res = lead.route_input(p)
        assert "Параметры веса и цели успешно обновлены" in res, f"Failed to match: {p} -> {res}"
        first_line = res.splitlines()[0]
        print(f"  '{p}' -> {first_line}")

if __name__ == "__main__":
    test_goals_calculation()
    test_telegram_parsing()
    print("\nAll goal & weight tests passed!")
