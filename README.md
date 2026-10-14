# Arknights Integrated Strategies Archipelago

A community-maintained, **manual-check** Archipelago world for Arknights Integrated Strategies.

> This project is unofficial and is not affiliated with, endorsed by, or associated with Hypergryph, Yostar, or Archipelago.

**Mostly vibe-coded as it was initially intended for private usage. I will not guarantee that this will be updated frequently, especially with modes and character releases.**

## What it does

The APWorld randomizes access to supported Integrated Strategies modes, squads, and operator permits. Its companion client connects to an Archipelago room and lets the player report checks they earn in-game. It **never reads, changes, automates, or connects to Arknights**.

Supported content includes IS2–IS6, mode access, squad permissions, operator permits, mode and ending goals, and optional floor, boss, encounter, ending, and Ducksanity checks. See the in-game Archipelago YAML/options interface for the complete, version-matched option descriptions.

<img width="796" height="596" alt="unlock-tracker" src="https://github.com/user-attachments/assets/67daa00a-d149-4dc2-99d3-91aa9b43a37a" />

## Install and build

Use an Archipelago installation compatible with the `compatible_version` in [`archipelago.json`](archipelago.json).

```bash
git clone https://github.com/TheKombiZombi/Arknights-IS-AP.git
cd arknights-is-ap
python3 build_apworld.py
```

Install `dist/arknights_integrated_strategies.apworld` through the Archipelago Launcher, then generate the room with that APWorld available to the generator.

## Companion client

Launch the client from an environment containing the same Archipelago release used for the room:

```bash
PYTHONPATH="$PWD:/path/to/Archipelago" python3 client.py --connect host:port --name YOUR_SLOT
```

The client provides a check-submission view, unlock tracker, and optional screenshot reporter. Screenshot recognition is opt-in, operates only on screenshots the player explicitly selects or captures, and submits only high-confidence unresolved checks. It does not save live captures.

Run with `--nogui` when graphical dependencies or a display are unavailable. Console commands include `/unlocked`, `/mode-hints`, `/missing <text>`, `/check <unique location fragment>`, `/complete-ending <unique ending fragment>`, `/complete-mode IS2`, `/recognize <screenshot-or-directory>`, and `/retire-confirm IS2`.

## Artwork and game assets

This non-profit fan project includes Arknights operator portraits and class icons in the tracker for player recognition. They remain the property of their respective rightsholders; this project is unofficial and makes no claim of ownership or endorsement. Do not add game files, account data, or extracted material beyond the project’s established tracker artwork without maintainer review.

## Development

The project has no bundled dependency environment; run the tests with a Python environment that can import Archipelago to exercise world-generation tests.

```bash
python3 -m unittest discover -s tests -v
python3 build_apworld.py
```

Some tests are skipped when optional dependencies, local evidence fixtures, or an Archipelago source checkout are unavailable. See [`CONTRIBUTING.md`](CONTRIBUTING.md) for contribution and rights boundaries.

## Status

This is an experimental community implementation. It makes no claim of official support, compatibility with every Arknights release, or compliance with third-party game terms. Use it only with accounts, software, and content you are authorized to use.
