import random
from dataclasses import dataclass


@dataclass
class ConstantRate:
    """A constant requests/second rate.

    Args:
        n_requests (int): Maximum number of requests per period.
        seconds (float): The period.
    """

    n_requests: int
    seconds: float

    def __post_init__(self):
        self.sleep_seconds = self.seconds / self.n_requests
        self.min_sleep_seconds = self.sleep_seconds
        self.max_sleep_seconds = self.sleep_seconds


@dataclass
class VariableRate:
    """A bounded random rate.

    Args:
        min_n_requests (float): Minimum number of requests per period.
        max_n_requests (float): Maximum number of requests per period.
        seconds (float): The period.
    """

    min_n_requests: float
    max_n_requests: float
    seconds: float

    def __post_init__(self):
        # calculate the bounds.
        self.min_sleep_seconds = self.seconds / self.min_n_requests
        self.max_sleep_seconds = self.seconds / self.max_n_requests

    @property
    def sleep_seconds(self) -> float:
        """Return a random rate within limits.

        Returns:
            float: The rate in requests/second.
        """
        return random.uniform(self.min_sleep_seconds, self.max_sleep_seconds)
