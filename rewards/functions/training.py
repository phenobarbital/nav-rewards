from navconfig import logging

async def check_product_knowledge(user, env, conn, **kwargs):
    """
    Check if user has completed product knowledge training with required score.
    This function retrieves the maximum score from the training module
    for the 'Product Knowledge' module, ensuring the user has completed it.
    If the user has not completed the module, it returns 0."""
    try:
        query = """
        SELECT MAX(score) as max_score
        FROM training.module_completions
        WHERE user_id = $1
        AND module_name = 'Product Knowledge'
        AND completed_at IS NOT NULL
        """
        result = await conn.fetchval(query, user.user_id)
        return result or 0
    except Exception as err:
        logging.error(f"Error checking product knowledge: {err}")
        return 0

async def check_sales_techniques(user, env, conn, **kwargs):
    """
    Check if user has completed sales techniques training with required score.
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

async def check_customer_service(user, env, conn, **kwargs):
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

async def check_closing_deals(user, env, conn, **kwargs):
    """
    Check if user has completed closing deals training with required score.
    This function retrieves the maximum score from the training module
    for the 'Closing Deals' module, ensuring the user has completed it.
    If the user has not completed the module, it returns 0.
    """
    try:
        query = """
        SELECT MAX(score) as max_score
        FROM training.module_completions
        WHERE user_id = $1
        AND module_name = 'Closing Deals'
        AND completed_at IS NOT NULL
        """
        result = await conn.fetchval(query, user.user_id)
        return result or 0
    except Exception as err:
        logging.error(f"Error checking closing deals: {err}")
        return 0

async def check_final_assessment(user, env, conn, **kwargs):
    """
    Check if user has completed final assessment with required score.
    This function retrieves the maximum score from the training assessments
    """
    try:
        query = """
        SELECT MAX(score) as max_score
        FROM training.assessments
        WHERE user_id = $1
        AND assessment_type = 'Sales Mastery Final'
        AND completed_at IS NOT NULL
        """
        result = await conn.fetchval(query, user.user_id)
        return result or 0
    except Exception as err:
        logging.error(f"Error checking final assessment: {err}")
        return 0
