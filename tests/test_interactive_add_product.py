import sys
import io
import json

# Ensure UTF-8 output encoding for Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from agents.ingestion_agent import (
    fetch_internet_product_nutrition,
    parse_entered_price,
    format_new_product_prompt
)
from agents.teamlead_agent import teamlead_agent
from database.db import get_product_prices, delete_product_entry


def test_interactive_flow():
    print("=== Testing Interactive Add Product Feature ===")

    # 1. Test price parser
    print("\n1. Testing parse_entered_price...")
    assert parse_entered_price("2.50") == 2.50
    assert parse_entered_price("2,5 евро") == 2.50
    assert parse_entered_price("3€") == 3.0
    assert parse_entered_price("200 руб") == 2.0  # converted from 200 RUB
    assert parse_entered_price("отмена") is None
    assert parse_entered_price("пропустить") is None
    print("✓ Price parser tests passed!")

    # 2. Test internet nutrition retrieval for a new product
    test_prod = "сыр сулугуни тест"
    print(f"\n2. Testing fetch_internet_product_nutrition for '{test_prod}'...")
    delete_product_entry(product_name=test_prod)
    info = fetch_internet_product_nutrition(test_prod)
    assert info is not None
    assert "calories_100g" in info and info["calories_100g"] > 0
    assert "protein_100g" in info and info["protein_100g"] >= 0
    assert "coach_verdict" in info
    print(f"✓ Found nutrition: {info['calories_100g']} kcal, P={info['protein_100g']}, F={info['fat_100g']}, C={info['carbs_100g']}")
    print(f"✓ Coach score: {info['coach_score']}/10, Verdict: {info['coach_verdict']}")

    # 3. Test format_new_product_prompt
    print("\n3. Testing format_new_product_prompt...")
    prompt_text, markup = format_new_product_prompt(info)
    assert "Обнаружен новый продукт" in prompt_text
    assert "Вы имеете в виду" in prompt_text
    assert "КБЖУ из сети" in prompt_text
    assert "inline_keyboard" in markup
    print("✓ Prompt message formatted correctly:\n" + prompt_text[:120] + "...")

    # 4. Test meal logging with an unknown product
    print("\n4. Testing meal logging with an unpriced/new product...")
    meal_input = f"100г {test_prod}, 2 яйца"
    res_details = teamlead_agent.route_input_with_details(meal_input, input_type="text")
    assert "записан" in res_details["response"].lower()
    assert res_details.get("pending_product") is not None
    pending = res_details["pending_product"]
    print(f"✓ Meal logged and pending product captured: {pending['product_name']}")

    # 5. Test entering price and saving to DB
    print("\n5. Testing saving price from pending product...")
    price = parse_entered_price("3.50 евро")
    assert price == 3.50

    from database.db import save_custom_product, save_product_price
    save_custom_product(
        pending["product_name"],
        pending["calories_100g"],
        pending["protein_100g"],
        pending["fat_100g"],
        pending["carbs_100g"]
    )
    save_product_price(
        pending["product_name"],
        price,
        pending.get("weight_g", 100.0),
        pending.get("category", "general"),
        pending["protein_100g"],
        pending["fat_100g"],
        pending["carbs_100g"],
        pending["calories_100g"],
        pending.get("coach_score", 6),
        pending.get("coach_verdict", "")
    )

    all_prods = get_product_prices()
    saved = next((p for p in all_prods if p["product_name"].lower() == pending["product_name"].lower()), None)
    assert saved is not None, "Product was not found in catalog after save!"
    assert saved["price_rub"] == 3.50
    print(f"✓ Product '{saved['product_name']}' successfully saved in catalog with price {saved['price_rub']} €!")

    # 6. Clean up
    delete_product_entry(product_name=test_prod)
    delete_product_entry(product_name=pending["product_name"])
    print("✓ Cleaned up test product!")

    print("\n=== ALL INTERACTIVE ADD PRODUCT TESTS PASSED! ===")


if __name__ == "__main__":
    test_interactive_flow()
