from typing import List, Dict, Any, Optional
from database.db import (
    save_product_price, get_product_prices, delete_product,
    are_product_duplicates, validate_product_values
)

class EconomyAgent:
    """
    Agent 4: Price & Economy Agent (Catalog Auditor & Guardian)
    1. Tracks product costs, computes EUR/RUB per 100g and per gram of protein/fat/carbs.
    2. Identifies cost-effective protein/fat sources.
    3. Monitors the product & price catalog:
       - Eliminates duplicate entries (e.g. Russian singular/plural forms, word permutations).
       - Enforces physical sanity: 4*P + 9*F + 4*C energy law, macro sums <= 100g, non-negative prices and weights.
       - Runs batch audits and automatically cleanses SQLite, Supabase, and Dashboard.
    """
    def __init__(self):
        self.name = "EconomyAgent"

    def are_duplicates(self, name1: str, name2: str) -> bool:
        """Expose canonical product duplication check."""
        return are_product_duplicates(name1, name2)

    def record_price(self, product_name: str, price_rub: float, weight_g: float = 100.0,
                     category: str = "general", protein_100g: float = 0, fat_100g: float = 0,
                     carbs_100g: float = 0, calories_100g: float = 0, coach_score: int = 0,
                     coach_verdict: str = ""):
        """Saves or updates a product price with pre-validation and deduplication."""
        save_product_price(
            product_name=product_name,
            price_rub=price_rub,
            weight_g=weight_g,
            category=category,
            protein_100g=protein_100g,
            fat_100g=fat_100g,
            carbs_100g=carbs_100g,
            calories_100g=calories_100g,
            coach_score=coach_score,
            coach_verdict=coach_verdict
        )

    def audit_and_clean_catalog(self) -> Dict[str, Any]:
        """
        Scans all products in the database:
        1. Identifies and merges duplicate entries (e.g. 'яйца куриные' and 'яйцо куриное').
        2. Validates macro and calorie equations (4P + 9F + 4C), clamps outliers.
        3. Removes redundant database records and syncs changes to SQLite, Supabase, and Dashboard.
        """
        products = get_product_prices()
        if not products:
            return {
                "status": "empty",
                "duplicates_merged": [],
                "values_corrected": [],
                "total_products": 0,
                "products": []
            }

        duplicates_merged = []
        values_corrected = []
        visited = set()
        duplicates_to_delete = []

        # 1. Deduplication pass
        for i in range(len(products)):
            p1 = products[i]
            name1 = (p1.get("product_name") or "").strip().lower()
            if not name1 or name1 in visited:
                continue

            for j in range(i + 1, len(products)):
                p2 = products[j]
                name2 = (p2.get("product_name") or "").strip().lower()
                if not name2 or name2 in visited:
                    continue

                if are_product_duplicates(name1, name2):
                    # Canonical election: prefer singular or longer descriptive title
                    canonical = name1 if not name1.endswith(('ы', 'и', 'а')) else name2
                    secondary = name2 if canonical == name1 else name1
                    can_prod = p1 if canonical == name1 else p2
                    sec_prod = p2 if canonical == name1 else p1

                    # Merge attributes: highest weight, latest price, best coach score/verdict
                    merged_weight = max(float(can_prod.get("weight_g") or 100), float(sec_prod.get("weight_g") or 100))
                    merged_price = float(sec_prod.get("price_rub") or 0) or float(can_prod.get("price_rub") or 0)
                    merged_category = can_prod.get("category") or sec_prod.get("category") or "general"
                    merged_prot = max(float(can_prod.get("protein_per_100g") or 0), float(sec_prod.get("protein_per_100g") or 0))
                    merged_fat = max(float(can_prod.get("fat_per_100g") or 0), float(sec_prod.get("fat_per_100g") or 0))
                    merged_carbs = max(float(can_prod.get("carbs_per_100g") or 0), float(sec_prod.get("carbs_per_100g") or 0))
                    merged_cal = max(float(can_prod.get("calories_per_100g") or 0), float(sec_prod.get("calories_per_100g") or 0))
                    merged_score = int(can_prod.get("coach_score") or sec_prod.get("coach_score") or 5)
                    merged_verdict = can_prod.get("coach_verdict") or sec_prod.get("coach_verdict") or ""

                    val = validate_product_values(
                        protein_100g=merged_prot,
                        fat_100g=merged_fat,
                        carbs_100g=merged_carbs,
                        calories_100g=merged_cal,
                        price_rub=merged_price,
                        weight_g=merged_weight,
                        coach_score=merged_score
                    )

                    save_product_price(
                        product_name=canonical,
                        price_rub=val["price_rub"],
                        weight_g=val["weight_g"],
                        category=merged_category,
                        protein_100g=val["protein_100g"],
                        fat_100g=val["fat_100g"],
                        carbs_100g=val["carbs_100g"],
                        calories_100g=val["calories_100g"],
                        coach_score=val["coach_score"],
                        coach_verdict=merged_verdict
                    )

                    duplicates_to_delete.append(secondary)
                    visited.add(secondary)
                    duplicates_merged.append({"canonical": canonical, "duplicate": secondary})

            visited.add(name1)

        # Remove duplicate records from database
        for d_name in duplicates_to_delete:
            delete_product(d_name)

        # 2. Validation & Sanity pass on remaining products
        remaining = get_product_prices()
        for prod in remaining:
            p_name = prod.get("product_name", "")
            orig_p = float(prod.get("protein_per_100g") or 0)
            orig_f = float(prod.get("fat_per_100g") or 0)
            orig_c = float(prod.get("carbs_per_100g") or 0)
            orig_cal = float(prod.get("calories_per_100g") or 0)
            orig_price = float(prod.get("price_rub") or 0)
            orig_w = float(prod.get("weight_g") or 100)
            orig_score = int(prod.get("coach_score") or 0)

            val = validate_product_values(
                protein_100g=orig_p,
                fat_100g=orig_f,
                carbs_100g=orig_c,
                calories_100g=orig_cal,
                price_rub=orig_price,
                weight_g=orig_w,
                coach_score=orig_score
            )

            fixes = []
            if abs(orig_p - val["protein_100g"]) > 0.01 or abs(orig_f - val["fat_100g"]) > 0.01 or abs(orig_c - val["carbs_100g"]) > 0.01:
                fixes.append("БЖУ нормализованы (сумма <= 100г)")
            if abs(orig_cal - val["calories_100g"]) > 0.5:
                fixes.append(f"Калории {int(orig_cal)} -> {val['calories_100g']} ккал (4P+9F+4C)")
            if orig_w <= 0:
                fixes.append("Вес скорректирован до 100г")
            if orig_score > 0 and (orig_score < 1 or orig_score > 10):
                fixes.append(f"Оценка тренера скорректирована ({val['coach_score']}/10)")

            if fixes:
                save_product_price(
                    product_name=p_name,
                    price_rub=val["price_rub"],
                    weight_g=val["weight_g"],
                    category=prod.get("category", "general"),
                    protein_100g=val["protein_100g"],
                    fat_100g=val["fat_100g"],
                    carbs_100g=val["carbs_100g"],
                    calories_100g=val["calories_100g"],
                    coach_score=val["coach_score"],
                    coach_verdict=prod.get("coach_verdict", "")
                )
                values_corrected.append({"product": p_name, "fixes": fixes})

        # 3. Refresh Dashboard if any modifications occurred
        if duplicates_merged or values_corrected:
            try:
                from agents.dashboard_agent import dashboard_agent
                dashboard_agent.render()
            except Exception as e:
                print(f"Dashboard render error during audit: {e}")

        final_products = get_product_prices()
        return {
            "status": "success",
            "duplicates_merged": duplicates_merged,
            "values_corrected": values_corrected,
            "total_products": len(final_products),
            "products": final_products
        }

    def run_audit_command(self) -> str:
        """Executes catalog audit and generates a clean Markdown report with ASCII table."""
        from agents.ingestion_agent import build_products_ascii_table
        res = self.audit_and_clean_catalog()
        products = res.get("products", [])

        lines = ["🛡 **Аудит базы продуктов завершён!**\n"]
        lines.append("👨‍💼 **Агент-контролёр**: EconomyAgent *(контроль цен, дубликатов и КБЖУ)*")
        lines.append(f"📦 **Всего проверенных продуктов**: {len(products)}\n")

        dup_merged = res.get("duplicates_merged", [])
        if dup_merged:
            lines.append("🔄 **Устранены повторы (дубликаты)**:")
            for d in dup_merged:
                lines.append(f"• Объединены *«{d['duplicate']}»* ➔ *«{d['canonical']}»*")
            lines.append("")
        else:
            lines.append("✅ **Повторов не обнаружено** (все названия уникальны и согласованы).")

        val_fixed = res.get("values_corrected", [])
        if val_fixed:
            lines.append("\n🛠 **Исправлены некорректные значения**:")
            for v in val_fixed:
                lines.append(f"• **{v['product'].capitalize()}**: {'; '.join(v['fixes'])}")
            lines.append("")
        else:
            lines.append("✅ **Значения корректны**: энергетический баланс ($4P+9F+4C$) и цены верны.")

        if products:
            table_str = build_products_ascii_table(products)
            lines.append(f"\n📋 **Текущий каталог проверенных продуктов**:\n```\n{table_str}\n```")

        lines.append("\n🌐 [Открыть Дашборд Vercel](https://fatcaunter.vercel.app)")
        return "\n".join(lines)

    def analyze_economy(self) -> Dict[str, Any]:
        """Calculates cost-efficiency of protein and fat sources."""
        prices = get_product_prices()
        if not prices:
            return {"best_protein_sources": [], "best_fat_sources": [], "message": "No price records available."}

        analyzed = []
        for p in prices:
            price_100g = p.get("price_per_100g", 0)
            prot = p.get("protein_per_100g", 0)
            fat = p.get("fat_per_100g", 0)

            cur_per_g_protein = round(price_100g / prot, 2) if prot > 0 else None
            cur_per_g_fat = round(price_100g / fat, 2) if fat > 0 else None

            analyzed.append({
                "product_name": p.get("product_name"),
                "price_rub": p.get("price_rub"),
                "weight_g": p.get("weight_g"),
                "price_per_100g": round(price_100g, 2),
                "cost_per_g_protein": cur_per_g_protein,
                "cost_per_g_fat": cur_per_g_fat,
            })

        best_protein = sorted([a for a in analyzed if a["cost_per_g_protein"] is not None], key=lambda x: x["cost_per_g_protein"])
        best_fats = sorted([a for a in analyzed if a["cost_per_g_fat"] is not None], key=lambda x: x["cost_per_g_fat"])

        return {
            "all_products": analyzed,
            "best_protein_sources": best_protein[:3],
            "best_fat_sources": best_fats[:3]
        }

economy_agent = EconomyAgent()
