"""
User engagement achievement functions.
"""
from datetime import timedelta


async def get_login_streak(user, env, conn, **kwargs):
    """Calculate consecutive login days."""
    if not conn:
        return 0

    query = """
        SELECT login_date::date as login_day
        FROM user_logins
        WHERE user_id = $1
        ORDER BY login_date DESC
        LIMIT 365
    """

    try:
        results = await conn.fetch_all(query, user.user_id)
        if not results:
            return 0

        # Calculate streak
        current_date = env.curdate
        streak = 0

        for record in results:
            login_day = record['login_day']
            expected_day = current_date - timedelta(days=streak)

            if login_day == expected_day:
                streak += 1
            else:
                break

        return streak
    except Exception:
        return 0

async def get_total_logins(user, env, conn, **kwargs):
    """Get total number of logins."""
    days = kwargs.get('days')

    if not conn:
        return 0

    query_parts = [
        "SELECT COUNT(*) as total_logins",
        "FROM user_logins",
        "WHERE user_id = $1"
    ]

    params = [user.user_id]

    if days:
        start_date = env.timestamp - timedelta(days=days)
        query_parts.append("AND login_date >= $2")
        params.append(start_date)

    query = " ".join(query_parts)

    try:
        result = await conn.fetchval(query, *params)
        return result or 0
    except Exception:
        return 0

async def get_session_duration_average(user, env, conn, **kwargs):
    """Get average session duration in minutes."""
    days = kwargs.get('days', 30)
    start_date = env.timestamp - timedelta(days=days)

    if not conn:
        return 0.0

    query = """
        SELECT COALESCE(
            AVG(
                EXTRACT(EPOCH FROM (logout_time - login_date))/60)
        , 0) as avg_duration
        FROM user_logins
        WHERE user_id = $1 AND login_date >= $2 AND logout_time IS NOT NULL
    """
    try:
        result = await conn.fetchval(query, user.user_id, start_date)
        return float(result or 0)
    except Exception:
        return 0.0
