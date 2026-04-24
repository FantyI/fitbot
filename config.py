import os
from dotenv import load_dotenv

load_dotenv()

BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
POLZA_API_KEY: str = os.getenv("POLZA_API_KEY", "")
POLZA_BASE_URL: str = os.getenv("POLZA_BASE_URL", "https://api.polza.ai/v1")
ADMIN_IDS: list[int] = [
    int(x.strip()) for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip().isdigit()
]

DB_PATH = "fitbot.db"

# Tariff configs
TARIFFS = {
    "free":      {"name": "Free",     "price_stars": 0,   "price_rub": 0,    "tryons": 2,   "max_items": 1, "quality": "medium"},
    "start":     {"name": "Старт",    "price_stars": 130, "price_rub": 390,  "tryons": 20,  "max_items": 3, "quality": "high"},
    "pro":       {"name": "Про",      "price_stars": 270, "price_rub": 790,  "tryons": 60,  "max_items": 6, "quality": "max"},
    "unlimited": {"name": "Безлимит", "price_stars": 500, "price_rub": 1490, "tryons": -1,  "max_items": 8, "quality": "max"},
}

PACKS = {
    "pack_5":      {"name": "5 примерок",          "tryons": 5,  "stars": 50,  "rub": 149},
    "pack_15":     {"name": "15 примерок",          "tryons": 15, "stars": 120, "rub": 349},
    "pack_outfit": {"name": "1 образ (5+ вещей)",   "tryons": 0,  "stars": 35,  "rub": 99,  "outfit": True},
    "pack_wardrobe": {"name": "Шкаф на месяц",      "tryons": 0,  "stars": 70,  "rub": 199, "wardrobe": True},
}

# History retention days by tariff
HISTORY_DAYS = {"free": 0, "start": 30, "pro": 90, "unlimited": 90}

# Wardrobe limits
WARDROBE_LIMIT = {"free": 0, "start": 0, "pro": 30, "unlimited": 100}
