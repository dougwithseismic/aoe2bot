"""Priority-based event queue with multi-step action sequences."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from .actions import Priority

logger = logging.getLogger(__name__)


@dataclass
class QueuedAction:
    name: str
    priority: int
    execute: Callable[[], dict]
    condition: Callable[[], bool] = field(default_factory=lambda: lambda: True)


@dataclass
class WaitCondition:
    name: str
    check: Callable[[], bool]
    timeout: float
    on_timeout: str = "skip"  # "skip" | "abort" | "retry"


@dataclass
class ActionSequence:
    name: str
    priority: int
    steps: list[QueuedAction | WaitCondition]
    current_step: int = 0
    started_at: float | None = None
    step_started_at: float | None = None

    @property
    def is_complete(self) -> bool:
        return self.current_step >= len(self.steps)

    @property
    def current(self) -> QueuedAction | WaitCondition | None:
        if self.is_complete:
            return None
        return self.steps[self.current_step]

    def advance(self, game_time: float) -> None:
        self.current_step += 1
        self.step_started_at = game_time


class EventQueue:
    def __init__(self) -> None:
        self._sequences: list[ActionSequence] = []
        self._standalone: list[QueuedAction] = []
        self._preempted: list[QueuedAction] = []

    def add_action(self, action: QueuedAction) -> None:
        self._standalone.append(action)

    def add_sequence(self, sequence: ActionSequence) -> None:
        self._sequences.append(sequence)

    def preempt(self, action: QueuedAction) -> None:
        self._preempted.append(action)

    def has_active(self, name_prefix: str) -> bool:
        for seq in self._sequences:
            if seq.name.startswith(name_prefix):
                return True
        for act in self._standalone:
            if act.name.startswith(name_prefix):
                return True
        return False

    def cancel(self, name: str) -> None:
        self._sequences = [s for s in self._sequences if s.name != name]
        self._standalone = [a for a in self._standalone if a.name != name]
        self._preempted = [a for a in self._preempted if a.name != name]

    def get_active_sequences(self) -> list[ActionSequence]:
        return list(self._sequences)

    def clear_below_priority(self, priority: int) -> None:
        self._sequences = [s for s in self._sequences if s.priority >= priority]
        self._standalone = [a for a in self._standalone if a.priority >= priority]

    def tick(self, game_time: float) -> dict | None:
        if self._preempted:
            action = self._preempted.pop(0)
            return self._execute_action(action)

        # Compare highest-priority standalone vs highest-priority sequence
        # The higher priority wins — CRITICAL standalone beats HIGH sequence
        seq_prio = max((s.priority for s in self._sequences if not s.is_complete), default=-1)
        self._standalone.sort(key=lambda a: a.priority, reverse=True)
        standalone_prio = self._standalone[0].priority if self._standalone else -1

        if standalone_prio > seq_prio:
            for i, action in enumerate(self._standalone):
                try:
                    if action.condition():
                        self._standalone.pop(i)
                        return self._execute_action(action)
                except Exception as exc:
                    logger.warning("Condition check failed for %s: %s", action.name, exc)

        result = self._tick_sequences(game_time)
        if result is not _NOTHING:
            return result

        # Fall through to standalone if sequences didn't consume the tick
        for i, action in enumerate(self._standalone):
            try:
                if action.condition():
                    self._standalone.pop(i)
                    return self._execute_action(action)
            except Exception as exc:
                logger.warning("Condition check failed for %s: %s", action.name, exc)

        return None

    def _tick_sequences(self, game_time: float) -> dict | None | object:
        self._sequences.sort(key=lambda s: s.priority, reverse=True)

        for seq in self._sequences:
            if seq.is_complete:
                continue

            if seq.started_at is None:
                seq.started_at = game_time
                seq.step_started_at = game_time

            step = seq.current
            if step is None:
                continue

            if isinstance(step, WaitCondition):
                self._handle_wait(seq, step, game_time)
                # WaitConditions don't consume the tick — let standalone actions fire
                continue

            if isinstance(step, QueuedAction):
                try:
                    if step.condition():
                        result = self._execute_action(step)
                        seq.advance(game_time)
                        self._cleanup_sequences()
                        return result
                except Exception as exc:
                    logger.warning("Condition check failed for %s: %s", step.name, exc)
                # Condition not met — don't consume the tick, let lower priority work
                continue

        return _NOTHING

    def _handle_wait(
        self, seq: ActionSequence, wait: WaitCondition, game_time: float
    ) -> dict | None:
        elapsed = game_time - seq.step_started_at

        try:
            if wait.check():
                logger.debug("Wait '%s' satisfied", wait.name)
                seq.advance(game_time)
                self._cleanup_sequences()
                return None
        except Exception as exc:
            logger.warning("Wait check failed for %s: %s", wait.name, exc)

        if elapsed >= wait.timeout:
            logger.info(
                "Wait '%s' timed out after %.1fs, action=%s",
                wait.name,
                elapsed,
                wait.on_timeout,
            )
            if wait.on_timeout == "skip":
                seq.advance(game_time)
            elif wait.on_timeout == "abort":
                seq.current_step = len(seq.steps)  # mark complete
            # "retry" — do nothing, check again next tick

        self._cleanup_sequences()
        return None

    def _execute_action(self, action: QueuedAction) -> dict:
        try:
            result = action.execute()
            logger.debug("Executed '%s': %s", action.name, result)
            return result
        except Exception as exc:
            logger.warning("Action '%s' failed: %s", action.name, exc)
            return {"success": False, "error": str(exc)}

    def _cleanup_sequences(self) -> None:
        self._sequences = [s for s in self._sequences if not s.is_complete]


_NOTHING = object()
