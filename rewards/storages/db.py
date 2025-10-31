"""DB (asyncdb) Extension.
DB connection for any Application.
"""
from collections.abc import Callable
from navconfig.logging import logging
from asyncdb import AsyncDB
from asyncdb.exceptions import ProviderError, DriverError
from .abstract import AbstractStorage, StorageError
from ..models import RewardView

class DbStorage(AbstractStorage):
    """DbStorage.

    Description: Abstract Storage for any asyncdb-based DB connection.

    Args:
        dsn (str): default DSN (if none, use default.)
        params (dict): optional connection parameters (if DSN is none)

    Raises:
        RuntimeError: Some exception raised.
        web.InternalServerError: Database connector is not installed.

    Returns:
        A collection of Rewards loaded from Storage.
    """
    name: str = 'asyncdb'
    driver: str = 'pg'
    timeout: int = 10

    def __init__(
            self,
            driver: str = 'pg',
            dsn: str = None,
            **kwargs
    ) -> None:
        super().__init__()
        self.driver = driver or 'pg'
        self.timeout = kwargs.pop('timeout', 10)
        self.params = kwargs.pop('params', {})
        self.conn: Callable = None
        self._dsn: str = dsn
        if not self._dsn and not self.params:
            raise StorageError(
                "DB: No DSN or Parameters for DB connection."
            )

    async def open(self):
        try:
            self.conn = AsyncDB(
                self.driver,
                dsn=self._dsn,
                params=self.params,
                timeout=self.timeout
            )
            return self.conn
        except (ProviderError, DriverError) as err:
            logging.exception(
                f"Error on Startup {self.name} Backend: {err!s}"
            )
            raise StorageError(
                f"Error on Startup {self.name} Backend: {err!s}"
            ) from err

    async def close(self):
        try:
            await self.conn.close()
        except AttributeError:
            pass
        except ProviderError as err:
            raise StorageError(
                f"Error on Closing Connection {self.name}: {err!s}"
            ) from err

    async def load_rewards(self):
        """load_rewards.

        Load all Rewards from Storage.
        """
        rewards = []
        try:
            async with await self.conn.connection() as conn:
                RewardView.Meta.connection = conn
                result = await RewardView.all()
                for row in result:
                    reward = row.to_dict()
                    if r := self._create_rewards(reward):
                        rewards.append(
                            r
                        )
        except (ProviderError, DriverError) as err:
            logging.exception(
                f"Error on Fetching Rewards: {err!s}"
            )
            raise StorageError(
                f"Error on Fetching Rewards: {err!s}"
            ) from err
        return rewards
