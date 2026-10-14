# Contributing

## Scope

Keep changes compatible with the version declared in `archipelago.json`, preserve stable item/location IDs, and add or update focused tests for behavioral changes. Do not make the client automate, control, inspect, or modify Arknights.

## Rights and privacy

Do not commit game files, screenshots containing account information, credentials, private room data, or material whose redistribution rights are unclear. The committed tracker artwork is an intentional, maintainer-reviewed exception for this non-profit fan project; do not add or replace it without maintainer review.

Use synthetic fixtures for recognition tests. Keep any personal evidence or captures outside the repository.

## Verification

Run the applicable checks before opening a change:

```bash
python3 -m unittest discover -s tests -v
python3 build_apworld.py
```

World-generation tests additionally require a compatible Archipelago source checkout on `PYTHONPATH`. State clearly when that environment is unavailable rather than treating skipped tests as passing generation coverage.
