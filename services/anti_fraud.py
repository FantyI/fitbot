from database import models
from config import ADMIN_IDS


HOURLY_LIMIT = 10

_paused_ref_codes: set[str] = set()


async def check_ref_fraud(ref_code: str, referred_id: int, bot=None) -> bool:
    """Returns True if registration should proceed, False if paused."""
    if ref_code in _paused_ref_codes:
        return False

    count = await models.count_referrals_this_hour(ref_code)
    if count >= HOURLY_LIMIT:
        _paused_ref_codes.add(ref_code)
        if bot:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚠️ Алерт: реферальный код `{ref_code}` — {count+1} регистраций за час. "
                        f"Начисления приостановлены.",
                        parse_mode="Markdown"
                    )
                except Exception:
                    pass
        return False

    await models.track_referral_registration(ref_code)
    return True


def is_self_referral(user_id: int, ref_code: str) -> bool:
    """Check if user is trying to use their own ref code."""
    # ref_code is md5 of user_id, so we check by getting user
    return False  # Checked in handler by comparing referrer.id == user_id
