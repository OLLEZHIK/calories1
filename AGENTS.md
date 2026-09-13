# AGENTS.md - Calories AI Project Guidelines

## Overview
This repository contains a multi-agent system for tracking calories, macros (BJU - Proteins, Fats, Carbs), product prices, and nutrition advice.

## Multi-Agent Architecture
- **IngestionAgent**: Parses raw inputs (voice, text, photos) into structured meal items.
- **NutritionAgent**: Calculates calories and macros per ingredient.
- **AuditorAgent**: Audits calculations against energy rules ($4 \cdot P + 9 \cdot F + 4 \cdot C$).
- **EconomyAgent**: Evaluates product costs, price-per-macro ratios, audits the product and price catalog, merges duplicates (e.g. Russian singular/plural forms), and validates energy/macro integrity ($4 \cdot P + 9 \cdot F + 4 \cdot C$, $P+F+C \le 100g$).
- **CoachAgent**: Provides personal trainer recommendations (e.g., detecting mayonnaise fat excess).
- **DashboardAgent**: Updates the HTML Web Dashboard (`dashboard/index.html`).

## Commands
- Run meal entry via CLI: `python mcp_server.py --add "5 яиц, 20г масла"`
- Get daily summary: `python mcp_server.py --summary`
- Run Coach recommendations: `python mcp_server.py --coach`
- Run Catalog Audit & Deduplication: `python mcp_server.py --audit`
- Update Dashboard: `python mcp_server.py --dashboard`
- Run test pipeline: `python -m tests.test_pipeline`
