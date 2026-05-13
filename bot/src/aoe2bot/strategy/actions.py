"""Priority-based action queue for 1-command-per-tick triage."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Callable

logger = logging.getLogger(__name__)


class Priority(IntEnum):
    CRITICAL = 100
    URGENT = 80
    HIGH = 60
    NORMAL = 40
    LOW = 20
    IDLE = 0


@dataclass
class Action:
    priority: int
    name: str
    execute: Callable[[], dict]


class ActionQueue:
    """Collects candidate actions, executes the single highest-priority one."""

    def __init__(self) -> None:
        self._actions: list[Action] = []

    def add(
        self,
        priority: int | Priority,
        name: str,
        execute: Callable[[], dict],
        *,
        condition: bool = True,
    ) -> None:
        if condition:
            self._actions.append(Action(priority=int(priority), name=name, execute=execute))

    def execute_best(self) -> tuple[str, dict] | None:
        if not self._actions:
            return None
        self._actions.sort(key=lambda a: a.priority, reverse=True)
        best = self._actions[0]
        try:
            result = best.execute()
            return (best.name, result)
        except Exception as exc:
            logger.warning("Action %s failed: %s", best.name, exc)
            return (best.name, {"success": False, "error": str(exc)})

    @property
    def pending(self) -> list[tuple[int, str]]:
        return [(a.priority, a.name) for a in sorted(self._actions, key=lambda a: a.priority, reverse=True)]

    def clear(self) -> None:
        self._actions.clear()
