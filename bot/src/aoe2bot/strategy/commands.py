"""Command tracking — issue commands, verify outcomes, prevent duplicates."""

from __future__ import annotations

import uuid
import logging
from dataclasses import dataclass, field
from enum import Enum, auto

from .spatial import Position
from .units import UnitTracker
from .buildings import BuildingTracker

logger = logging.getLogger(__name__)

MAX_HISTORY = 20

# Timeout per command type (game seconds)
_TIMEOUTS: dict[str, float] = {
    "BUILD": 90.0,
    "GATHER": 30.0,
    "TRAIN": 45.0,
    "MOVE": 30.0,
    "RESEARCH": 120.0,
}


class CommandStatus(Enum):
    PENDING = auto()
    ACKNOWLEDGED = auto()
    SUCCEEDED = auto()
    FAILED = auto()
    EXPIRED = auto()


@dataclass
class TrackedCommand:
    id: str
    command_type: str
    issued_at: float
    target_position: Position | None = None
    target_id: int | None = None
    unit_ids: list[int] = field(default_factory=list)
    building_type: str | None = None
    status: CommandStatus = CommandStatus.PENDING
    key: str | None = None

    @property
    def is_active(self) -> bool:
        return self.status in (CommandStatus.PENDING, CommandStatus.ACKNOWLEDGED)


class CommandTracker:

    def __init__(self) -> None:
        self._commands: dict[str, TrackedCommand] = {}
        self._last_population: int = 0
        self._recently_succeeded: list[TrackedCommand] = []
        self._recently_failed: list[TrackedCommand] = []

    def issue(
        self,
        command_type: str,
        target_position: Position | None = None,
        target_id: int | None = None,
        unit_ids: list[int] | None = None,
        building_type: str | None = None,
        game_time: float = 0.0,
        key: str | None = None,
    ) -> str:
        cmd_id = uuid.uuid4().hex[:8]
        cmd = TrackedCommand(
            id=cmd_id,
            command_type=command_type,
            issued_at=game_time,
            target_position=target_position,
            target_id=target_id,
            unit_ids=unit_ids or [],
            building_type=building_type,
            key=key,
        )
        self._commands[cmd_id] = cmd
        logger.debug("Issued %s %s id=%s", command_type, building_type or "", cmd_id)
        return cmd_id

    def update(
        self,
        units: UnitTracker,
        buildings: BuildingTracker,
        game_time: float,
        population: int | None = None,
    ) -> None:
        if population is not None:
            self._last_population = population

        self._recently_succeeded.clear()
        self._recently_failed.clear()

        for cmd in list(self._commands.values()):
            if not cmd.is_active:
                continue

            elapsed = game_time - cmd.issued_at
            timeout = _TIMEOUTS.get(cmd.command_type, 60.0)

            if cmd.command_type == "BUILD":
                self._check_build(cmd, buildings, elapsed, timeout)
            elif cmd.command_type == "GATHER":
                self._check_gather(cmd, units, elapsed, timeout)
            elif cmd.command_type == "TRAIN":
                self._check_train(cmd, elapsed, timeout, population)
            elif cmd.command_type == "MOVE":
                self._check_move(cmd, units, elapsed, timeout)
            elif cmd.command_type == "RESEARCH":
                self._check_research(cmd, elapsed, timeout)

        self._cleanup()

    def is_pending(self, command_type: str, near: Position | None = None) -> bool:
        for cmd in self._commands.values():
            if not cmd.is_active or cmd.command_type != command_type:
                continue
            if near is None:
                return True
            if cmd.target_position and cmd.target_position.distance_to(near) <= 8.0:
                return True
        return False

    def has_active_build(self, building_type: str) -> bool:
        bt = building_type.upper()
        for cmd in self._commands.values():
            if not cmd.is_active or cmd.command_type != "BUILD":
                continue
            if cmd.building_type and cmd.building_type.upper() == bt:
                return True
        return False

    def has_active_train(self) -> bool:
        return any(
            cmd.is_active and cmd.command_type == "TRAIN"
            for cmd in self._commands.values()
        )

    def get_failed(self) -> list[TrackedCommand]:
        return list(self._recently_failed)

    def get_succeeded(self) -> list[TrackedCommand]:
        return list(self._recently_succeeded)

    def can_issue(self, command_type: str, key: str) -> bool:
        for cmd in self._commands.values():
            if not cmd.is_active:
                continue
            if cmd.command_type == command_type and cmd.key == key:
                return False
        return True

    # ── Private verification ──

    def _mark(self, cmd: TrackedCommand, status: CommandStatus) -> None:
        cmd.status = status
        if status == CommandStatus.SUCCEEDED:
            self._recently_succeeded.append(cmd)
        elif status in (CommandStatus.FAILED, CommandStatus.EXPIRED):
            self._recently_failed.append(cmd)

    def _check_build(
        self,
        cmd: TrackedCommand,
        buildings: BuildingTracker,
        elapsed: float,
        timeout: float,
    ) -> None:
        if cmd.building_type and cmd.target_position:
            placed = buildings.was_building_placed(
                cmd.building_type, cmd.target_position, since=cmd.issued_at
            )
            if placed:
                if cmd.status == CommandStatus.PENDING:
                    self._mark(cmd, CommandStatus.ACKNOWLEDGED)
                # Check if the building is now complete
                nearest = buildings.get_nearest(cmd.building_type, cmd.target_position)
                if nearest and nearest.is_complete and nearest.first_seen >= cmd.issued_at:
                    self._mark(cmd, CommandStatus.SUCCEEDED)
                    return

        if elapsed > timeout:
            self._mark(cmd, CommandStatus.EXPIRED)

    def _check_gather(
        self,
        cmd: TrackedCommand,
        units: UnitTracker,
        elapsed: float,
        timeout: float,
    ) -> None:
        any_moved = False
        for uid in cmd.unit_ids:
            unit = units.get_unit(uid)
            if unit and (unit.is_moving or not unit.is_idle):
                any_moved = True
                break

        if any_moved:
            if cmd.status == CommandStatus.PENDING:
                self._mark(cmd, CommandStatus.ACKNOWLEDGED)
            if elapsed > 10.0:
                self._mark(cmd, CommandStatus.SUCCEEDED)
                return

        if elapsed > timeout:
            self._mark(cmd, CommandStatus.EXPIRED)

    def _check_train(
        self,
        cmd: TrackedCommand,
        elapsed: float,
        timeout: float,
        population: int | None,
    ) -> None:
        if population is not None and population > self._last_population:
            self._mark(cmd, CommandStatus.SUCCEEDED)
            return

        if elapsed > timeout:
            self._mark(cmd, CommandStatus.EXPIRED)

    def _check_move(
        self,
        cmd: TrackedCommand,
        units: UnitTracker,
        elapsed: float,
        timeout: float,
    ) -> None:
        any_moved = False
        any_arrived = False

        for uid in cmd.unit_ids:
            unit = units.get_unit(uid)
            if unit is None:
                continue
            if unit.is_moving:
                any_moved = True
            if cmd.target_position and unit.position.distance_to(cmd.target_position) <= 3.0:
                any_arrived = True

        if any_moved and cmd.status == CommandStatus.PENDING:
            self._mark(cmd, CommandStatus.ACKNOWLEDGED)

        if any_arrived:
            self._mark(cmd, CommandStatus.SUCCEEDED)
            return

        if elapsed > timeout:
            self._mark(cmd, CommandStatus.EXPIRED)

    def _check_research(
        self, cmd: TrackedCommand, elapsed: float, timeout: float
    ) -> None:
        if elapsed > timeout:
            self._mark(cmd, CommandStatus.EXPIRED)

    def _cleanup(self) -> None:
        active = {
            cid: cmd for cid, cmd in self._commands.items() if cmd.is_active
        }
        finished = {
            cid: cmd for cid, cmd in self._commands.items() if not cmd.is_active
        }
        # Keep all active + last N finished
        if len(finished) > MAX_HISTORY:
            sorted_finished = sorted(
                finished.items(), key=lambda kv: kv[1].issued_at, reverse=True
            )
            finished = dict(sorted_finished[:MAX_HISTORY])
        self._commands = {**active, **finished}
