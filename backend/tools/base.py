"""Base class for reusable tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Tool(ABC):
    """A named, reusable capability invoked by agents or workflow nodes."""

    name: str

    @abstractmethod
    def run(self, *args: Any, **kwargs: Any) -> Any:
        """Execute the tool and return its result."""
        ...
