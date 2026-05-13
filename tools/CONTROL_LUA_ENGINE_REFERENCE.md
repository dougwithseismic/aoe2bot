# CONTROL Lua Engine — AI Agent Reference

**Purpose:** Provide this file to coding agents that need an accurate description of CONTROL's Lua API and runtime behavior.

**Rule:** Treat the signatures below as strict Lua signatures. A C++ default argument is not optional in Lua unless a separate overload is explicitly listed.

**Scope:** Treat this file as the primary contract for Lua function names, signatures, lifecycle behavior, and sandbox restrictions. Do not assume standard AoE2 `.per` AI syntax or generic game-engine APIs unless they are documented here or on the official CONTROL docs.

**When incomplete:** If a needed behavior is missing here or appears outdated, confirm it before shipping code on the official documentation hub: [AoE2Control Documentation](https://aoe2control.github.io/).

---

## 1. Overview

- Windows only
- Intended primarily for single-player use; multiplayer is allowed when cheats are enabled
- Config root: `%appdata%\CONTROL\AoE2Control\`
- Modules root: `%appdata%\CONTROL\AoE2Control\modules\`
- Module entries: `{moduleName}.main.lua` or `{moduleName}.main.module`
- CONTROL supports multiple module instances, each assigned to a player slot

---

## 2. Module System

Folder layout:

```text
modules/
└── my_module/
    ├── my_module.main.lua
    └── utils/
        └── logger.lua
```

Rules:

- Keep the module entry file thin; move reusable logic into required submodules
- `require("utils.logger")` loads `utils/logger.lua` relative to the module root
- Dot notation becomes path separators
- `require` depth limit: 3
- `..` traversal is blocked
- Modules are cached by path
- `load`, `loadfile`, `dofile`, `module`, and `collectgarbage` are removed from the sandbox

---

## 3. Lifecycle

All callbacks are optional.

| Callback | When | Notes |
|----------|------|-------|
| `Load(playerId)` | Instance is loaded or re-enabled | Use for `Settings.Add*` and setup that only needs the assigned player id. `GetAssignedPlayerId()` is also available here. |
| `Init()` | Match becomes ready, world changes, or instance reloads | Per-instance setup. |
| `Update()` | Every configured update interval while a match is running | Main logic. |
| `Render()` | Every frame while a match is running | Overlay rendering. Not called while multithreading is enabled. |
| `End(hasWon)` | Once when the match or replay ends, including manual match exit | `hasWon` refers to the assigned player. Manual exit reports `false`. |
| `Unload()` | Instance unload, disable, replace, or engine eject | Cleanup that should run even without normal match end. |

Read-only game API calls are valid during `Init`, `Update`, or `Render`. Facts and other end-state reads are also available in `End()`. Game commands belong in `Update()`.

- In **Tournament Mode**, update execution above `20 ms` adds delay to the effective update interval

---

## 4. Commands

This section follows the same grouping as `BindGameAPI()` in `module_bindings.cpp`.

### Engine

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `Log` | `(message)` | `nil` | Write to CONTROL's log window. |
| `SetEngineUIVisibility` | `(visible)` | `nil` | Show or hide the CONTROL overlay. |
| `UnloadEngine` | `()` | `nil` | Detach CONTROL from the game process. |
| `GetAssignedPlayerId` | `()` | `number` | Assigned player id for this module instance. Available in `Load`. |
| `AssignAndLoadModule` | `(playerId, moduleName)` | `boolean` | Assign a discovered module entry to a player slot and load or reload it. |

- `AssignAndLoadModule()` accepts player ids `1` to `8`
- `moduleName` must match a discovered module entry name
- Calls made from inside a running module callback are queued and applied safely by the module manager

### Menu / UI

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `DispatchStartGame` | `()` | `boolean` | Start the currently configured session. |
| `DispatchRestartGame` | `()` | `boolean` | Restart the current single-player session when supported. |
| `DispatchResignGame` | `()` | `boolean` | Resign the current game. |
| `DispatchQuitGame` | `()` | `boolean` | Exit the current game flow when supported. |
| `DispatchLoadGame` | `(saveGameFileName)` | `boolean` | Load a file from the current load-game list by file name. |
| `GetAvailableSaveFiles` | `()` | `string[]` | File names currently exposed by the game's load-game list. |
| `GetCurrentGameOptions` | `()` | `GameOptions \| nil` | Current session setup object when available. |
| `IsGamePaused` | `()` | `boolean` | Whether the current game or replay is paused. |
| `IsMenuOpen` | `()` | `boolean` | Whether the game UI is currently in a menu state. Also works during replays. |

### Replays

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `SetGameSpeedMultiplier` | `(multiplier)` | `nil` | Change the current game or replay speed multiplier. |
| `SetGamePaused` | `(paused)` | `nil` | Pause or resume the active replay. |
| `SetReplaySpeed` | `(speed)` | `nil` | Set replay playback speed using `ReplaySpeed`. |
| `GetCurrentReplayFileName` | `()` | `string` | Current replay file name while a replay is active. |

### Commands

Command functions usually filter input objects to ones owned by the assigned player.

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `SetCameraPosition` | `(position)` | `nil` | Move the camera to a `Vector2` world position. |
| `SendChatMessage` | `(message)` | `nil` | Send chat text as the assigned player. |
| `TrainUnit` | `(unitId)` | `boolean` | Train one unit by automatically selecting a matching source type for the assigned player. |
| `TrainUnit` | `(unitId, amount)` | `boolean` | Train units by automatically selecting a matching source type for the assigned player. |
| `TrainUnit` | `(trainSources, unitId)` | `boolean` | Train one unit from the assigned player's most common matching source type from the provided source list. |
| `TrainUnit` | `(trainSources, unitId, amount)` | `boolean` | Train units from the assigned player's most common matching source type from the provided source list. |
| `UnitsTargetObject` | `(units, target)` | `boolean` | Order owned units to target an object. |
| `UnitsBuildStructure` | `(builders, structureId, position)` | `boolean` | Order owned builders to construct a building. |
| `UnitsMove` | `(units, position)` | `boolean` | Order owned units to move. |
| `EnableScouting` | `()` | `boolean` | Enable auto-scouting on an idle assigned scout-line unit. |
| `ResearchTechnology` | `(technology)` | `boolean` | Research a technology from the assigned player's most common matching source type automatically. |
| `DeleteUnit` | `(unit)` | `nil` | Delete an owned unit. |
| `DestroyBuilding` | `(building)` | `nil` | Destroy an owned building. |
| `SetGatherPoint` | `(buildings, targetPosition)` | `nil` | Set gather point on owned buildings. |
| `RingTownBell` | `(building, isCallingIn)` | `nil` | Ring or release the town bell on an owned building. |
| `SendBackToWork` | `(building)` | `nil` | Send workers from an owned building back to work. |
| `SendAllBackToWork` | `(building)` | `nil` | Send all workers from an owned building back to work. |
| `SetUnitStanceAutoScout` | `(units)` | `nil` | Set owned units to auto-scout. |
| `SetUnitStancePatrol` | `(units, targetPosition)` | `nil` | Set owned units to patrol. |
| `SetUnitStanceGuard` | `(units, targetObject)` | `nil` | Set owned units to guard. |
| `SetUnitStanceFollow` | `(units, targetObject)` | `nil` | Set owned units to follow. |
| `SetUnitStanceAttackMove` | `(units, targetPosition)` | `nil` | Set owned units to attack-move. |
| `SetUnitStanceGarrison` | `(units, targetObject)` | `nil` | Garrison owned units. |
| `SetUnitStanceUngarrison` | `(sourceObjects, unit)` | `nil` | Ungarrison an owned unit from owned source buildings. |
| `SetUnitStanceSeekShelter` | `(units)` | `nil` | Send owned units to shelter. |
| `SetUnitCombatStance` | `(units, stance)` | `nil` | Set combat stance on owned units. |

Rules:

- Only the **Commands** subsection is subject to replay blocking, outside-`Update()` warnings, and `Sequential Actions`
- **Tournament Mode** also blocks selected engine, menu, replay, render, and `GameOptions` APIs
- **Multithreading** also blocks selected menu, replay, render, and IPC wait APIs, and disables `Render()`
- Most unit and building commands filter inputs to objects owned by the assigned player
- `SetCameraPosition` and `SendChatMessage` are game commands, but they are not ownership-filtered
- `Log()`, `SetEngineUIVisibility()`, and `UnloadEngine()` are not in-match game commands, but **Tournament Mode** can still restrict selected engine APIs
- If `Sequential Actions` is enabled, only the first successful command per tick executes

---

## 5. Facts

| Function | Signature | Returns | Description |
|----------|-----------|---------|-------------|
| `GetFact` | `(fact)` | `number` | Read a fact for the assigned player with parameter `0`. |
| `GetFact` | `(fact, parameter)` | `number` | Read a fact for the assigned player. |
| `IsObjectTypeAvailable` | `(unitObjectType)` | `boolean` | Check whether the assigned player currently has access to a unit or building type. |
| `GetUnitTypeCount` | `(unitId)` | `number` | Count a unit type for the assigned player. |
| `GetAttribute` | `(attribute)` | `number` | Read a `PlayerAttribute` for the assigned player. |
| `CanAfford` | `(unitId, isBuilding)` | `boolean` | Check whether the assigned player can afford an item. |
| `GetTechCost` | `(technology)` | `{ resourceId = ResourceType, amount = number }[]` | Current technology cost entries for the assigned player. |
| `GetObjectCost` | `(unitObjectType)` | `{ resourceId = ResourceType, amount = number }[]` | Current object cost entries for the assigned player with multiplier `1.0`. |
| `GetObjectCost` | `(unitObjectType, costMultiplier)` | `{ resourceId = ResourceType, amount = number }[]` | Current object cost entries for the assigned player with the given multiplier applied. |
| `CanResearch` | `(technology)` | `boolean` | Check whether the assigned player can research a technology. |
| `IsTechnologyResearched` | `(technology)` | `boolean` | Check whether the assigned player has researched a technology. |
| `GetObjectsByType` | `(unitType)` | `Object[]` | Scan matching world objects by type. Not restricted to owned objects. Loot-bearing dead huntables and livestock are included. |
| `GetObjectsByTypes` | `(unitTypes)` | `Object[]` | Scan matching world objects by any listed type. Loot-bearing dead huntables and livestock are included. |
| `GetObjectsByClass` | `(unitClass)` | `Object[]` | Scan matching world objects by class. Not restricted to owned objects. Loot-bearing dead huntables and livestock are included. |
| `GetGameTime` | `()` | `number` | Match time in seconds. |
| `GetAllChatMessages` | `()` | `string[]` | Current chat buffer as plain message strings. |
| `GetNewChatMessages` | `()` | `string[]` | Chat messages that became visible since this module instance last called the function. |
| `GetLastChatMessage` | `()` | `string \| nil` | Newest chat message, or `nil` when the chat buffer is empty. |
| `GetAssignedPlayer` | `()` | `Player` | Player currently assigned to this module instance. |
| `GetPlayerById` | `(id)` | `Player` | Player by list index. Gaia is usually `0`. |
| `GetPlayerCount` | `()` | `number` | Size of the player list. |
| `GetMapTilesPtr` | `()` | `number, number` | Returns `(ptr, count)` for an engine-owned packed tile snapshot buffer. Intended for IPC / RPM readers. |
| `GetMapWidth` | `()` | `number` | Current map width in tiles. |
| `GetMapHeight` | `()` | `number` | Current map height in tiles. |
| `GetMapTile` | `(x, y)` | `MapTile` | Overload: tile at integer map coordinates, or `nil` if out of bounds. |
| `GetMapTile` | `(position)` | `MapTile` | Overload: floors a `Vector2` position to a tile lookup. |
| `GetAllMapTiles` | `()` | `MapTile[]` | Full map tile list. Tile methods still respect fog-aware visibility. |
| `CalculatePath` | `(startPos, targetPos)` | `Vector3[]` | Calculate a native path between two `Vector3` positions. |
| `CalculatePath` | `(startPos, targetPos, collisionRadius)` | `Vector3[]` | Calculate a native path between two `Vector3` positions with an explicit collision radius. |
| `GetObjectsInArea` | `(pos1, pos2)` | `Object[]` | Objects inside the rectangle defined by two `Vector2` positions. Loot-bearing dead huntables and livestock are included. |
| `GetObjectsPtr` | `()` | `number, number` | Returns `(ptr, count)` for an engine-owned packed object snapshot buffer. Intended for IPC / RPM readers. |
| `GetObjectTypeData` | `(objectTypeId, objectData)` | `number` | Static object-type data lookup for a `UnitObjectType`. |
| `GetObjectTypeAttribute` | `(objectTypeId, objectAttribute, damageType)` | `number` | Static object-type attribute lookup for a `UnitObjectType`. |
| `IsEnemyPlayer` | `(player)` | `boolean` | Whether `player` is an enemy of the assigned player. |
| `GetObjectById` | `(id)` | `Object` | Object by id. |
| `GetProjectileById` | `(id)` | `Object` | Projectile object by id. |
| `GetAllProjectiles` | `()` | `Object[]` | Visible projectile objects. |
| `GetProjectilesByType` | `(projectileType)` | `Object[]` | Projectile objects matching a `ProjectileType`. |
| `GetVictoryCondition` | `()` | `VictoryCondition` | Current victory condition. |
| `GetVictoryPlayer` | `()` | `Player` | Winning player after game end, else `nil`. |

Notes:

- Use `GetAssignedPlayer()`, not `GetLocalPlayer()`.
- `GetAssignedPlayerId()` is documented in the Engine subsection above because it is available before the match starts and can be used from `Load(playerId)`.
- `GetMapTile(position)` floors `position.x` and `position.y`.
- `CalculatePath()` uses the game's native pathfinding, accepts `Vector3` start and target positions, and returns an empty list when no path is available.
- `GetObjectsInArea(pos1, pos2)` uses the same object filter as the other scan APIs. Loot-bearing dead huntables and livestock are included, and fog-aware visibility still applies.
- `GetObjectsByType()`, `GetObjectsByTypes()`, `GetObjectsByClass()`, `GetObjectsInArea()`, and `GetObjectById()` can still return explored animals or resources outside active vision
- On those non-visible explored object references, only `IsVisible()`, `IsExplored()`, `GetId()`, `GetPosition()`, `GetClass()`, and `GetUnitObjectType()` are safe
- `GetTechCost()` and `GetObjectCost()` return arrays of resource-cost entries. Use `entry.resourceId` and `entry.amount`; numeric indexes `entry[1]` and `entry[2]` mirror the same values.
- `GetAllChatMessages()` and `GetLastChatMessage()` read from the game's current chat buffer.
- `GetNewChatMessages()` tracks unread chat state per module instance; the first call after load or reload returns the currently visible buffer.
- Projectile lookup functions return normal `Object` references whose `ObjectType` is `ObjectType.PROJECTILE` and follow the same visibility restrictions as other object queries.
- Object retrieval follows the assigned player's fog-of-war when **Modules See Everything** is disabled, except for the explored animal and resource exception above. This includes `GetObjectById()`.
- With **Modules See Everything** disabled, player-state methods on other `Player` objects return neutral values for resources, facts, tech state, and object availability.
- `GetAllMapTiles()` returns the full grid, but each `MapTile` only exposes data allowed by the current fog state.
- `GetMapTilesPtr()` and `GetObjectsPtr()` return `(ptr, count)`, where `count` is an element count, not a byte count.
- `GetObjectsPtr()` is dead-inclusive.
- `CanAfford(unitId, isBuilding)` accepts both parameters, but the binding does not distinguish the flag internally.

### Enum Lookup Discipline

- CONTROL exposes enums as global Lua tables such as `Fact.WOOD_AMOUNT`
- Never guess enum member names or numeric values; wrong ids can fail at runtime or silently target the wrong system
- Use authoritative sources in this order:
  - [Enums](https://aoe2control.github.io/enums/) for most in-match tables such as `Fact`, `Age`, `Technology`, `UnitObjectType`, `UnitClass`, `PlayerAttribute`, and `ResourceType`
  - [GameOptions](https://aoe2control.github.io/game-options/) for setup-only tables such as `OptionsAge`, `OptionsLocation`, `OptionsGameMode`, and the `GameOptions` API
  - [Facts](https://aoe2control.github.io/facts/) when confirming which readers use `Fact` or `PlayerAttribute`
- Lookup workflow:
  - Identify the exact enum table expected by the API or by the symbol prefix before the dot
  - Copy the documented member spelling exactly
  - When comparing ages or similar tiers, verify which table the value came from before comparing or mapping it, especially `Age` vs `OptionsAge`
  - If the live docs and this file disagree on enum members or numeric values, prefer the published site and refresh the local copy
- Optional local mirror: if the AoE2Control Lua extension is installed, `definitions/control-api.d.lua` can speed up lookups, but reconcile with the published docs when precision matters
- Anti-patterns:
  - Hard-coding magic numbers for facts, units, technologies, or ages
  - Using `OptionsAge` values to interpret `Fact.CURRENT_AGE`, or the reverse, without confirming they match in the current engine version
  - Copying large enum tables into project docs instead of linking to the authoritative pages

---

## 6. Render API

All parameters shown are required in Lua.

| Function | Signature |
|----------|-----------|
| `GetScreenSize` | `()` |
| `IsOnScreen` | `(position)` |
| `RenderText` | `(text, position, size, color, center, border)` |
| `RenderLine` | `(from, to, color, thickness)` |
| `RenderCircle` | `(position, radius, color, thickness, segments)` |
| `RenderCircleFilled` | `(position, radius, color, segments)` |
| `RenderRect` | `(from, to, color, rounding, roundingCornersFlags, thickness)` |
| `RenderRectFilled` | `(from, to, color, rounding, roundingCornersFlags)` |
| `IsWorldPosOnScreen` | `(worldPos)` |
| `WorldToScreen` | `(worldPos)` |
| `WorldToMinimap` | `(worldPos)` |
| `GetZoom` | `()` |
| `GetCameraPosition` | `()` |
| `RenderWorldLine` | `(from, to, color, thickness)` |
| `RenderWorldRect` | `(worldPos, width, height, color, thickness)` |
| `RenderWorldRectFilled` | `(worldPos, width, height, color)` |
| `RenderWorldCircle` | `(worldPos, radius, color, thickness, segments)` |
| `RenderWorldCircleFilled` | `(worldPos, radius, color, segments)` |
| `RenderWorldText` | `(text, worldPos, size, color, center, border)` |
| `RenderObjectBounds` | `(object, color, thickness)` |
| `RenderObjectBoundsFilled` | `(object, color)` |
| `RenderMinimapDot` | `(worldPos, radius, color)` |
| `RenderMinimapLine` | `(worldPosFrom, worldPosTo, thickness, color)` |
| `RenderMinimapRect` | `(worldPos, width, height, color, thickness)` |
| `RenderMinimapRectFilled` | `(worldPos, width, height, color)` |

---

## 7. Settings API

Use `Settings.Add*` only in `Load(playerId)`.

| Function | Signature |
|----------|-----------|
| `Settings.AddBool` | `(key, defaultValue)` |
| `Settings.AddInt` | `(key, defaultValue, minValue, maxValue)` |
| `Settings.AddFloat` | `(key, defaultValue, minValue, maxValue)` |
| `Settings.AddDropdown` | `(key, defaultValue, options)` |
| `Settings.AddKeybind` | `(key, defaultVkCode)` |
| `Settings.AddTooltip` | `(key, tooltip)` |
| `Settings.AddColor` | `(key, defaultColor)` |
| `Settings.GetBool` | `(key, defaultValue)` |
| `Settings.GetInt` | `(key, defaultValue)` |
| `Settings.GetFloat` | `(key, defaultValue)` |
| `Settings.GetString` | `(key, defaultValue)` |
| `Settings.GetKeybind` | `(key, defaultVkCode)` |
| `Settings.GetColor` | `(key, defaultColor)` |
| `IsKeyPressed` | `(vkCode)` |

Custom module settings may be per-player or profile-shared depending on whether **Sync Settings** is enabled in the UI.

---

## 8. IPC API

| Function | Signature | Returns |
|----------|-----------|---------|
| `IPC.StartServer` | `(pipeName)` | `boolean` |
| `IPC.StopServer` | `()` | `nil` |
| `IPC.Send` | `(message)` | `boolean` |
| `IPC.HasMessages` | `()` | `boolean` |
| `IPC.GetMessages` | `()` | `string[]` |
| `IPC.WaitForMessage` | `()` | `string \| nil` |
| `IPC.WaitForMessage` | `(timeoutMs)` | `string \| nil` |
| `ParseJSON` | `(str)` | `table` |
| `ToJSON` | `(obj)` | `string` |

Behavior:

- Named pipes are newline-delimited
- Multiple module instances can share one pipe
- Incoming messages can route by `instanceId`, `assignedPlayerId`, `moduleName`, or `settingsGroup`
- Routing fields can appear at the root or under a root `target` object
- `IPC.Send` accepts strings or Lua values; non-string values are serialized to JSON automatically
- `IPC.Send` wraps payloads in an envelope with source metadata
- `IPC.HasMessages()` reports whether this module instance has queued messages
- `IPC.GetMessages` returns strings; use `ParseJSON` when expecting JSON
- `IPC.WaitForMessage()` returns one message at a time and waits indefinitely until a message arrives or the endpoint stops
- `IPC.WaitForMessage(timeoutMs)` returns `nil` on timeout and treats negative values as an indefinite wait
- `IPC.Send` and `IPC.GetMessages` can be polled continuously without waiting for a pipe close event
- `IPC.WaitForMessage()` is blocked while **Multithreading** is enabled
- `GetMapTilesPtr()` and `GetObjectsPtr()` are meant for high-throughput IPC / ML readers
- Snapshot buffers are engine-owned, rebuilt on demand, and should be copied immediately
- Snapshot byte size is `count * sizeof(Tile)` or `count * sizeof(Object)`
- Explicit `IPC.StopServer()` in `Unload()` is optional in practice because CONTROL also stops the server automatically after module unload

Snapshot layouts:

```cpp
#pragma pack(push, 1)
namespace game::snapshot {
    struct Tile {
        uint16_t x;
        uint16_t y;
        uint8_t terrain;
        uint8_t elevation;
        uint8_t isVisible;
        uint8_t flags;
    };

    struct Object {
        uint32_t id;
        uint16_t unitObjectType;
        uint16_t x;
        uint16_t y;
        uint8_t playerId;
        uint8_t flags;
    };
}
#pragma pack(pop)
```

Flags:

- `Tile.flags` bit `0`: walkable
- `Tile.flags` bit `1`: navigatable
- `Object.flags` bit `0`: alive

---

## 9. Types

### Vector2

- Constructors: `Vector2()`, `Vector2(x, y)`, `Vector2(scalar)`
- Fields: `x`, `y`
- Methods: `LengthSqr`, `Length`, `Normalize`, `Normalized`
- Overloads: `Dot(other)` / `Dot(a, b)`, `Cross(other)` / `Cross(a, b)`
- Other methods: `IsNearlyZero`, `Lerp`, `Distance`
- Operators: `+`, `-`, `*`, `/`, unary `-`, `==`

### Vector3

- Constructors: `Vector3()`, `Vector3(x, y, z)`, `Vector3(scalar)`
- Fields: `x`, `y`, `z`
- Methods: `LengthSqr`, `Length`, `Normalize`, `Normalized`
- Overloads: `Dot(other)` / `Dot(a, b)`, `Cross(other)` / `Cross(a, b)`
- Other methods: `IsNearlyZero`, `Lerp`, `Distance`
- Operators: `+`, `-`, `*`, `/`, unary `-`, `==`

### Vector4

- Constructors: `Vector4()`, `Vector4(x, y, z, w)`, `Vector4(scalar)`
- Fields: `x`, `y`, `z`, `w`
- Methods: `LengthSqr`, `Length`, `Normalize`, `Normalized`
- Overloads: `Dot(other)` / `Dot(a, b)`
- Other methods: `IsNearlyZero`, `Lerp`, `Distance`
- Operators: `+`, `-`, `*`, `/`, unary `-`, `==`

### Color

- Constructors: `Color()`, `Color(r, g, b)`, `Color(r, g, b, a)`, float RGB/RGBA variants, `Color(hexString)`
- Static methods: `Color.Parse`, `Color.HSV`

### Object

Methods:

- `GetId()`
- `GetObjectType()`
- `GetOwningPlayer()`
- `GetGarrisonObject()`
- `GetTargetPosition()`
- `GetTargetObject()`
- `GetActionTargetPosition()`
- `GetDirection()`
- `IsVisible()`
- `IsExplored()`
- `IsAlive()`
- `GetUnitObjectType()`
- `GetClass()`
- `GetAttribute(attribute, damageType)`
- `GetObjectData(objectData)`
- `IsIdle()`
- `IsMoving()`
- `IsScouting()`
- `GetHitpoints()`
- `GetMaxHitpoints()`
- `GetPosition()`
- `GetCurrentMapTile()`
- `GetPath()`
- `GetName()`
- `GetInternalName()`
- `GetMasterName()`
- `CalculatePath(targetPos)`

Behavior:

- `IsVisible()` uses map-tile visibility
- Cached objects can throw a Lua error on most method calls after they become invisible
- Explored animals and resources can still be returned even when they are not currently visible
- On those non-visible explored object references, only `IsVisible()`, `IsExplored()`, `GetId()`, `GetPosition()`, `GetClass()`, and `GetUnitObjectType()` are safe
- `GetName()`, `GetInternalName()`, and `GetMasterName()` return empty strings when name data is unavailable
- Re-fetch object references in the current frame when fog-aware mode is active

### MapTile

Methods:

- `GetPosition()`
- `GetTerrain()`
- `GetElevation()`
- `GetTileVisibility()`
- `IsBuildable()`
- `IsWalkable()`
- `IsNavigatable()`
- `GetObjectCount()`
- `GetObjects()`

Behavior:

- `GetTerrain()` returns `Terrain.UNKNOWN` for unexplored tiles
- `GetElevation()` returns `0` for unexplored tiles
- `IsBuildable()` requires a flat, walkable tile
- `IsWalkable()` returns `false` for unexplored tiles and uses the collision grid for walkability
- `GetObjectCount()` and `GetObjects()` only expose currently visible tiles

Enum notes:

- `ReplaySpeed` values: `SLOW`, `NORMAL`, `FAST`, `FASTEST`
- `ProjectileType` is exposed to Lua for `GetProjectilesByType()` filtering
- `ResourceType` exposes additional engine-defined ids; common values include `FOOD`, `WOOD`, `STONE`, `GOLD`, `POPULATION`
- `Terrain.UNKNOWN = -1`
- `TileVisibility.UNEXPLORED = 0`
- `TileVisibility.VISIBLE = 15`
- `TileVisibility.EXPLORED = 128`
- Use `ObjectAttribute` instead of `UnitAttribute`
- `ObjectData` entries use names without the `OBJECT_DATA_` prefix

### GameOptions

Obtained from `GetCurrentGameOptions()`.

Global setup methods:

- `GetAIDifficulty()` / `SetAIDifficulty(difficulty)`
- `GetCivilizationSet()` / `SetCivilizationSet(civilizationSet)`
- `GetGameMode()` / `SetGameMode(gameMode)`
- `GetMapSize()` / `SetMapSize(mapSize)`
- `GetStartingAge()` / `SetStartingAge(age)`
- `GetEndingAge()` / `SetEndingAge(age)`
- `GetGameSpeed()` / `SetGameSpeed(gameSpeed)`
- `GetRevealMap()` / `SetRevealMap(revealMap)`
- `GetVictory()` / `SetVictory(victory)`
- `GetVictoryLimit()` / `SetVictoryLimit(victoryLimit)`
- `GetResources()` / `SetResources(resources)`
- `GetPopulation()` / `SetPopulation(population)`
- `GetTeamsNotTogether()` / `SetTeamsNotTogether(teamsNotTogether)`
- `GetRecordGame()` / `SetRecordGame(recordGame)`
- `GetTeamPositions()` / `SetTeamPositions(teamPositions)`
- `GetFullTechTree()` / `SetFullTechTree(fullTechTree)`
- `GetLockTeams()` / `SetLockTeams(lockTeams)`
- `GetLockSpeed()` / `SetLockSpeed(lockSpeed)`
- `GetTurboMode()` / `SetTurboMode(turboMode)`
- `GetAntiquityMode()` / `SetAntiquityMode(antiquityMode)`
- `GetLocation()` / `SetLocation(location)`
- `SetRandomMapPoolLocations(locations)`
- `GetPlayersCount()` / `SetPlayersCount(playersCount)`
- `GetTreatyLength()` / `SetTreatyLength(treatyLength)`
- `GetHandicap()` / `SetHandicap(handicap)`

Player-slot methods:

- `GetPlayerTeam(playerIndex)` / `SetPlayerTeam(playerIndex, team)`
- `GetPlayerHandicapPercentage(playerIndex)` / `SetPlayerHandicapPercentage(playerIndex, handicapPercentage)`
- `GetPlayerColor(playerIndex)` / `SetPlayerColor(playerIndex, color)`
- `GetPlayerCivilization(playerIndex)` / `SetPlayerCivilization(playerIndex, civilization)`
- `SetAssignedPlayerCivilization(civilization)`

Behavior:

- `GetCurrentGameOptions()` can return `nil`
- Setter methods return `false` while already in game
- Player-slot methods accept indexes `0` to `7`
- `SetAssignedPlayerCivilization()` uses the current module instance's assigned player slot and requires a valid player id from `1` to `8`
- `SetRandomMapPoolLocations()` accepts a Lua array of `OptionsLocation` values; one entry behaves like `SetLocation()`, while multiple entries switch the location to `OptionsLocation.CUSTOM_MAP_POOL`
- Most `GameOptions` methods are blocked while **Tournament Mode** is enabled; `SetAssignedPlayerCivilization()` remains available in the current Lua API
- The associated enum tables are `OptionsAIDifficulty`, `OptionsCivilizationSet`, `OptionsGameMode`, `OptionsMapSize`, `OptionsAge`, `OptionsRevealMap`, `OptionsVictory`, `OptionsResources`, `OptionsLocation`, and `OptionsCivilization`

### Player

Methods:

- `GetId()`
- `GetPlayerType()`
- `GetPlayerObjects()`
- `GetCameraPosition()`
- `GetMouseHoveredObject()`
- `GetSelectedObject()`
- `GetSelectedObjectCount()`
- `GetPlayerName()`
- `GetCivilizationId()`
- `GetCivilizationName()`
- `HasWon()`
- `IsAlliedWith(player)`
- `IsEnemyTo(player)`
- `GetColor()`
- `GetAttribute(attribute)`
- `GetUnitTypeCount(id)`
- `GetFact(fact, parameter)`
- `IsObjectTypeAvailable(unitObjectType)`
- `CanAfford(id, isBuilding)`
- `GetResearchState(technology)`
- `GetTechCost(technology)`
- `GetObjectCost(unitObjectType)`
- `GetObjectCost(unitObjectType, costMultiplier)`
- `CanAffordResearch(technology)`
- `CanResearch(technology)`
- `IsTechnologyResearched(technology)`
- `GetObjectsByTypes(unitTypes)`
- `GetObjectsByMostCommonType(unitTypes)`
- `GetObjectsByClass(unitClass)`
- `GetObjectsByClassDeadInclusive(unitClass)`
- `GetTownCenters()`

Behavior:

- With **Modules See Everything** off, resource, fact, tech, and object-availability methods only expose the assigned player's data
- Object lists from other players still depend on object visibility

### ResourceTracker

Constructor: `ResourceTracker()`

Methods:

- `Update()`
- `GetConvertibleLivestock(position, radius)`
- `GetOwnedLivestock()`
- `GetDeadLivestock(position, radius)`
- `GetForage()`
- `GetFarms()`
- `GetTrees()`
- `GetGold()`
- `GetStone()`

Behavior:

### VillagerOccupation

Constructor: `VillagerOccupation(resourceTracker)`

Methods:

- `Update()`
- `GetVillagerCount()`
- `GetVillagerCount(profession)`
- `GetIdleVillagerCount()`
- `GetAllVillagers()`
- `GetIdleVillagers()`
- `RequestVillagers(amount, position, urgency)`
- `SetPriorities(wood, food, gold, stone)`
- `GetPriorityPercentage(profession)`
- `ResetPriorities()`
- `SetPriorityPercentage(profession, percentage)`
- `SetLivestockVillagerLimit(limit)`
- `SetForageVillagerLimit(limit)`
- `SetFarmMaxTownCenterDistance(distance)`
- `SetFarmMaxMillDistance(distance)`
- `SetProfessionBuildingRange(profession, range)`
- `AssignVillagers(objectIds)`
- `AssignVillagers(objects)`
- `AssignVillager(villager)`

Notes:

- Food assignment prefers livestock, then forage, then farms, with fallback when needed
- `SetLivestockVillagerLimit()` defaults to `6`, and `SetForageVillagerLimit()` defaults to `8`
- `SetFarmMaxTownCenterDistance()` and `SetFarmMaxMillDistance()` default to `1.0`
- `GetIdleVillagers()` returns idle villagers currently available for reassignment
- `SetProfessionBuildingRange()` defaults to `8.0` tiles per profession in the current implementation

### ConstructionPlacement

Constructor: `ConstructionPlacement(villagerOccupation)`

Methods:

- `Update()`
- `SetTownCenterPadding(padding)`
- `BuildStructure(structureType, builderUnitId, targetPos, direction, padding)`
- `BuildStructure(structureType, builderUnitId, targetPos, direction, padding, bypassTownCenterPadding)`
- `BuildStructure(structureType, builderUnitId, targetPos, directionPos, padding)`
- `BuildStructure(structureType, builderUnitId, targetPos, directionPos, padding, bypassTownCenterPadding)`
- `BuildStructure(structureType, targetPos, direction, padding)`
- `BuildStructure(structureType, targetPos, direction, padding, bypassTownCenterPadding)`
- `BuildStructure(structureType, targetPos, directionPos, padding)`
- `BuildStructure(structureType, targetPos, directionPos, padding, bypassTownCenterPadding)`
- `BuildStructureAtTown(structureType, targetPos, padding)`
- `BuildStructureAtTown(structureType, targetPos, padding, bypassTownCenterPadding)`
- `BuildStructureAtTown(structureType, padding)`
- `BuildStructureAtTown(structureType, padding, bypassTownCenterPadding)`
- `FindBestPosition(structureType, targetPos, direction, padding, bypassTownCenterPadding)`
- `GetValidFarmPlacementTile()`
- `QueueBuildingRequest(structureType, targetPosition, priority, padding, bypassTownCenterPadding, builderUnitId, requireScouting)`
- `QueueBuildingRequestAtTown(structureType, priority, padding, bypassTownCenterPadding, builderUnitId, requireScouting)`
- `ProcessBuildingRequests()`
- `IsStructureTypeQueued(structureType)`
- `IsUnitAssignedToBuilding(unitId)`

Notes:

- `BuildStructure(...)`, `FindBestPosition(...)`, and queue helpers take `UnitObjectType` and derive placement size internally
- Convenience `BuildStructure(...)` overloads can auto-select a builder villager and issue the build command directly
- `BuildStructureAtTown(...)` adds town-center-oriented placement helpers
- `SetTownCenterPadding()` defaults to `3` and clamps to `0` or higher
- `GetValidFarmPlacementTile()` uses the current villager-occupation farm distance rules when available
- Build helpers also expose overloads without the final `bypassTownCenterPadding` argument; those use the default `false` behavior
- Map tile state is cached internally to improve repeated placement work

Not exposed to Lua:

- `ConstructionPlacement.RenderDebug`

---

## 10. Important UI Behavior

- Global module toggle defaults to enabled
- Module configuration is grouped by `Player 1` to `Player 8`
- Each player group exposes one module slot for that player
- The built-in submenus are **MODULES**, **UI**, **MISC**, **KEYBINDS**, and **DEBUG**
- `Suppress Native AI` defaults to `true`; when enabled, assigned bot players have their native decision AI disabled while a Lua module is attached
- `Multithreading` detaches module execution from the game's render thread, disables `Render()`, and blocks selected menu, replay, render, and IPC wait APIs
- `Modules See Everything` defaults to `false` and affects map-tile reads, object visibility, and restricted cross-player data access
- Player perspective options live under the **MISC** submenu: `Default`, `Player 1` to `Player 8`, `Gaia`
- `Game Speed Multiplier` lives under the **MISC** submenu and applies a preset game-speed override
- CONTROL resets `Player Perspective` to `Default` on startup
- Menu scale and transparency live under the **UI** submenu
- `Tournament Mode` blocks game commands outside `Update()` and also restricts selected engine, menu, replay, render, and `GameOptions` APIs
- By default, assigning a module to a bot player's slot suppresses that player's native decision AI while the module remains assigned
- The Debug menu's **Module Telemetry** view shows sampled `Update()` and `Render()` timing for active modules, plus a sampled baseline frame cost
- In multithreading mode, the baseline frame view is hidden
- `Spectator Mode` keeps controls enabled while spectating
- Runtime Lua errors are displayed and logged through the UI

---

## 11. Minimal Example

```lua
local announced = false

function Load(playerId)
    Settings.AddBool("Highlight Villagers", true)
    Settings.AddColor("Villager Color", Color(0, 255, 0, 90))
    Log("Loading for player " .. tostring(playerId))
end

function Init()
    announced = false
    Log("Match ready for player " .. tostring(GetAssignedPlayerId()))
end

function Update()
    if not announced then
        SendChatMessage("Hello from player " .. tostring(GetAssignedPlayerId()))
        announced = true
    end
end

function Render()
    if not Settings.GetBool("Highlight Villagers", true) then
        return
    end

    local color = Settings.GetColor("Villager Color", Color(0, 255, 0, 90))
    local player = GetAssignedPlayer()
    if not player then
        return
    end

    for _, villager in ipairs(player:GetObjectsByClass(UnitClass.VILLAGER)) do
        RenderObjectBoundsFilled(villager, color)
    end
end
```
