import sqlite3
import os

DB_PATH = 'calories.db'
if os.path.exists(DB_PATH):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    
    # Ensure user_goals exists
    c.execute('''CREATE TABLE IF NOT EXISTS user_goals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        calories REAL DEFAULT 2200,
        protein_g REAL DEFAULT 160,
        fat_g REAL DEFAULT 70,
        carbs_g REAL DEFAULT 230,
        weight_current REAL DEFAULT 80.0,
        weight_goal REAL DEFAULT 75.0
    )''')
    
    # Ensure custom_products exists
    c.execute('''CREATE TABLE IF NOT EXISTS custom_products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_name TEXT NOT NULL UNIQUE,
        calories_100g REAL NOT NULL,
        protein_100g REAL NOT NULL,
        fat_100g REAL NOT NULL,
        carbs_100g REAL NOT NULL,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP
    )''')
    
    # Check if there are any rows in user_goals
    c.execute('SELECT COUNT(*) FROM user_goals')
    if c.fetchone()[0] == 0:
        c.execute('INSERT INTO user_goals (calories, protein_g, fat_g, carbs_g, weight_current, weight_goal) VALUES (2200, 160, 70, 230, 76.0, 67.0)')
    else:
        c.execute('UPDATE user_goals SET weight_current=76.0, weight_goal=67.0')
    conn.commit()
    conn.close()
    print('SQLite updated.')
else:
    print('DB not found at', DB_PATH)
