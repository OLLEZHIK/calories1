import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"

# Auto-load .env file variables into os.environ if .env exists
if ENV_FILE.exists():
    with open(ENV_FILE, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip()

IS_VERCEL = os.getenv("VERCEL", "0") == "1" or os.getenv("AWS_LAMBDA_FUNCTION_NAME") is not None
if IS_VERCEL:
    DB_PATH = os.getenv("DB_PATH", "/tmp/calories.db")
else:
    DB_PATH = os.getenv("DB_PATH", str(BASE_DIR / "calories.db"))

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

TELEGRAM_USER_ID = os.getenv("TELEGRAM_USER_ID", "697275222")
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
