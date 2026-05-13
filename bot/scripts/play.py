"""
AoE2Bot — Castle-building strategy.
One command per tick due to Sequential Actions.
"""

import time
import json
import sys
from aoe2bot.client import AoE2Client

VILLAGER_MALE = 83
HOUSE = 70
MILL = 68
LUMBER_CAMP = 562
MINING_CAMP = 584
FARM = 50
BLACKSMITH = 103
MARKET = 84
TOWN_CENTER = 109
CASTLE = 82

LOOM = 22
FEUDAL_AGE = 101
CASTLE_AGE = 102
DOUBLE_BIT_AXE = 202
HORSE_COLLAR = 14

TICK_DELAY = 0.9


def main():
    c = AoE2Client()
    c.connect(5000)
    print("Connected!")

    tc_x, tc_y = None, None
    loom_done = False
    feudal_sent = False
    castle_age_sent = False
    blacksmith_sent = False
    market_sent = False
    castle_sent = False
    house_offset = 0

    try:
        while True:
            # Read state
            state = c.request({"action": "get_state"})
            time.sleep(0.3)

            res = state.get("resources", {})
            pop = state.get("population", {})
            age = state.get("age", 0)
            food = res.get("food", 0)
            wood = res.get("wood", 0)
            gold = res.get("gold", 0)
            stone = res.get("stone", 0)
            current_pop = pop.get("current", 0)
            hh = pop.get("housing_headroom", 0)
            idle = state.get("idleVillagers", 0)
            t = state.get("time", 0)
            age_names = {0: "Dark", 1: "Feudal", 2: "Castle", 3: "Imperial"}

            mins = int(t) // 60
            secs = int(t) % 60
            print(f"[{mins}:{secs:02d}] {age_names.get(age,'?')} | Pop:{current_pop} HH:{hh} "
                  f"| F:{food:.0f} W:{wood:.0f} G:{gold:.0f} S:{stone:.0f} | Idle:{idle}")

            # Find TC if we don't have coords yet
            if tc_x is None:
                r = c.request({"action": "get_town_centers"})
                time.sleep(0.3)
                tcs = r.get("tcs", [])
                if tcs:
                    tc_x = tcs[0]["x"]
                    tc_y = tcs[0]["y"]
                    print(f"  TC at ({tc_x}, {tc_y})")
                else:
                    print("  No TC found, building one...")
                    if wood >= 275:
                        units = c.request({"action": "get_units"})
                        time.sleep(0.3)
                        vils = [u["id"] for u in units.get("units", []) if u.get("class") == 904 and u.get("idle")]
                        if vils:
                            c.request({"action": "build", "building_type": TOWN_CENTER,
                                       "x": 135.0, "y": 87.0, "builder_ids": vils})
                    time.sleep(TICK_DELAY)
                    continue

            # === PRIORITY: One action per tick ===
            acted = False

            # 1. Houses when housing headroom is low
            if not acted and hh <= 2 and wood >= 25:
                house_offset += 1
                dx = (house_offset % 4) * 3 - 6
                dy = -5 - (house_offset // 4) * 3
                r = c.request({"action": "build", "building_type": HOUSE,
                               "x": tc_x + dx, "y": tc_y + dy})
                if r.get("success"):
                    print(f"  Building house at ({tc_x+dx:.0f}, {tc_y+dy:.0f})")
                acted = True

            # 2. Train villagers (always, up to ~30 pop)
            if not acted and food >= 50 and hh > 1 and current_pop < 35:
                r = c.request({"action": "train", "unit_type": VILLAGER_MALE})
                if r.get("success"):
                    acted = True

            # 3. Loom (once, after a few vils)
            if not acted and not loom_done and current_pop >= 7:
                r = c.request({"action": "research", "technology": LOOM})
                if r.get("success"):
                    print("  Researching Loom")
                    loom_done = True
                    acted = True

            # 4. Feudal Age (need 500F 0G, usually at ~22 pop)
            if not acted and age == 0 and not feudal_sent and current_pop >= 18 and food >= 500:
                r = c.request({"action": "research", "technology": FEUDAL_AGE})
                if r.get("success"):
                    print("  >>> ADVANCING TO FEUDAL <<<")
                    feudal_sent = True
                    acted = True

            # 5. Feudal buildings (Blacksmith + Market for Castle Age)
            if not acted and age >= 1:
                if not blacksmith_sent and wood >= 150:
                    r = c.request({"action": "build", "building_type": BLACKSMITH,
                                   "x": tc_x + 8, "y": tc_y + 5})
                    if r.get("success"):
                        print("  Building Blacksmith")
                        blacksmith_sent = True
                        acted = True

                if not acted and not market_sent and wood >= 175:
                    r = c.request({"action": "build", "building_type": MARKET,
                                   "x": tc_x - 8, "y": tc_y + 5})
                    if r.get("success"):
                        print("  Building Market")
                        market_sent = True
                        acted = True

            # 6. Castle Age (need 800F 200G + 2 feudal buildings)
            if not acted and age >= 1 and not castle_age_sent:
                if blacksmith_sent and market_sent and food >= 800 and gold >= 200:
                    r = c.request({"action": "research", "technology": CASTLE_AGE})
                    if r.get("success"):
                        print("  >>> ADVANCING TO CASTLE AGE <<<")
                        castle_age_sent = True
                        acted = True

            # 7. BUILD THE CASTLE!
            if not acted and age >= 2 and stone >= 650 and not castle_sent:
                print("  >>> BUILDING CASTLE! <<<")
                units = c.request({"action": "get_units"})
                time.sleep(0.3)
                vils = [u["id"] for u in units.get("units", []) if u.get("class") == 904][:5]
                r = c.request({"action": "build", "building_type": CASTLE,
                               "x": tc_x + 15, "y": tc_y, "builder_ids": vils})
                if r.get("success"):
                    print("  !!! CASTLE CONSTRUCTION STARTED !!!")
                    castle_sent = True
                    acted = True
                else:
                    # Try another position
                    r = c.request({"action": "build", "building_type": CASTLE,
                                   "x": tc_x - 15, "y": tc_y, "builder_ids": vils})
                    if r.get("success"):
                        print("  !!! CASTLE CONSTRUCTION STARTED (alt pos) !!!")
                        castle_sent = True
                        acted = True

            # 8. Scout
            if not acted and t < 120:
                c.request({"action": "scout"})

            # Check if castle is done (after sending build)
            if castle_sent and age >= 2:
                # Wait a bit then check buildings
                time.sleep(2)
                buildings = c.request({"action": "get_buildings"})
                time.sleep(0.3)
                for b in buildings.get("buildings", []):
                    if "Castle" in b.get("name", "") or b.get("type") == CASTLE:
                        hp = b.get("hp", 0)
                        maxhp = b.get("maxHp", 1)
                        print(f"  Castle HP: {hp}/{maxhp}")
                        if hp >= maxhp * 0.95:
                            print("\n=== MISSION COMPLETE: CASTLE BUILT! ===")
                            c.request({"action": "chat", "message": "Castle built! GG!"})
                            time.sleep(1)
                            return

            time.sleep(TICK_DELAY)

    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as e:
        print(f"\nError: {e}")
    finally:
        try:
            c.disconnect()
        except:
            pass


if __name__ == "__main__":
    main()
