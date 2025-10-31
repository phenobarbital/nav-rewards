import logging


async def unlock_sales_techniques(user, env, conn, **kwargs):
    """
    Check if user has completed sales techniques training with required score.
    This function retrieves the maximum score from the training module
    for the 'Sales Techniques' module, ensuring the user has completed it.
    If the user has not completed the module, it returns 0.
    """
    try:
        query = """
        SELECT MAX(score) as max_score
        FROM training.module_completions
        WHERE user_id = $1
        AND module_name = 'Sales Techniques'
        AND completed_at IS NOT NULL
        """
        result = await conn.fetchval(query, user.user_id)
        return result or 0
    except Exception as err:
        logging.error(f"Error checking sales techniques: {err}")
        return 0


async def unlock_customer_service(user, env, conn, **kwargs):
    """
    Check if user has completed customer service training with required score.
    This function retrieves the maximum score from the training module
    for the 'Customer Service' module, ensuring the user has completed it.
    If the user has not completed the module, it returns 0.
    """
    try:
        query = """
        SELECT MAX(score) as max_score
        FROM training.module_completions
        WHERE user_id = $1
        AND module_name = 'Customer Service'
        AND completed_at IS NOT NULL
        """
        result = await conn.fetchval(query, user.user_id)
        return result or 0
    except Exception as err:
        logging.error(f"Error checking customer service: {err}")
        return 0
