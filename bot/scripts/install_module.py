"""Install the aoe2bot Lua module into AoE2Control's modules directory."""

import os
import shutil
import sys
from pathlib import Path


def main():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        print("ERROR: APPDATA environment variable not found.", file=sys.stderr)
        sys.exit(1)

    modules_dir = Path(appdata) / "CONTROL" / "AoE2Control" / "modules"
    source_dir = Path(__file__).parent.parent.parent / "game" / "aoe2bot"

    if not source_dir.exists():
        print(f"ERROR: Source module not found at {source_dir}", file=sys.stderr)
        sys.exit(1)

    target_dir = modules_dir / "aoe2bot"

    if not modules_dir.exists():
        print(f"AoE2Control modules directory not found at {modules_dir}")
        print("Make sure AoE2Control has been run at least once to create the config directory.")
        print(f"Creating directory: {modules_dir}")
        modules_dir.mkdir(parents=True, exist_ok=True)

    if target_dir.exists():
        print(f"Removing existing module at {target_dir}")
        shutil.rmtree(target_dir)

    print(f"Copying {source_dir} -> {target_dir}")
    shutil.copytree(source_dir, target_dir)
    print("Done! Module installed successfully.")
    print(f"  Source: {source_dir}")
    print(f"  Target: {target_dir}")
    print()
    print("Next steps:")
    print("  1. Launch AoE2:DE")
    print("  2. Run AoE2Control.exe and click START")
    print("  3. Assign 'aoe2bot' module to a player slot")
    print("  4. Start a game")
    print("  5. Run: aoe2bot ping")


if __name__ == "__main__":
    main()
