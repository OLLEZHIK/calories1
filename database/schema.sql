-- SQLite Schema for Calories AI Multi-Agent System

CREATE TABLE IF NOT EXISTS meals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    raw_input TEXT NOT NULL,
    input_type TEXT DEFAULT 'text', -- 'text', 'voice', 'photo'
    notes TEXT
);

CREATE TABLE IF NOT EXISTS meal_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    meal_id INTEGER NOT NULL,
    product_name TEXT NOT NULL,
    category TEXT DEFAULT 'general',
    quantity_g REAL NOT NULL,
    calories REAL NOT NULL,
    protein_g REAL NOT NULL,
    fat_g REAL NOT NULL,
    carbs_g REAL NOT NULL,
    FOREIGN KEY (meal_id) REFERENCES meals(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS product_prices (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_name TEXT NOT NULL UNIQUE,
    category TEXT DEFAULT 'general',
    price_rub REAL NOT NULL,
    weight_g REAL NOT NULL,
    price_per_100g REAL GENERATED ALWAYS AS ((price_rub / weight_g) * 100) VIRTUAL,
    protein_per_100g REAL DEFAULT 0,
    fat_per_100g REAL DEFAULT 0,
    carbs_per_100g REAL DEFAULT 0,
    calories_per_100g REAL DEFAULT 0,
    updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS coach_recommendations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    topic TEXT NOT NULL,
    recommendation TEXT NOT NULL,
    severity TEXT DEFAULT 'info' -- 'info', 'warning', 'tip'
);

CREATE TABLE IF NOT EXISTS user_goals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    calories REAL DEFAULT 2200,
    protein_g REAL DEFAULT 160,
    fat_g REAL DEFAULT 70,
    carbs_g REAL DEFAULT 230
);
