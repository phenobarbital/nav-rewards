from aiohttp import web
from asyncdb.models import Model
from navconfig.logging import logging

## Reward Engine: Applying Rewards when User logs in.
async def apply_rewards(
    request: web.Request,
    user: Model,
    usermodel: Model,
    **kwargs
):
    """apply_rewards.

    Apply Rewards when User logs in.
    Args:
        request (web.Request): HTTP request
        user (Model): User Data.
        usermodel (Model): User Model (CRUD).
        kwargs: other arguments
    """
    logging.debug(
        f"Rewards: User was logged: {user.username}"
    )
