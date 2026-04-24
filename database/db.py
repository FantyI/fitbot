import aiosqlite
from contextlib import asynccontextmanager
from config import DB_PATH


@asynccontextmanager
async def get_db():
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute("PRAGMA foreign_keys = ON")
        await db.execute("PRAGMA journal_mode = WAL")
        await db.execute("PRAGMA busy_timeout = 3000")
        yield db


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY,
            username TEXT,
            full_name TEXT,
            ref_code TEXT UNIQUE,
            referred_by INTEGER,
            tariff TEXT DEFAULT 'free',
            tariff_expires_at DATETIME,
            balance INTEGER DEFAULT 2,
            bonus_balance INTEGER DEFAULT 0,
            bonus_expires_at DATETIME,
            total_referred INTEGER DEFAULT 0,
            referral_bonus_pending BOOLEAN DEFAULT 0,
            first_purchase_done BOOLEAN DEFAULT 0,
            promo_used TEXT,
            is_blocked BOOLEAN DEFAULT 0,
            total_tryons INTEGER DEFAULT 0,
            wardrobe_until DATETIME,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS tryon_sessions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            session_type TEXT,
            user_photo_file_id TEXT,
            item_photos TEXT,
            result_file_id TEXT,
            status TEXT DEFAULT 'pending',
            cost INTEGER,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS wardrobe_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            name TEXT,
            file_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (user_id) REFERENCES users(id)
        );

        CREATE TABLE IF NOT EXISTS referrals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            referrer_id INTEGER,
            referred_id INTEGER,
            bonus_credited BOOLEAN DEFAULT 0,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS promo_codes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT UNIQUE,
            type TEXT,
            value INTEGER,
            target TEXT DEFAULT 'all',
            max_uses INTEGER,
            uses_count INTEGER DEFAULT 0,
            new_users_only BOOLEAN DEFAULT 0,
            expires_at DATETIME,
            is_active BOOLEAN DEFAULT 1,
            trial_tariff TEXT DEFAULT 'start',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS promo_activations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            promo_id INTEGER,
            activated_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS payments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount_stars INTEGER,
            amount_rub INTEGER,
            product_type TEXT,
            product_id TEXT,
            status TEXT DEFAULT 'pending',
            telegram_charge_id TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS ref_hour_tracking (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ref_code TEXT,
            registered_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS support_tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            username TEXT,
            full_name TEXT,
            type TEXT,
            message TEXT,
            status TEXT DEFAULT 'new',
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        """)

        # Lightweight migrations for existing DBs
        async with db.execute("PRAGMA table_info(users)") as cur:
            cols = {row[1] for row in await cur.fetchall()}
        if "wardrobe_until" not in cols:
            await db.execute("ALTER TABLE users ADD COLUMN wardrobe_until DATETIME")

        async with db.execute("PRAGMA table_info(promo_codes)") as cur:
            promo_cols = {row[1] for row in await cur.fetchall()}
        if "trial_tariff" not in promo_cols:
            await db.execute("ALTER TABLE promo_codes ADD COLUMN trial_tariff TEXT DEFAULT 'start'")

        await db.commit()
