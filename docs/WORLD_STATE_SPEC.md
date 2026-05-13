# World State Model — Project Specification

## Problem Statement

The current strategy engine issues commands and hopes for the best. It doesn't know:
- Whether a command actually took effect (vils walking to build site? or standing idle?)
- What each villager is doing right now (gathering wood? walking? building?)
- Whether a building is under construction, complete, or never started
- What areas of the map have been explored vs fog of war
- Whether the scout has reached its waypoint or is still walking

This causes cascading failures: spamming duplicate build commands, sending vils to depleted resources, trying to build lumber camps in unexplored fog, and not knowing when to issue the next command.

## Architecture

```
                    ┌─────────────────────────┐
                    │      WorldState          │
                    │  (single source of truth)│
                    └────┬───┬───┬───┬───┬────┘
                         │   │   │   │   │
         ┌───────────────┘   │   │   │   └───────────────┐
         ▼                   ▼   │   ▼                   ▼
   ┌───────────┐   ┌──────────┐ │ ┌──────────┐   ┌───────────┐
   │   Unit    │   │ Building │ │ │   Map    │   │  Command  │
   │  Tracker  │   │ Tracker  │ │ │Knowledge │   │  Tracker  │
   └───────────┘   └──────────┘ │ └──────────┘   └───────────┘
                                │
                         ┌──────┘
                         ▼
                   ┌───────────┐
                   │   Event   │
                   │   Queue   │
                   └───────────┘
```

Every tick, the `WorldState` ingests the raw game state and updates all trackers.
The strategy reads the WorldState and makes decisions.
Commands go through the EventQueue, which feeds them to the game one per tick.

## Design Principles

1. **Observe, don't assume.** Never hardcode timers. Watch for actual state changes. A building is done when hp == maxHp, not after "30 seconds".

2. **Track deltas, not snapshots.** The system notices when things CHANGE: a vil that was moving is now idle, a building that was at 50% is now at 100%, a resource that existed is now gone.

3. **Commands have expected outcomes.** When we issue "build house at (36,110)", we expect: a vil starts moving toward (36,110), then a foundation appears, then hp ticks up, then it completes. If we don't see the first step within a few ticks, the command failed.

4. **One queue, prioritized.** All actions go through the EventQueue. Multi-step sequences (scout A→B→C) are first-class. Higher priority actions can preempt lower ones.

5. **Positions are truth.** Everything is spatial. A vil at (30, 106) near berries at (29, 106) is probably foraging. A vil at (36, 110) where we ordered a house is probably building.

---

## Feature 1: Unit Tracker

### Purpose
Track every owned unit's position, state, and inferred task.

### Data Model
```python
@dataclass
class TrackedUnit:
    id: int
    unit_class: int          # 904=villager, 961=scout, etc.
    position: Position
    previous_position: Position | None
    hp: int
    max_hp: int
    is_idle: bool
    is_moving: bool          # position != previous_position
    inferred_task: UnitTask  # IDLE, GATHERING, BUILDING, WALKING, SCOUTING
    task_target: int | None  # resource/building ID they're working on
    last_command: str | None # what we last told this unit to do
    last_command_time: float # game time when we issued it
    last_seen: float         # game time when last observed
```

### Task Inference
The tracker infers what a unit is doing by watching state changes:
- **IDLE**: `is_idle == True` in game state
- **GATHERING**: not idle, position near a known resource, not moving
- **BUILDING**: not idle, position near an in-progress building
- **WALKING**: position changed since last tick
- **SCOUTING**: we issued a scout/move command and they're still moving

### Interface
```python
class UnitTracker:
    def update(self, all_units: list[dict], game_time: float) -> None
    def get_idle_vils(self) -> list[TrackedUnit]
    def get_vils_by_task(self, task: UnitTask) -> list[TrackedUnit]
    def get_nearest_vil(self, pos: Position, prefer_idle: bool = True) -> TrackedUnit | None
    def get_unit(self, unit_id: int) -> TrackedUnit | None
    def get_vils_near(self, pos: Position, radius: float) -> list[TrackedUnit]
    def count_vils_on_resource(self, resource_type: str) -> int
    def was_command_acknowledged(self, unit_id: int) -> bool
```

### Key Behaviors
- Detects when a vil assigned to gather goes idle (resource depleted)
- Knows which vils are already assigned so we don't re-assign them
- Tracks whether a commanded unit started moving (command acknowledged)
- Groups vils by current task for eco distribution awareness

---

## Feature 2: Building Tracker

### Purpose
Track every owned building's existence, construction progress, and completion.

### Data Model
```python
@dataclass  
class TrackedBuilding:
    id: int
    name: str                    # raw game name e.g. "LumberCamp EAST"
    normalized_name: str         # e.g. "LUMBERCAMP"
    building_type: str           # e.g. "LUMBER_CAMP", "TOWN_CENTER", "HOUSE"
    position: Position
    hp: int
    max_hp: int
    is_complete: bool            # hp == max_hp
    construction_pct: float      # hp / max_hp * 100
    first_seen: float            # game time when first detected
    completed_at: float | None   # game time when construction finished
    builders: list[int]          # unit IDs of vils building this (inferred)
```

### Building Type Normalization
Maps game names to canonical types:
- "LumberCamp EAST" → LUMBER_CAMP
- "TownCenter DARK (Back)" → TOWN_CENTER  
- "House DARK Age1" → HOUSE
- "Mill DARK Age" → MILL

Uses the same `_normalize()` strip-and-uppercase approach.

### Interface
```python
class BuildingTracker:
    def update(self, buildings: list[dict], game_time: float) -> None
    def get_by_type(self, building_type: str) -> list[TrackedBuilding]
    def count_type(self, building_type: str) -> int
    def has_complete(self, building_type: str) -> bool
    def get_in_progress(self) -> list[TrackedBuilding]
    def get_nearest(self, building_type: str, pos: Position) -> TrackedBuilding | None
    def was_building_placed(self, building_type: str, near: Position, since: float) -> bool
    def get_new_buildings(self) -> list[TrackedBuilding]  # appeared since last update
    def get_completed_buildings(self) -> list[TrackedBuilding]  # completed since last update
```

### Key Behaviors
- Detects when a new building foundation appears (command succeeded)
- Tracks construction progress ticking up
- Fires "building complete" when hp reaches max_hp
- Knows how many of each type exist (complete AND in-progress separately)

---

## Feature 3: Command Tracker

### Purpose
Track issued commands and verify their outcomes. Prevents duplicate commands and knows when a command failed.

### Data Model
```python
@dataclass
class TrackedCommand:
    id: str                      # unique command ID
    command_type: str             # BUILD, GATHER, TRAIN, MOVE, RESEARCH
    issued_at: float             # game time
    target_position: Position | None
    target_id: int | None
    unit_ids: list[int]          # units involved
    expected_outcome: str        # what we expect to see
    status: CommandStatus        # PENDING, ACKNOWLEDGED, SUCCEEDED, FAILED, EXPIRED
    outcome_check_fn: str | None # what to check for success

class CommandStatus(Enum):
    PENDING = auto()       # just issued, waiting for acknowledgement
    ACKNOWLEDGED = auto()  # saw units start moving / state change
    SUCCEEDED = auto()     # expected outcome observed
    FAILED = auto()        # units went idle without outcome
    EXPIRED = auto()       # too long without any change
```

### Outcome Verification
Each command type has expected outcomes:
- **BUILD(house, pos)**: expect new building near pos within ~15s game time, then hp ticking up
- **GATHER(vils, resource_id)**: expect vils to stop being idle and move toward resource
- **TRAIN(villager)**: expect population to increase by 1 within ~25s game time
- **MOVE(units, pos)**: expect units' positions to start changing toward pos
- **RESEARCH(tech_id)**: expect tech to show as researched after research time

### Interface
```python
class CommandTracker:
    def issue(self, cmd: TrackedCommand) -> str  # returns command ID
    def update(self, world: WorldState, game_time: float) -> None
    def is_pending(self, command_type: str, near: Position | None = None) -> bool
    def has_active_build(self, building_type: str) -> bool
    def has_active_train(self) -> bool
    def get_failed(self) -> list[TrackedCommand]
    def get_succeeded(self) -> list[TrackedCommand]  # since last check
    def can_issue(self, command_type: str, key: str) -> bool  # no duplicate active
```

### Key Behaviors
- Won't let strategy issue "build house" if there's already an active BUILD_HOUSE command
- Detects when a build command failed (vils went idle, no foundation appeared)
- Reports successes so the strategy knows a building is going up
- Cleans up expired commands automatically

---

## Feature 4: Map Knowledge

### Purpose
Track what areas of the map have been explored and where resources are.

### Data Model
```python
@dataclass
class MapKnowledge:
    width: int
    height: int
    explored: set[tuple[int, int]]     # tiles we've seen
    resources: dict[str, list[KnownResource]]  # by type
    last_scan_time: float

@dataclass
class KnownResource:
    id: int
    resource_type: str          # trees, gold, stone, forage, farm
    position: Position
    first_seen: float
    last_seen: float
    depleted: bool              # was here but isn't in latest scan
```

### Exploration Tracking
- When a unit moves to a new area, mark tiles around it as explored (LOS radius ~8 tiles)
- Track which directions from base are unexplored
- Score exploration coverage: "we've explored 60% of the inner ring around TC"

### Resource Discovery
- Resources from `scan_resources` are only visible in explored areas
- Track when resources appear (discovered by scouting)
- Track when resources disappear (depleted)
- Know which forage bushes are depleted vs undiscovered

### Interface
```python
class MapKnowledge:
    def update(self, scan: dict, unit_positions: list[Position], game_time: float) -> None
    def mark_explored(self, pos: Position, radius: float = 8) -> None
    def is_explored(self, pos: Position) -> bool
    def get_unexplored_direction(self, from_pos: Position) -> Position | None
    def get_resources(self, resource_type: str) -> list[KnownResource]
    def get_nearest_resource(self, resource_type: str, to: Position) -> KnownResource | None
    def get_exploration_pct(self, center: Position, radius: float) -> float
    def has_discovered(self, resource_type: str) -> bool
```

### Key Behaviors
- Knows to scout north because that direction is unexplored
- Knows not to send vils to forage that was depleted last scan
- Tracks tree coverage so lumber camp placement picks the best treeline
- Distinguishes "no gold found" (fog) vs "gold is gone" (depleted)

---

## Feature 5: Event Queue

### Purpose
Queue multi-step action sequences that execute over multiple ticks. Supports priority-based preemption and conditional waits.

### Data Model
```python
@dataclass
class QueuedAction:
    name: str
    priority: int                    # same Priority enum as ActionQueue
    execute: Callable                 # the game command to send
    condition: Callable[[], bool]     # only execute when this is true
    
@dataclass
class ActionSequence:
    name: str
    priority: int
    steps: list[QueuedAction | WaitCondition]
    current_step: int = 0
    
@dataclass
class WaitCondition:
    name: str
    check: Callable[[], bool]        # wait until this returns True
    timeout_game_time: float         # give up after this many game seconds
    on_timeout: str                  # "skip" | "abort" | "retry"
```

### Sequence Examples
```python
# Scout base perimeter
ActionSequence("scout_base", Priority.HIGH, [
    QueuedAction("move_scout_N", move(scout_id, base.x, base.y - 20)),
    WaitCondition("scout_arrived_N", lambda: unit_near(scout_id, target), timeout=30),
    QueuedAction("move_scout_E", move(scout_id, base.x + 20, base.y)),
    WaitCondition("scout_arrived_E", lambda: unit_near(scout_id, target), timeout=30),
    QueuedAction("move_scout_S", move(scout_id, base.x, base.y + 20)),
    WaitCondition("scout_arrived_S", lambda: unit_near(scout_id, target), timeout=30),
    QueuedAction("move_scout_W", move(scout_id, base.x - 20, base.y)),
    WaitCondition("scout_arrived_W", lambda: unit_near(scout_id, target), timeout=30),
])

# Build a mill near berries, then surround with farms
ActionSequence("setup_food_eco", Priority.HIGH, [
    QueuedAction("build_mill", place_building("MILL", berry_pos)),
    WaitCondition("mill_started", lambda: building_tracker.was_building_placed("MILL", berry_pos), timeout=20),
    WaitCondition("mill_complete", lambda: building_tracker.has_complete("MILL"), timeout=60),
    QueuedAction("build_farm_1", place_building("FARM", farm_pos_1)),
    QueuedAction("build_farm_2", place_building("FARM", farm_pos_2)),
    QueuedAction("build_farm_3", place_building("FARM", farm_pos_3)),
    QueuedAction("build_farm_4", place_building("FARM", farm_pos_4)),
])
```

### Interface
```python
class EventQueue:
    def add_action(self, action: QueuedAction) -> None
    def add_sequence(self, sequence: ActionSequence) -> None
    def tick(self, world: WorldState) -> dict | None  # execute next action, return response
    def has_active(self, name_prefix: str) -> bool
    def cancel(self, name: str) -> None
    def preempt(self, action: QueuedAction) -> None  # jump the queue
    def get_active_sequences(self) -> list[ActionSequence]
    def clear_below_priority(self, priority: int) -> None
```

### Key Behaviors
- Executes one game command per tick (respects AoE2Control constraint)
- WaitConditions consume a tick but don't send a command (just check)
- Higher priority actions/sequences preempt lower ones
- Sequences can be cancelled mid-execution
- Timeout on waits prevents infinite stalls

---

## Feature 6: WorldState (Orchestrator)

### Purpose
Central model that owns all trackers, ingests raw game state each tick, and provides a unified view.

### Interface
```python
class WorldState:
    units: UnitTracker
    buildings: BuildingTracker
    commands: CommandTracker
    map: MapKnowledge
    queue: EventQueue
    spatial: SpatialEngine       # existing, integrated here
    
    # Core state
    game_time: float
    age: int
    resources: Resources         # food, wood, gold, stone
    population: int
    housing_headroom: int
    
    def update(self, raw_state: dict) -> None:
        """Ingest raw game state, update all trackers."""
        
    # Convenience queries that span multiple trackers
    def idle_vils(self) -> list[TrackedUnit]
    def vils_gathering(self, resource: str) -> list[TrackedUnit]
    def can_afford(self, food=0, wood=0, gold=0, stone=0) -> bool
    def tc_is_training(self) -> bool
    def tc_is_complete(self) -> bool
    def has_building(self, building_type: str, complete_only: bool = True) -> bool
    def exploration_around_base(self) -> float  # 0.0 to 1.0
```

### Tick Flow
```
1. Runner calls world.update(raw_state)
   ├── units.update(raw["_all_units"])
   ├── buildings.update(raw["_building_details"])
   ├── commands.update(world)          # check outcomes
   ├── map.update(raw["_resources_scan"], unit_positions)
   └── spatial.refresh(raw_state)      # existing spatial engine
   
2. Strategy reads world state, decides what to do
   
3. Strategy adds actions to world.queue
   
4. Runner calls world.queue.tick(world) → executes one command
```

---

## Integration Map

```
WorldState.update()
    │
    ├─► UnitTracker.update()      reads: _all_units
    │       │
    │       └─► infers tasks from positions + BuildingTracker + MapKnowledge
    │
    ├─► BuildingTracker.update()  reads: _building_details, _buildings (counts)
    │       │
    │       └─► detects new/completed buildings → CommandTracker.verify()
    │
    ├─► CommandTracker.update()   reads: UnitTracker, BuildingTracker
    │       │
    │       └─► checks expected outcomes → marks commands succeeded/failed
    │
    ├─► MapKnowledge.update()     reads: _resources_scan, UnitTracker positions
    │       │
    │       └─► marks explored tiles, discovers/depletes resources
    │
    └─► SpatialEngine.refresh()   reads: _tcs, _building_details, _resources_scan
            │
            └─► updates base layout, placement calculations
```

---

## Implementation Order

### Level 0 (No dependencies — build first)
1. **UnitTracker** — foundation, everything needs unit positions
2. **BuildingTracker** — foundation, command verification needs this

### Level 1 (Depends on Level 0)
3. **CommandTracker** — needs UnitTracker + BuildingTracker to verify outcomes
4. **MapKnowledge** — needs UnitTracker for exploration marking

### Level 2 (Depends on Level 1)
5. **EventQueue** — needs CommandTracker for wait conditions
6. **WorldState** — orchestrates everything, integrates SpatialEngine

### Level 3 (Depends on Level 2)
7. **Strategy Rewrite** — FastCastle using WorldState + EventQueue instead of raw state

---

## Files

```
bot/src/aoe2bot/strategy/
├── world.py          # WorldState orchestrator
├── units.py          # UnitTracker
├── buildings.py      # BuildingTracker  
├── commands.py       # CommandTracker
├── map_knowledge.py  # MapKnowledge
├── event_queue.py    # EventQueue + ActionSequence
├── spatial.py        # SpatialEngine (existing, updated)
├── fast_castle.py    # Strategy (rewritten to use WorldState)
├── runner.py         # Game loop (simplified — WorldState handles enrichment)
├── eco.py            # EcoManager (reads from WorldState.units)
├── state.py          # AdaptiveState (may merge into WorldState)
└── actions.py        # Priority enum (kept)
```

---

## Success Criteria

1. **No duplicate commands** — never builds two lumber camps because we didn't know one was in progress
2. **No spamming** — if a build command is in flight, don't re-issue it
3. **Scout reveals map** — scout queues waypoints and waits for arrival before moving to next
4. **Idle vils get assigned** — knows the difference between "walking to gather" and "actually idle"
5. **Building lifecycle tracked** — knows foundation placed, construction in progress, complete
6. **Resource depletion detected** — knows when forage runs out, sends vils to farms
7. **Strategy is clean** — FastCastle reads WorldState, adds to EventQueue, done. No IPC calls in strategy.
