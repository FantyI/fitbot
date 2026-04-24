from datetime import datetime, timedelta
from database import models
from config import TARIFFS, PACKS


async def check_tariff_expiry(user_id: int):
    """Downgrade tariff to free if tariff_expires_at has passed."""
    user = await models.get_user(user_id)
    if not user or user["tariff"] == "free" or not user["tariff_expires_at"]:
        return
    try:
        exp = datetime.fromisoformat(user["tariff_expires_at"])
        if datetime.now() > exp:
            await models.update_user(user_id, tariff="free", tariff_expires_at=None)
    except Exception:
        pass


def get_tryon_cost(session_type: str, item_count: int) -> int:
    if session_type == "single":
        return 1
    # outfit
    if item_count <= 4:
        return 2
    return 3


async def can_afford(user_id: int, cost: int) -> bool:
    await check_tariff_expiry(user_id)
    user = await models.get_user(user_id)
    if not user:
        return False
    if user["tariff"] == "unlimited":
        return True
    # Check bonus expiry
    bonus = user["bonus_balance"] or 0
    if user["bonus_expires_at"]:
        exp = datetime.fromisoformat(user["bonus_expires_at"])
        if datetime.now() > exp:
            bonus = 0
    return (bonus + (user["balance"] or 0)) >= cost


async def apply_tariff(user_id: int, tariff_key: str):
    tariff = TARIFFS[tariff_key]
    expires = (datetime.now() + timedelta(days=30)).isoformat()
    tryons = tariff["tryons"]
    if tryons == -1:
        tryons = 0  # unlimited
    await models.update_user(user_id, tariff=tariff_key, tariff_expires_at=expires)
    # Add monthly tryons on top of existing balance (not replace)
    if tryons > 0:
        user = await models.get_user(user_id)
        new_bal = (user["balance"] or 0) + tryons
        await models.update_user(user_id, balance=new_bal)


async def apply_pack(user_id: int, pack_key: str):
    pack = PACKS[pack_key]
    if pack.get("outfit"):
        # Pre-fund the cost of a 5+ item outfit (3 tryons)
        await models.add_balance(user_id, 3)
    elif pack.get("wardrobe"):
        # Grant standalone wardrobe access for 30 days — independent of tariff
        user = await models.get_user(user_id)
        now = datetime.now()
        base = now
        if user and user["wardrobe_until"]:
            try:
                existing = datetime.fromisoformat(user["wardrobe_until"])
                if existing > now:
                    base = existing  # extend instead of reset
            except Exception:
                pass
        expires = (base + timedelta(days=30)).isoformat()
        await models.update_user(user_id, wardrobe_until=expires)
    else:
        await models.add_balance(user_id, pack["tryons"])


async def handle_first_purchase(user_id: int, amount_stars: int):
    """Credit referral bonus after first purchase."""
    user = await models.get_user(user_id)
    if not user or user["first_purchase_done"]:
        return
    await models.update_user(user_id, first_purchase_done=True)

    # Credit referrer
    ref = await models.get_referral(user_id)
    if ref and not ref["bonus_credited"]:
        referrer_id = ref["referrer_id"]
        monthly_count = await models.get_monthly_referrals_count(referrer_id)
        if monthly_count <= 50:
            # +5 tryons to referrer (bonus, expires 14 days)
            await models.add_balance(referrer_id, 5, bonus=True, expire_days=14)
            # +10% of first payment as tryons (rounded up)
            import math
            bonus_tryons = math.ceil(amount_stars * 0.1 / 10)  # approx 1 tryon per 10 stars
            if bonus_tryons > 0:
                await models.add_balance(referrer_id, bonus_tryons, bonus=True, expire_days=14)
            await models.credit_referral_bonus(user_id)

            # Check milestones
            referrer = await models.get_user(referrer_id)
            total_refs = (referrer["total_referred"] or 0) + 1
            await models.update_user(referrer_id, total_referred=total_refs)

            if total_refs == 5 and referrer["tariff"] == "free":
                await apply_tariff(referrer_id, "start")
            elif total_refs == 15 and referrer["tariff"] in ("free", "start"):
                await apply_tariff(referrer_id, "pro")
