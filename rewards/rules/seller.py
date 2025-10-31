import pandas as pd
from .computed import ComputedRule

class BestSeller(ComputedRule):
    """BestSeller Rule class.

    Rule that checks if user is the best seller over a period of time.

    Attributes:
    ----------
    conditions: dict: dictionary of conditions affecting the Rule object
    """
    def __init__(self, conditions: dict = None, **kwargs):
        super().__init__(conditions, **kwargs)
        self.name = "BestSeller"
        self.description = "user is the best seller over a period of time."

    async def _get_candidates(
        self,
        env,
        dataset
    ) -> list:
        """
        Generate a List the potencial users to match the rule.

        :param dataset: The dataset to be evaluated.
        :param env: The environment information, such as the current time.
        :return: True if this Rule can be applied to User.
        """
        try:
            dataset[self.column] = pd.to_numeric(
                dataset[self.column],
                errors='coerce'
            )
            df_sorted = dataset.sort_values(
                by=[self.column], ascending=False
            )
            return df_sorted.head(self.count)
        except Exception as err:
            self.logger.error(
                f"Error Sorting Data: {err}"
            )
            return []
