from pathlib import Path, PurePath
import aiofiles
import orjson
from datamodel.exceptions import ValidationError
from .abstract import AbstractStorage, StorageError


class FileStorage(AbstractStorage):
    """FileStorage.

    Description: Extracting Rewards definition from Files.

    Args:
        path (str|path): Filename containing Rewards.

    Raises:
        RuntimeError: Some exception raised.

    Returns:
        A collection of Rewards loaded from Storage.
    """
    def __init__(self, path: PurePath) -> None:
        super().__init__()
        self.path = path
        if isinstance(path, str):
            self.path = Path(path)
        if not self.path.exists():
            raise StorageError(
                f"File {self.path} does not exist."
            )
        self.file = None

    async def load_rewards(self):
        """load_rewards.

        Load all Rewards from Storage.
        """
        if self.file is None:
            raise StorageError("File not opened")
        content = await self.file.read()
        content = orjson.loads(content)
        if not isinstance(content, list):
            raise StorageError(
                "Invalid Rewards file."
            )
        rewards = []
        for reward in content:
            # TODO check content
            try:
                if r := self._create_rewards(reward):
                    rewards.append(
                        r
                    )
            except (TypeError, ValueError) as exc:
                raise StorageError(
                    f"Error loading Reward: {exc}"
                ) from exc
            except Exception:
                raise
        return rewards

    async def open(self):
        """Open the Storage Connection."""
        self.file = await aiofiles.open(self.path, mode='r')

    async def close(self):
        """Close the Storage Connection."""
        if self.file:
            await self.file.close()
            self.file = None
