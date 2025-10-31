"""
Reward-related achievement functions.
"""
from datetime import timedelta


async def get_badges_earned_count(user, env, conn, **kwargs):
    """Get number of badges earned by user."""
    category = kwargs.get('category')
    reward_type = kwargs.get('reward_type')
    days = kwargs.get('days')

    if not conn:
        return 0

    query_parts = [
        "SELECT COUNT(*) as badge_count",
        "FROM rewards.users_rewards ur",
        "JOIN rewards.rewards r ON ur.reward_id = r.reward_id",
        "WHERE ur.receiver_user = $1"
    ]

    params = [user.user_id]
    param_count = 1

    if category:
        param_count += 1
        query_parts.append(f"AND r.reward_category = ${param_count}")
        params.append(category)

    if reward_type:
        param_count += 1
        query_parts.append(f"AND r.reward_type = ${param_count}")
        params.append(reward_type)

    if days:
        param_count += 1
        start_date = env.timestamp - timedelta(days=days)
        query_parts.append(f"AND ur.awarded_at >= ${param_count}")
        params.append(start_date)

    query = " ".join(query_parts)

    try:
        result = await conn.fetchval(query, *params)
        return result or 0
    except Exception:
        return 0

async def get_points_earned(user, env, conn, **kwargs):
    """Get total points earned by user."""
    days = kwargs.get('days')

    if not conn:
        return 0

    query_parts = [
        "SELECT COALESCE(SUM(points), 0) as total_points",
        "FROM rewards.users_rewards",
        "WHERE receiver_user = $1"
    ]

    params = [user.user_id]

    if days:
        start_date = env.timestamp - timedelta(days=days)
        query_parts.append("AND awarded_at >= $2")
        params.append(start_date)

    query = " ".join(query_parts)

    try:
        result = await conn.fetchval(query, *params)
        return result or 0
    except Exception:
        return 0
