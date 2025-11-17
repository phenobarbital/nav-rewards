from datamodel import BaseModel
from navigator.views import ModelView, FormModel
from ..context import EvalContext
from ..env import Environment
from ..models import (
    Reward,
    RewardCategory,
    RewardGroup,
    RewardType,
    BadgeAssign,
    UserReward,
    RewardView,
    Employee
)


class RewardHandler(ModelView):
    model: BaseModel = Reward
    pk: str = 'reward_id'


class RewardCategoryHandler(ModelView):
    model: BaseModel = RewardCategory
    name: str = "Reward Category"
    pk: str = "reward_category"


class RewardGroupHandler(ModelView):
    model: BaseModel = RewardGroup
    name: str = "Reward Group"
    pk: str = "reward_group"


class RewardTypeHandler(ModelView):
    model: BaseModel = RewardType
    name: str = "Reward Type"
    pk: str = "reward_type"


class UserRewardHandler(ModelView):
    model: BaseModel = UserReward
    name: str = "Managing User Rewards"
    pk: str = "award_id"


class RewardViewHandler(ModelView):
    model: BaseModel = RewardView
    name: str = "Reward View"
    pk: str = "reward_id"

class BadgeAssignHandler(FormModel):
    model: BadgeAssign = BadgeAssign
    path: str = "/api/v1/badge_assign"

    async def put(self):
        """Get information for usage in Form."""
        try:
            data = await self.validate_payload()
        except ValueError as exc:
            self.error(
                f"Invalid data: {exc}"
            )
        # Step 1: validate Reward exists on Reward Engine and return it
        try:
            system = self.request.app['reward_engine']
        except Exception as err:
            self.error(
                f"Reward System is not installed: {err}"
            )
        reward = await system.get_reward(data.reward_id)
        if not reward:
            self.error(
                f"Badge {data.reward_id} not found.",
                status=404
            )
        session, _ = await system.get_user(self.request)

        # fill giver information with session data:
        giver = session['session']
        full_name = giver.get('display_name', None) or f"{giver.get('first_name', '')} {giver.get('last_name', '')}".strip()  # noqa: E501
        data.giver_user = giver.get('user_id', None)
        data.giver_email = giver.get('email', None)
        data.giver_employee = giver.get('associate_id', None)
        data.giver_name = full_name
        data.points = reward.reward().points
        env = Environment(
            connection=system.connection,
            cache=system.get_cache()
        )
        if not reward:
            self.error(
                f"Badge {reward.reward().reward} not found or it's not available."  # noqa: E501
            )
        # Step 2: validate User exists on UserView and returned
        try:
            user = await system.check_user(
                data,
                env
            )
            data.receiver_user = user.user_id
            data.receiver_email = user.email
            data.receiver_employee = getattr(user, 'associate_id', user.email)
            data.display_name = user.display_name
            data.receiver_name = user.display_name
        except RuntimeError as err:
            self.error(
                response={
                    "message": "Cannot Fetch User Information.",
                    "error": f"{err}"
                }
            )
        except Exception as err:
            self.error(
                response={
                    "message": "No Assigning Badge to User.",
                    "error": f"{err}"
                }
            )
        if user.user_id == session.user_id:
            self.error(
                response={
                    "message": "You cannot assign a Badge to yourself."
                }
            )
        # Step 3: Reward fits the User who receives the reward:
        ctx = EvalContext(
            request=self.request,
            user=user,
            session=session
        )
        if not reward.fits(ctx=ctx, env=env):
            error = {
                "message": f"Badge {reward.reward().reward}: this User doesn't "   # noqa: E501
                "Fit at this moment.",
                "rule": reward.failed_conditions()
            }
            self.error(
                response=error
            )
        async with await system.connection.acquire() as conn:
            # Step 4: Evaluate if reward can be applied to this user:
            if not await reward.evaluate(
                ctx=ctx, env=env
            ):
                self.error(
                    response={
                        "message": f"User {user.user_id}:{user.display_name} Cannot Receive the Badge.",   # noqa: E501
                        "reason": reward.failed_conditions()
                    }
                )
            # Step 5: Check if the reward is already assigned to the user
            if await reward.has_awarded(
                user, env, conn, reward.reward().timeframe
            ):
                # Check if it's due to cooldown or actual duplicate
                query = """
                SELECT awarded_at FROM rewards.users_rewards
                WHERE receiver_user = $1::int
                AND reward_id = $2::int
                AND revoked = FALSE
                AND deleted_at IS NULL
                ORDER BY awarded_at DESC
                LIMIT 1;
                """
                last_award = await conn.fetch_one(
                    query, user.user_id, reward.id
                )

                time_since_last = None
                if last_award:
                    time_since_last = env.timestamp - last_award['awarded_at']

                error_msg = f"User {user.user_id}:{user.display_name} already received the Badge."

                if time_since_last and time_since_last.total_seconds() < 60:
                    error_msg = (
                        f"Badge cooldown active. Please wait "
                        f"{60 - int(time_since_last.total_seconds())} more seconds "
                        f"before awarding this badge again."
                    )

                self.error(
                    response={
                        "message": error_msg
                    }
                )
            # Step 6: Apply reward to User
            try:
                # Create a clean data dictionary for the apply method
                apply_data = {
                    **data.to_dict()
                }

                # Remove None values to avoid issues
                apply_data = {
                    k: v for k, v in apply_data.items() if v is not None
                }
                r, error = await reward.apply(ctx, env, conn, **apply_data)
                if error:
                    self.error(
                        response={
                            "message": error
                        },
                        status=406
                    )
            except Exception:
                raise
            return self.json_response(r)


class EmployeeSearchHandler(FormModel):
    """Handler for employee search functionality."""
    model: BaseModel = Employee
    path: str = "/api/v1/rewards/employee_search"

    async def get(self):
        """Search employees by display_name using query parameter."""
        try:
            # Get the search parameter from query string
            search_name = self.request.query.get('name', '')

            if not search_name:
                return self.json_response(
                    status=400,
                    response={"error": "Missing 'name' query parameter"}
                )

            # Get reward system and database connection
            try:
                system = self.request.app['reward_engine']
                connection = system.connection
            except KeyError:
                return self.json_response(
                    status=500,
                    response={"error": "Reward system not available"}
                )
            except Exception as err:
                return self.json_response(
                    status=500,
                    response={"error": f"Failed to get database connection: {err}"}
                )

            # SQL query to search employees by display_name
            sql = """
            SELECT
                u.user_id,
                e.display_name,
                e.corporate_email
            FROM troc.troc_employees AS e
            LEFT JOIN auth.users AS u
                ON e.corporate_email = u.email
            WHERE e.status = 'Active'
                AND u.user_id IS NOT NULL
                AND e.display_name ILIKE $1
            ORDER BY e.display_name
            LIMIT 50
            """

            async with await connection.acquire() as conn:
                try:
                    # Execute the query with the search parameter
                    search_pattern = f"%{search_name}%"
                    result, error = await conn.query(
                        sql,
                        search_pattern
                    )

                    if error:
                        return self.json_response(
                            status=500,
                            response={"error": f"Database error: {error}"}
                        )

                    if not result:
                        return self.json_response(
                            status=404,
                            response={"message": "No employees found", "results": []}
                        )

                    # Convert results to list of dictionaries
                    employees = [dict(row) for row in result]

                    return self.json_response(
                        response={
                            "message": f"Found {len(employees)} employees",
                            "results": employees
                        },
                        status=200
                    )

                except Exception as err:
                    return self.json_response(
                        status=500,
                        response={"error": f"Search failed: {str(err)}"}
                    )

        except Exception as err:
            return self.json_response(
                status=500,
                response={"error": f"Unexpected error: {str(err)}"}
            )
