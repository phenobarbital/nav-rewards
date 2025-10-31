from collections.abc import Iterable
from typing import Optional
import aiormq
import pandas as pd
from querysource.queries.qs import QS
from querysource.exceptions import DataNotFound
from resources.users import User
from ..base import RewardObject
from ...models import (
    RewardView,
)
from ...env import Environment


class EventReward(RewardObject):
    """
    Event Reward.

    A reward/badge assigned based on events triggered by Event System.
    """
    type: str = 'event'

    def __init__(
        self,
        reward: RewardView,
        rules: Optional[list] = None,
        conditions: Optional[dict] = None,
        **kwargs
    ) -> None:
        super().__init__(reward, rules, conditions, **kwargs)

    async def _get_dataset(
        self,
        data: Iterable,
        event: aiormq.abc.DeliveredMessage,
        env: Environment
    ) -> Iterable:
        # 1.- obtain the event data:
        event_name = event.delivery.routing_key
        if not self._events:
            return []
        events = self._events.copy()
        event_data = {}
        for evt in events:
            if event_name in evt:
                event_data = evt[event_name]
        # 2. using the event data to generate the dataset:
        target, target_value = next(iter(event_data.items()))
        del event_data[target]
        if target == 'slug':
            try:
                # Using QuerySource to fetch Data:
                qry = QS(
                    slug=target_value,
                    lazy=True,
                    **event_data
                )
                await qry.build_provider()
                res, error = await qry.query()
                if not res:
                    raise DataNotFound(
                        f"QS({target_value}): Data Not Found"
                    )
                if error:
                    raise RuntimeError(
                        f"QS({target_value}): {error}"
                    )
                df = pd.DataFrame(
                    [dict(r) for r in res],
                    dtype=str
                )
                df.infer_objects()
                df = df.convert_dtypes(
                    convert_string=True
                )
                return df
            except Exception as err:
                self.logger.error(
                    f"Error Fetching Data: {err}"
                )
                return []
        return []

    async def evaluate_event(
        self,
        data: Iterable,
        event: aiormq.abc.DeliveredMessage,
        env: Environment
    ) -> Iterable:
        """
        Evaluate the event data against the Rules.

        :param data: The event data to be evaluated.
        :param env: The environment information, such as the current time.
        :param conn: The database connection.
        :return: an iterable List (or pandas dataframe) of potential users.
        """
        # Step 1: Generate the dataset to be evaluated by Rules
        dataset = await self._get_dataset(data, event, env)
        if isinstance(dataset, pd.DataFrame) and dataset.empty:
            return []
        # Step 2: Evaluate the dataset against the Rules
        # Generate list of potential Users:
        potential_users = []
        for rule in self._rules:
            if rule.fits(None, env):
                potential_users = await rule.evaluate_dataset(env, dataset)
        return potential_users
