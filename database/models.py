import hashlib
from datetime import datetime, timedelta
from database.db import get_db


# ── Users ──────────────────────────────────────────────────────────────────

async def get_user(user_id: int):
    async with get_db() as db:
        async with db.execute("SELECT * FROM users WHERE id = ?", (user_id,)) as cur:
            return await cur.fetchone()


async def create_user(user_id: int, username: str, full_name: str, referred_by: int = None):
    ref_code = hashlib.md5(str(user_id).encode()).hexdigest()[:8].upper()
    async with get_db() as db:
        await db.execute(
            """INSERT OR IGNORE INTO users (id, username, full_name, ref_code, referred_by)
               VALUES (?, ?, ?, ?, ?)""",
            (user_id, username, full_name, ref_code, referred_by)
        )
        await db.commit()
    return await get_user(user_id)


async def update_user(user_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [user_id]
    async with get_db() as db:
        await db.execute(f"UPDATE users SET {cols} WHERE id = ?", vals)
        await db.commit()


async def get_user_by_ref_code(ref_code: str):
    async with get_db() as db:
        async with db.execute("SELECT * FROM users WHERE ref_code = ?", (ref_code,)) as cur:
            return await cur.fetchone()


async def deduct_balance(user_id: int, amount: int) -> bool:
    """Deduct from bonus_balance first, then main balance. Returns False if insufficient."""
    result = await deduct_balance_tracked(user_id, amount)
    return result is not None


async def deduct_balance_tracked(user_id: int, amount: int) -> dict | None:
    """Same as deduct_balance but returns breakdown of what was taken for precise refunds.
    Returns None if insufficient, else {"bonus": int, "main": int, "bonus_expire_days": int|None}."""
    user = await get_user(user_id)
    if not user:
        return None
    tariff = user["tariff"]
    if tariff == "unlimited":
        await update_user(user_id, total_tryons=user["total_tryons"] + amount)
        return {"bonus": 0, "main": 0, "bonus_expire_days": None}

    bonus = user["bonus_balance"] or 0
    # expire bonus if needed
    bonus_expire_days = None
    if user["bonus_expires_at"]:
        exp = datetime.fromisoformat(user["bonus_expires_at"])
        if datetime.now() > exp:
            bonus = 0
            await update_user(user_id, bonus_balance=0, bonus_expires_at=None)
        else:
            remaining = (exp - datetime.now()).days
            bonus_expire_days = max(1, remaining)

    main = user["balance"] or 0
    total = bonus + main
    if total < amount:
        return None

    if bonus >= amount:
        await update_user(user_id,
                          bonus_balance=bonus - amount,
                          total_tryons=user["total_tryons"] + amount)
        return {"bonus": amount, "main": 0, "bonus_expire_days": bonus_expire_days}
    else:
        remainder = amount - bonus
        await update_user(user_id,
                          bonus_balance=0,
                          balance=main - remainder,
                          total_tryons=user["total_tryons"] + amount)
        return {"bonus": bonus, "main": remainder, "bonus_expire_days": bonus_expire_days}


async def add_balance(user_id: int, amount: int, bonus: bool = False, expire_days: int = None):
    user = await get_user(user_id)
    if not user:
        return
    if bonus:
        new_bonus = (user["bonus_balance"] or 0) + amount
        exp = (datetime.now() + timedelta(days=expire_days)).isoformat() if expire_days else None
        await update_user(user_id, bonus_balance=new_bonus, bonus_expires_at=exp)
    else:
        new_bal = (user["balance"] or 0) + amount
        await update_user(user_id, balance=new_bal)


async def get_all_users(limit: int = None):
    async with get_db() as db:
        q = "SELECT * FROM users"
        if limit:
            q += f" LIMIT {limit}"
        async with db.execute(q) as cur:
            return await cur.fetchall()


async def search_users(query: str):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM users WHERE username LIKE ? OR CAST(id AS TEXT) LIKE ?",
            (f"%{query}%", f"%{query}%")
        ) as cur:
            return await cur.fetchall()


async def get_stats():
    async with get_db() as db:
        today = datetime.now().date().isoformat()
        week_ago = (datetime.now() - timedelta(days=7)).isoformat()
        month_ago = (datetime.now() - timedelta(days=30)).isoformat()

        async with db.execute("SELECT COUNT(*) as c FROM users WHERE DATE(created_at) = ?", (today,)) as cur:
            new_today = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM users WHERE created_at >= ?", (week_ago,)) as cur:
            new_week = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM users WHERE created_at >= ?", (month_ago,)) as cur:
            new_month = (await cur.fetchone())["c"]

        async with db.execute("SELECT COUNT(*) as c FROM tryon_sessions WHERE status='done' AND DATE(created_at) = ?", (today,)) as cur:
            tryons_today = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM tryon_sessions WHERE status='done' AND created_at >= ?", (week_ago,)) as cur:
            tryons_week = (await cur.fetchone())["c"]
        async with db.execute("SELECT COUNT(*) as c FROM tryon_sessions WHERE status='done' AND created_at >= ?", (month_ago,)) as cur:
            tryons_month = (await cur.fetchone())["c"]

        async with db.execute("SELECT SUM(amount_stars) as s FROM payments WHERE status='completed' AND DATE(created_at)=?", (today,)) as cur:
            rev_today = (await cur.fetchone())["s"] or 0
        async with db.execute("SELECT SUM(amount_stars) as s FROM payments WHERE status='completed' AND created_at>=?", (month_ago,)) as cur:
            rev_month = (await cur.fetchone())["s"] or 0

        async with db.execute("SELECT COUNT(*) as c FROM users WHERE tariff != 'free'") as cur:
            active_subs = (await cur.fetchone())["c"]

        return {
            "new_today": new_today, "new_week": new_week, "new_month": new_month,
            "tryons_today": tryons_today, "tryons_week": tryons_week, "tryons_month": tryons_month,
            "rev_today": rev_today, "rev_month": rev_month,
            "active_subs": active_subs,
        }


# ── Tryon Sessions ─────────────────────────────────────────────────────────

async def create_session(user_id: int, session_type: str, user_photo: str) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO tryon_sessions (user_id, session_type, user_photo_file_id, item_photos) VALUES (?, ?, ?, ?)",
            (user_id, session_type, user_photo, "[]")
        )
        await db.commit()
        return cur.lastrowid


async def update_session(session_id: int, **kwargs):
    if not kwargs:
        return
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [session_id]
    async with get_db() as db:
        await db.execute(f"UPDATE tryon_sessions SET {cols} WHERE id = ?", vals)
        await db.commit()


async def get_session(session_id: int):
    async with get_db() as db:
        async with db.execute("SELECT * FROM tryon_sessions WHERE id = ?", (session_id,)) as cur:
            return await cur.fetchone()


async def get_user_history(user_id: int, offset: int = 0, limit: int = 5, days: int = 30):
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    async with get_db() as db:
        async with db.execute(
            """SELECT * FROM tryon_sessions
               WHERE user_id = ? AND status = 'done' AND result_file_id IS NOT NULL
                 AND created_at >= ?
               ORDER BY created_at DESC LIMIT ? OFFSET ?""",
            (user_id, cutoff, limit, offset)
        ) as cur:
            rows = await cur.fetchall()
        async with db.execute(
            "SELECT COUNT(*) as c FROM tryon_sessions WHERE user_id=? AND status='done' AND result_file_id IS NOT NULL AND created_at>=?",
            (user_id, cutoff)
        ) as cur:
            total = (await cur.fetchone())["c"]
    return rows, total


# ── Wardrobe ───────────────────────────────────────────────────────────────

async def add_wardrobe_item(user_id: int, name: str, file_id: str) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO wardrobe_items (user_id, name, file_id) VALUES (?, ?, ?)",
            (user_id, name, file_id)
        )
        await db.commit()
        return cur.lastrowid


async def get_wardrobe_items(user_id: int, offset: int = 0, limit: int = 5):
    async with get_db() as db:
        async with db.execute(
            "SELECT * FROM wardrobe_items WHERE user_id=? ORDER BY created_at DESC LIMIT ? OFFSET ?",
            (user_id, limit, offset)
        ) as cur:
            rows = await cur.fetchall()
        async with db.execute("SELECT COUNT(*) as c FROM wardrobe_items WHERE user_id=?", (user_id,)) as cur:
            total = (await cur.fetchone())["c"]
    return rows, total


async def delete_wardrobe_item(item_id: int, user_id: int):
    async with get_db() as db:
        await db.execute("DELETE FROM wardrobe_items WHERE id=? AND user_id=?", (item_id, user_id))
        await db.commit()


async def get_wardrobe_item(item_id: int):
    async with get_db() as db:
        async with db.execute("SELECT * FROM wardrobe_items WHERE id=?", (item_id,)) as cur:
            return await cur.fetchone()


# ── Referrals ──────────────────────────────────────────────────────────────

async def create_referral(referrer_id: int, referred_id: int):
    async with get_db() as db:
        await db.execute(
            "INSERT OR IGNORE INTO referrals (referrer_id, referred_id) VALUES (?, ?)",
            (referrer_id, referred_id)
        )
        await db.commit()


async def get_referral(referred_id: int):
    async with get_db() as db:
        async with db.execute("SELECT * FROM referrals WHERE referred_id=?", (referred_id,)) as cur:
            return await cur.fetchone()


async def credit_referral_bonus(referred_id: int):
    async with get_db() as db:
        await db.execute(
            "UPDATE referrals SET bonus_credited=1 WHERE referred_id=?",
            (referred_id,)
        )
        await db.commit()


async def count_referrals_this_hour(ref_code: str) -> int:
    hour_ago = (datetime.now() - timedelta(hours=1)).isoformat()
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as c FROM ref_hour_tracking WHERE ref_code=? AND registered_at>=?",
            (ref_code, hour_ago)
        ) as cur:
            return (await cur.fetchone())["c"]


async def track_referral_registration(ref_code: str):
    async with get_db() as db:
        await db.execute("INSERT INTO ref_hour_tracking (ref_code) VALUES (?)", (ref_code,))
        await db.commit()


async def get_monthly_referrals_count(referrer_id: int) -> int:
    month_ago = (datetime.now() - timedelta(days=30)).isoformat()
    async with get_db() as db:
        async with db.execute(
            "SELECT COUNT(*) as c FROM referrals WHERE referrer_id=? AND created_at>=?",
            (referrer_id, month_ago)
        ) as cur:
            return (await cur.fetchone())["c"]


# ── Promo Codes ────────────────────────────────────────────────────────────

async def get_promo_code(code: str):
    async with get_db() as db:
        async with db.execute("SELECT * FROM promo_codes WHERE code=?", (code.upper(),)) as cur:
            return await cur.fetchone()


async def create_promo_code(code: str, type_: str, value: int, target: str = "all",
                             max_uses: int = None, new_users_only: bool = False,
                             expires_at: str = None, trial_tariff: str = "start"):
    async with get_db() as db:
        await db.execute(
            """INSERT INTO promo_codes
               (code, type, value, target, max_uses, new_users_only, expires_at, trial_tariff)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (code.upper(), type_, value, target, max_uses, int(new_users_only), expires_at, trial_tariff)
        )
        await db.commit()


async def activate_promo(user_id: int, promo_id: int):
    async with get_db() as db:
        await db.execute(
            "INSERT INTO promo_activations (user_id, promo_id) VALUES (?, ?)",
            (user_id, promo_id)
        )
        await db.execute("UPDATE promo_codes SET uses_count = uses_count + 1 WHERE id=?", (promo_id,))
        await db.commit()


async def has_used_promo(user_id: int, promo_id: int) -> bool:
    async with get_db() as db:
        async with db.execute(
            "SELECT id FROM promo_activations WHERE user_id=? AND promo_id=?",
            (user_id, promo_id)
        ) as cur:
            return await cur.fetchone() is not None


async def get_active_promos():
    async with get_db() as db:
        async with db.execute("SELECT * FROM promo_codes WHERE is_active=1 ORDER BY created_at DESC") as cur:
            return await cur.fetchall()


async def set_promo_active(promo_id: int, active: bool):
    async with get_db() as db:
        await db.execute("UPDATE promo_codes SET is_active=? WHERE id=?", (int(active), promo_id))
        await db.commit()


# ── Payments ───────────────────────────────────────────────────────────────

async def create_payment(user_id: int, stars: int, rub: int, product_type: str, product_id: str) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO payments (user_id, amount_stars, amount_rub, product_type, product_id) VALUES (?, ?, ?, ?, ?)",
            (user_id, stars, rub, product_type, product_id)
        )
        await db.commit()
        return cur.lastrowid


async def complete_payment(payment_id: int, charge_id: str):
    async with get_db() as db:
        await db.execute(
            "UPDATE payments SET status='completed', telegram_charge_id=? WHERE id=?",
            (charge_id, payment_id)
        )
        await db.commit()


# ── Support Tickets ────────────────────────────────────────────────────────

async def create_support_ticket(user_id: int, username: str, full_name: str,
                                 type_: str, message: str) -> int:
    async with get_db() as db:
        cur = await db.execute(
            "INSERT INTO support_tickets (user_id, username, full_name, type, message) VALUES (?, ?, ?, ?, ?)",
            (user_id, username, full_name, type_, message)
        )
        await db.commit()
        return cur.lastrowid


async def get_support_tickets(limit: int = 5, offset: int = 0, exclude_closed: bool = True):
    async with get_db() as db:
        if exclude_closed:
            q = "SELECT * FROM support_tickets WHERE status != 'closed' ORDER BY created_at DESC LIMIT ? OFFSET ?"
            cq = "SELECT COUNT(*) as c FROM support_tickets WHERE status != 'closed'"
            async with db.execute(q, (limit, offset)) as cur:
                rows = await cur.fetchall()
            async with db.execute(cq) as cur:
                total = (await cur.fetchone())["c"]
        else:
            async with db.execute(
                "SELECT * FROM support_tickets ORDER BY created_at DESC LIMIT ? OFFSET ?", (limit, offset)
            ) as cur:
                rows = await cur.fetchall()
            async with db.execute("SELECT COUNT(*) as c FROM support_tickets") as cur:
                total = (await cur.fetchone())["c"]
    return rows, total


async def get_support_ticket(ticket_id: int):
    async with get_db() as db:
        async with db.execute("SELECT * FROM support_tickets WHERE id=?", (ticket_id,)) as cur:
            return await cur.fetchone()


async def mark_ticket_read(ticket_id: int):
    async with get_db() as db:
        await db.execute(
            "UPDATE support_tickets SET status='open' WHERE id=? AND status='new'", (ticket_id,)
        )
        await db.commit()


async def close_support_ticket(ticket_id: int):
    async with get_db() as db:
        await db.execute("UPDATE support_tickets SET status='closed' WHERE id=?", (ticket_id,))
        await db.commit()


async def count_new_tickets() -> int:
    async with get_db() as db:
        async with db.execute("SELECT COUNT(*) as c FROM support_tickets WHERE status='new'") as cur:
            return (await cur.fetchone())["c"]


async def get_promo_by_id(promo_id: int):
    async with get_db() as db:
        async with db.execute("SELECT * FROM promo_codes WHERE id=?", (promo_id,)) as cur:
            return await cur.fetchone()
