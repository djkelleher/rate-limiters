from dataclasses import dataclass
from typing import Any


@dataclass
class ScopedMap:
    """Key and value that will be set to None when they go out of context manager scope."""

    key: str = None
    value: Any = None

    def __enter__(self):
        pass

    def __exit__(self, *args):
        self.key = None
        self.value = None

    @property
    def is_set(self):
        return self.key is not None and self.value is not None
