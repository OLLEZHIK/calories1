import sys
import io
import json

# Ensure UTF-8 output encoding for Windows terminal
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

from database.db import (
    get_product_prices, save_product_price, update_product_price,
    delete_product_entry, estimate_product_nutrition
)

def test_crud():
    print("=== Testing Products CRUD in Database & API ===")
    
    test_prod = "тестовый батончик протеиновый"
    
    # 1. Clean up if existed
    delete_product_entry(product_name=test_prod)
    initial_count = len(get_product_prices())
    print(f"Initial products count: {initial_count}")

    # 2. Add product
    print(f"\n1. Adding product: '{test_prod}'...")
    save_product_price(
        product_name=test_prod,
        price_rub=2.50,
        weight_g=60.0,
        category="sweets",
        protein_100g=30.0,
        fat_100g=10.0,
        carbs_100g=25.0,
        calories_100g=310.0,
        coach_score=8,
        coach_verdict="Отличный протеиновый перекус без лишнего сахара."
    )
    
    prods = get_product_prices()
    found = next((p for p in prods if p["product_name"] == test_prod), None)
    assert found is not None, "Product was not added!"
    print(f"✓ Product added successfully: id={found.get('id')}, cal={found['calories_per_100g']}, P={found['protein_per_100g']}, score={found['coach_score']}")
    p_id = found.get("id")

    # 3. Update product (update macros, zero carbs, update price)
    print("\n2. Updating product values (zero carbs, higher protein, lower price)...")
    res = update_product_price(
        product_name=test_prod,
        product_id=p_id,
        price_rub=1.99,
        weight_g=60.0,
        category="sweets",
        protein_100g=40.0,
        fat_100g=5.0,
        carbs_100g=0.0,
        calories_100g=205.0, # 4*40 + 9*5 + 4*0 = 205
        coach_score=9,
        coach_verdict="Супер-высокобелковый изолят, ноль углеводов."
    )
    
    prods2 = get_product_prices()
    updated_prod = next((p for p in prods2 if p["product_name"] == test_prod), None)
    assert updated_prod is not None, "Product not found after update!"
    assert updated_prod["protein_per_100g"] == 40, f"Expected 40 protein, got {updated_prod['protein_per_100g']}"
    assert updated_prod["carbs_per_100g"] == 0, f"Expected 0 carbs, got {updated_prod['carbs_per_100g']}"
    assert updated_prod["price_rub"] == 1.99, f"Expected 1.99 price, got {updated_prod['price_rub']}"
    assert updated_prod["coach_score"] == 9, f"Expected 9 score, got {updated_prod['coach_score']}"
    print(f"✓ Product updated successfully: P={updated_prod['protein_per_100g']}, F={updated_prod['fat_per_100g']}, C={updated_prod['carbs_per_100g']}, Cal={updated_prod['calories_per_100g']}, Price={updated_prod['price_rub']}")

    # 4. Test Rename product
    renamed_prod = "тестовый батончик ультра"
    print(f"\n3. Testing product renaming from '{test_prod}' to '{renamed_prod}'...")
    update_product_price(
        product_name=renamed_prod,
        original_name=test_prod,
        product_id=p_id,
        price_rub=2.10,
        weight_g=60.0,
        category="sweets",
        protein_100g=40.0,
        fat_100g=5.0,
        carbs_100g=0.0,
        calories_100g=205.0,
        coach_score=9,
        coach_verdict="Переименованный батончик"
    )
    prods3 = get_product_prices()
    old_found = next((p for p in prods3 if p["product_name"] == test_prod), None)
    new_found = next((p for p in prods3 if p["product_name"] == renamed_prod), None)
    assert old_found is None, "Old product name still exists!"
    assert new_found is not None, "Renamed product not found!"
    print(f"✓ Rename verified: old removed, new '{renamed_prod}' active!")

    # 5. Test Nutrition Estimation
    print("\n4. Testing AI nutrition estimation for 'индейка филе'...")
    est = estimate_product_nutrition("индейка филе", category="meat")
    assert est["calories_100g"] > 0, "Estimation failed to produce calories!"
    assert est["protein_100g"] > 0, "Estimation failed to produce protein!"
    print(f"✓ Estimation result: {est['calories_100g']} kcal, P={est['protein_100g']}g, F={est['fat_100g']}g, C={est['carbs_100g']}g, score={est['coach_score']}/10")

    # 6. Test Delete
    print(f"\n5. Deleting product '{renamed_prod}'...")
    delete_product_entry(product_name=renamed_prod)
    prods_final = get_product_prices()
    del_check = next((p for p in prods_final if p["product_name"] == renamed_prod), None)
    assert del_check is None, "Product was not deleted!"
    print(f"✓ Product deleted successfully! Total products now: {len(prods_final)}")

    print("\n=== ALL CRUD TESTS PASSED PERFECTLY! ===")

if __name__ == "__main__":
    test_crud()
