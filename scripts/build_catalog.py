#!/usr/bin/env python3
"""Rebuild ``arknights_is/catalog.json`` from reviewed local text sources.

The input files are intentionally supplied explicitly so this maintenance helper
has no dependency on a contributor's home directory or private workspace.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

ROOT = Path(__file__).parents[1]
SQUADS = {
    "IS2": ["Leader Squad", "Gathering Squad", "Support Squad", "Spearhead Squad", "Tactical Assault Squad", "Tactical Fortification Squad", "Tactical Ranged Squad", "Tactical Destruction Squad", "Research Squad", "First-Class Squad"],
    "IS3": ["Leader Squad", "Gathering Squad", "Support Squad", "Spearhead Squad", "Tactical Assault Squad", "Tactical Fortification Squad", "Tactical Ranged Squad", "Tactical Destruction Squad", "Research Squad", "First-Class Squad", "Mind Over Matter Squad", "Resourceful Squad", "People-Oriented Squad"],
    "IS4": ["Leader Squad", "Gathering Squad", "Support Squad", "Spearhead Squad", "Tactical Assault Squad", "Tactical Fortification Squad", "Tactical Ranged Squad", "Tactical Destruction Squad", "Special Training Squad", "First-Class Squad", "Eternal Hunting Squad", "Life Prioritizing Squad", "Scientific Thinking Squad"],
    "IS5": ["Leader Squad", "Gathering Squad", "Support Squad", "Spearhead Squad", "Tactical Assault Squad", "Tactical Fortification Squad", "Tactical Ranged Squad", "Tactical Destruction Squad", "First-Class Squad", "Improvisation Squad", "Soul Escort Squad", "Erudite Squad", "Blueprint Squad", "Ingots Squad", "Collection Squad", "Mimic Squad", "Top Gun Squad"],
    "IS6": ["Leader Squad", "Special Squad", "Support Squad", "Tactical Assault Squad", "Tactical Fortification Squad", "Tactical Ranged Squad", "Tactical Destruction Squad", "High Ground Breaching Operators", "Ground Breaching Operators", "First-Class Squad", "Tourist Squad", "Sui Regulator Squad", "Tianshi Bureau Squad", "Blooming Flowers Squad", "Perilous Game Squad", "Sui's Shadow Squad", "Proxy Squad", "Knowledge Squad", "Merchant Squad"],
}


def parse_operators(path: Path) -> list[str]:
    ignored_prefixes = ("Arknights", "As of:", "Scope", "Primary", "http", "Count:")
    return [
        line for line in path.read_text(encoding="utf8").splitlines()
        if line and not line.startswith(ignored_prefixes)
    ]


def parse_stages(path: Path) -> dict[str, dict[str, list[object]]]:
    modes = {
        f"IS{number}": {"normal": [], "f3_bosses": [], "f5_bosses": [], "f6_bosses": [], "encounters": [], "endings": []}
        for number in range(2, 7)
    }
    mode: str | None = None
    floor: int | str | None = None
    subsection: str | None = None
    for raw in path.read_text(encoding="utf8").splitlines():
        line = raw.strip()
        match = re.match(r"# IS([2-6]) ", line)
        if match:
            mode, floor, subsection = f"IS{match.group(1)}", None, None
            continue
        if not mode:
            continue
        if line == "Endings:":
            subsection = "endings"
            continue
        if line.startswith("## Floor "):
            floor, subsection = int(line.split()[-1]), "normal"
            continue
        if line.startswith("## Shifei/Jinxi Border"):
            floor, subsection = "Shifei/Jinxi Border", "normal"
            continue
        if line == "### Dreadful Foe":
            subsection = "boss"
            continue
        if line == "## Encounter Stages":
            subsection = "encounters"
            continue
        if not line or line.startswith(("#", "Primary", "Scope", "Method", "Catalog", "•")):
            continue
        value = line.lstrip("- ").strip()
        if subsection == "endings":
            modes[mode]["endings"].append(value)
        elif subsection == "normal":
            modes[mode]["normal"].append({"floor": floor, "name": value})
        elif subsection == "boss" and isinstance(floor, int):
            modes[mode][f"f{floor}_bosses"].append(value)
        elif subsection == "encounters":
            modes[mode]["encounters"].append(value)
    return modes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--operators", type=Path, required=True, help="reviewed operator-list text file")
    parser.add_argument("--stages", type=Path, required=True, help="reviewed IS-stage-list text file")
    parser.add_argument("--output", type=Path, default=ROOT / "arknights_is" / "catalog.json")
    args = parser.parse_args()
    modes = parse_stages(args.stages)
    output = {"operators": parse_operators(args.operators), "squads": SQUADS, "modes": modes}
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf8")
    print(f"operators={len(output['operators'])} normal={sum(len(data['normal']) for data in modes.values())} encounters={sum(len(data['encounters']) for data in modes.values())}")


if __name__ == "__main__":
    main()
