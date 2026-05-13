"""Abstract base class for all strategies."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..controller import GameController
    from .world import WorldState


class BaseStrategy(ABC):

    def __init__(self, ctrl: GameController):
        self.ctrl = ctrl
        self.running = False

    @property
    @abstractmethod
    def name(self) -> str: ...

    @abstractmethod
    def on_start(self) -> None:
        """Called once when the strategy begins. Use for initial setup."""
        ...

    @abstractmethod
    def on_tick(self, raw_state: dict, world: WorldState | None = None) -> str | None:
        """Called each tick with fresh game state. Returns name of action taken."""
        ...

    @abstractmethod
    def is_complete(self, raw_state: dict) -> bool:
        """Whether this strategy has reached its goal."""
        ...
