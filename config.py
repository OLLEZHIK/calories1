import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "calories.db"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")

# Supabase Cloud Database Config
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
USE_SUPABASE = os.getenv("USE_SUPABASE", "false").lower() in ["true", "1", "yes"]

# Default User Daily Goals
DEFAULT_GOALS = {
    "calories": 2200,
    "protein_g": 160,
    "fat_g": 70,
    "carbs_g": 230
}
