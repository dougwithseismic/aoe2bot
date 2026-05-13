# AoE2Bot Gameplay Guide — What Works, What Doesn't, and How to Script It

This is the practical guide for scripting AoE2 gameplay through the aoe2bot bridge. Everything here was validated in live games.

## Architecture Quick Reference

```
Claude CLI  -->  TCP Bridge (localhost:9999)  -->  Named Pipe  -->  Lua Module (in AoE2:DE)
```

1. Start game + AoE2Control (headless or GUI)
2. Assign `aoe2bot` module to player slot
3. Start bridge: `aoe2bot bridge`
4. Send commands: `aoe2bot <command>` (all output is JSON)

## Startup Checklist

```powershell
# 1. Install module
python bot/scripts/install_module.py

# 2. Launch AoE2Control (game must be running first)
AoE2Control.exe --headless --override-module "path\to\game\aoe2bot"

# 3. Start a game (skirmish, scenario, etc.)
# 4. Start bridge
aoe2bot bridge

# 5. Test
aoe2bot ping
```

## Hot-Reloading the Lua Module

After editing the Lua file:
1. Run `python bot/scripts/install_module.py`
2. In AoE2Control UI, re-assign the module to the player slot
3. The pipe reconnects automatically — no need to restart AoE2Control

**IMPORTANT**: The bridge's pipe connection will drop on reload. The bridge auto-reconnects on the next request.

---

## Building — THE KEY LESSON

### What works: `smart_build` (ConstructionPlacement)

`smart_build` uses CONTROL's `ConstructionPlacement` helper which handles finding a valid position AND selecting an idle villager AND issuing the build command.

```bash
# Auto-place near TC (no coordinates needed)
aoe2bot raw '{"action":"smart_build","building_name":"HOUSE_DARK_AGE","padding":1}'
aoe2bot raw '{"action":"smart_build","building_name":"FARM","padding":1}'
aoe2bot raw '{"action":"smart_build","building_name":"LUMBER_CAMP_DARK_AGE","padding":1}'
aoe2bot raw '{"action":"smart_build","building_name":"BLACKSMITH_FEUDAL_AGE","padding":1}'
aoe2bot raw '{"action":"smart_build","building_name":"MARKET_FEUDAL_AGE","padding":1}'
```

### What does NOT work: raw `build` (UnitsBuildStructure)

The raw `build` command (`UnitsBuildStructure`) returns `success: true` but usually does NOT actually place the building. It worked once for a house early in testing but failed consistently for TCs, farms, lumber camps, etc. **Do not rely on it.**

```bash
# DON'T USE THIS — unreliable
aoe2bot raw '{"action":"build","building_type":70,"x":120,"y":55}'
```

### Building names use age-specific enum names

Buildings in AoE2 have different enum names per age. You MUST use the correct one:

| Building | Dark Age | Feudal Age | Castle Age |
|----------|----------|------------|------------|
| House | HOUSE_DARK_AGE | HOUSE_FEUDAL_AGE | HOUSE_CASTLE_AGE |
| TC | TOWN_CENTER_DARK_AGE (109) | TOWN_CENTER_FEUDAL_AGE (71) | TOWN_CENTER_CASTLE_AGE (141) |
| Lumber Camp | LUMBER_CAMP_DARK_AGE | LUMBER_CAMP_FEUDAL_AGE | LUMBER_CAMP_CASTLE_AGE |
| Mining Camp | MINING_CAMP_DARK_AGE | MINING_CAMP_FEUDAL_AGE | MINING_CAMP_CASTLE_AGE |
| Mill | MILL (68) | — | — |
| Farm | FARM (50) | — | — |
| Blacksmith | — | BLACKSMITH_FEUDAL_AGE | BLACKSMITH_CASTLE_AGE |
| Market | — | MARKET_FEUDAL_AGE | MARKET_CASTLE_AGE |
| Barracks | BARRACKS (12) | — | — |
| Archery Range | ARCHERY_RANGE (87) | — | — |
| Stable | STABLE (101) | — | — |
| Castle | — | — | CASTLE (82) |

To discover the correct name:
```bash
aoe2bot raw '{"action":"enum_lookup","table_name":"UnitObjectType","search":"HOUSE"}'
```

### Coordinate-based smart_build does NOT work yet

`BuildStructure(typeId, targetPos, direction, padding)` fails with sol2 type errors. Only the auto-placement `BuildStructureAtTown(typeId, padding)` works. This means buildings always place near the TC.

**Workaround for lumber camps near trees**: Use auto-place — ConstructionPlacement sometimes places near resources. Not ideal. This needs fixing.

### Building requires idle villagers

`ConstructionPlacement` auto-selects an idle vil. If no vils are idle, it returns `success: false`. Always check that you have idle vils before building, or pull vils off tasks first.

---

## Training Units

```bash
aoe2bot train villager -n 3     # Train 3 villagers
aoe2bot train archer -n 5       # Train 5 archers
aoe2bot train knight            # Train 1 knight
```

Or raw:
```bash
aoe2bot raw '{"action":"train","unit_type":83,"amount":3}'   # Villager = 83
```

### Training fails when:
- Pop capped (housing_headroom = 0) — build houses first
- Not enough resources
- No valid production building

Always check `housing_headroom` before training. If 0, build houses.

---

## Gathering Resources — Targeting Objects

### Moving vils to a location does NOT make them gather

`move` sends vils to coordinates but they just stand there. To gather, you must **target them on a specific resource object** using the `attack` action with the object's ID.

```bash
# Find resources first
aoe2bot raw '{"action":"scan_resources"}'

# Target vils on specific objects
aoe2bot raw '{"action":"attack","unit_ids":[9813,9815],"target_id":9865}'  # Gold pile ID
aoe2bot raw '{"action":"attack","unit_ids":[9817],"target_id":2439}'       # Tree ID
aoe2bot raw '{"action":"attack","unit_ids":[9819],"target_id":9920}'       # Stone ID
```

### Sheep/livestock gathering
```bash
# Target vils on sheep/cow objects
aoe2bot raw '{"action":"attack","unit_ids":[9813,9815,9817,9819],"target_id":9930}'
```

### Tree chopping — edge trees only!

Trees in dense forests are unreachable. Vils can only chop trees on the EDGE of a forest — trees adjacent to walkable tiles.

**How to find choppable trees:**
1. Scan all trees: `aoe2bot raw '{"action":"scan_world","unit_class":915,"limit":80}'`
2. Check which tiles at y+1 or y-1 are walkable: `aoe2bot raw '{"action":"get_map_tiles","x1":119,"y1":38,"x2":125,"y2":40}'`
3. Target vils on trees whose adjacent tiles are walkable (terrain != -1, walkable = true)

**Trees get chopped and disappear** — their IDs become invalid. If `attack` returns `"error": "invalid units or target"`, rescan for live trees.

### Resource scanning

```bash
# ResourceTracker scan — finds trees, gold, stone, forage near explored areas
aoe2bot raw '{"action":"scan_resources"}'

# World scan by unit class — finds any world object
aoe2bot raw '{"action":"scan_world","unit_class":915,"limit":50}'   # Trees (class 915)
aoe2bot raw '{"action":"scan_world","unit_class":932,"limit":20}'   # Gold (class 932)
```

### Important unit classes for scanning
| Resource | UnitClass |
|----------|-----------|
| Trees | 915 |
| Gold Mine | 932 |
| Stone Mine | — (use scan_resources) |
| Forage | — (use scan_resources) |
| Livestock | 958 |

---

## Research / Age Advancement

```bash
aoe2bot research loom
aoe2bot research feudal          # 500 food
aoe2bot research castle-age      # 800 food + 200 gold (needs blacksmith + market)
aoe2bot research imperial        # 1000 food + 800 gold (needs castle or university)
```

### Castle Age prerequisites
- Blacksmith (BLACKSMITH_FEUDAL_AGE)
- Market (MARKET_FEUDAL_AGE) or Monastery or University — any 2 Feudal buildings

### Imperial Age prerequisites
- Castle (CASTLE) or University (UNIVERSITY)

### Check if research is affordable
```bash
aoe2bot can-afford 102          # Castle Age tech ID
```

---

## State Queries

```bash
aoe2bot status                   # Full snapshot: age, resources, pop, idle vils
aoe2bot resources                # Just resources
aoe2bot units                    # All owned units with positions
aoe2bot idle-vils                # Idle units (includes buildings — filter by class 904)
aoe2bot buildings                # All buildings
aoe2bot town-centers             # TC positions
aoe2bot players                  # All players and diplomacy
aoe2bot map-info                 # Map dimensions
aoe2bot diag                     # Diagnostics: enum tables, helper status
```

### Idle villager filtering

`idle-vils` returns ALL idle objects including buildings, yurts, horses. Filter for `class: 904` to get actual villagers:

```python
idle = [u for u in response["units"] if u.get("class") == 904]
```

### Key state fields
```json
{
  "age": 0,           // 0=Dark, 1=Feudal, 2=Castle, 3=Imperial
  "resources": { "food": 200, "wood": 150, "gold": 100, "stone": 200 },
  "population": {
    "current": 22,
    "headroom": 178,
    "housing_headroom": 8   // BUILD HOUSES WHEN THIS IS LOW (<5)
  },
  "villagerCount": 22,
  "idleVillagers": 3,
  "helpersReady": true      // ConstructionPlacement/ResourceTracker initialized
}
```

---

## Map Scanning

```bash
# Scan a region for terrain, walkability, buildability
aoe2bot raw '{"action":"get_map_tiles","x1":119,"y1":38,"x2":125,"y2":40}'
```

### Terrain values
| Value | Meaning |
|-------|---------|
| -1 | Unexplored (fog of war) |
| 11 | Grass/dirt |
| 21 | Forest (trees) |
| 100 | Cleared/path |

### Tile properties
- `walkable: true` — units can walk here
- `buildable: true` — buildings can be placed here
- `terrain: -1` — unexplored, need to scout

---

## Unit Commands

```bash
# Move units
aoe2bot raw '{"action":"move","unit_ids":[42,43],"x":150,"y":200}'

# Attack target object
aoe2bot raw '{"action":"attack","unit_ids":[42,43],"target_id":99}'

# Attack-move (move + engage enemies along the way)
aoe2bot raw '{"action":"attack_move","unit_ids":[42,43],"x":200,"y":200}'

# Patrol
aoe2bot raw '{"action":"patrol","unit_ids":[42,43],"x":200,"y":200}'

# Garrison
aoe2bot raw '{"action":"garrison","unit_ids":[42,43],"target_id":11234}'

# Set combat stance
aoe2bot raw '{"action":"set_stance","unit_ids":[42,43],"stance":0}'
# 0=aggressive, 1=defensive, 2=no-attack, 3=stand-ground

# Scout (auto-scout with scout unit)
aoe2bot scout
```

---

## Game Control

```bash
aoe2bot pause
aoe2bot unpause
aoe2bot speed 0.5               # Slow down
aoe2bot speed 2.0               # Speed up
aoe2bot camera 120 55           # Move camera
aoe2bot chat "gg"               # Send chat
aoe2bot resign
```

---

## Enum Lookups

When you don't know the exact enum name:

```bash
aoe2bot raw '{"action":"enum_lookup","table_name":"UnitObjectType","search":"HOUSE"}'
aoe2bot raw '{"action":"enum_lookup","table_name":"Technology","search":"FEUDAL"}'
aoe2bot raw '{"action":"enum_lookup","table_name":"UnitClass","search":"TREE"}'
aoe2bot raw '{"action":"enum_lookup","table_name":"PlacementDirection"}'
```

---

## Common Gotchas

1. **Buildings don't place** — Use `smart_build`, not raw `build`. Raw `UnitsBuildStructure` is unreliable.

2. **Pop capped** — Check `housing_headroom` before training. Build 2 houses when it drops below 5.

3. **No idle vils** — `smart_build` needs idle vils. Pull vils off stone/gold (check if you have excess) or wait for new vils from TC.

4. **Trees unreachable** — Don't target trees deep in a forest. Find edge trees by cross-referencing tree positions with walkable tiles at adjacent coordinates.

5. **Resource objects disappear** — Sheep die, trees get chopped, gold runs out. Their IDs become invalid. Always rescan before targeting.

6. **Building enum names are age-specific** — `HOUSE` doesn't work; use `HOUSE_DARK_AGE` or `HOUSE_FEUDAL_AGE`.

7. **VillagerOccupation auto-manages** — If enabled in Update(), it will reassign all vils every tick. Only enable it if you want full auto-eco.

8. **Module reload drops pipe** — Re-assigning the module in CONTROL restarts the pipe server. Bridge auto-reconnects.

9. **Lumber camps auto-place near TC** — `BuildStructureAtTown` places near TC, not near trees. Build lumber camps and let vils walk, or find a way to fix coordinate-based placement.

10. **scan_resources vs scan_world** — `scan_resources` uses ResourceTracker (trees/gold/stone/forage). `scan_world` uses `GetObjectsByClass` for any world object by class ID.

---

## Scripting a Build Order — Recommended Flow

```
1. Check status (age, resources, pop, idle vils)
2. If housing_headroom < 5: smart_build houses
3. If idle vils > 0: assign them (scan_resources, target on objects)
4. If TC queue empty: train villager
5. If age conditions met: research next age
6. If age prereq buildings needed: smart_build them
7. Repeat every few seconds
```

### Resource priorities by age
- **Dark Age**: 6 on food (sheep/berries), rest on wood. Research loom.
- **Pre-Feudal**: 60% food, 40% wood. Click Feudal at 500 food.
- **Feudal**: Build blacksmith + market. Start adding gold (3-4 vils). Click Castle at 800F/200G.
- **Pre-Castle**: Heavy food + gold. Some wood for buildings/farms.
- **Castle**: 2nd TC. Boom vils. Add military production.
- **Pre-Imperial**: 1000 food + 800 gold. Heavy farms + gold miners.

### Key thresholds
| Resource | Trigger Action |
|----------|---------------|
| housing_headroom < 5 | Build 2 houses |
| food > 500 (Dark) | Click Feudal |
| food > 800 + gold > 200 (Feudal) | Click Castle (if prereqs built) |
| food > 1000 + gold > 800 (Castle) | Click Imperial |
| wood < 100 | Pull vils from stone/gold to wood |
| idle vils > 0 | Assign immediately |
