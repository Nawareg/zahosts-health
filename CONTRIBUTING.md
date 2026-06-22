# Contributing

## Development Setup

```bash
pip install -r requirements-dev.txt
python -m pytest
python -m ruff check .
```

## Tests

Tests are fully offline. Collector behavior is exercised with captured fixtures in `tests/fixtures/`, so contributors do not need a WHM server for normal development.

## Style

Each collector lives in `zahosts_health/collectors/` behind the `Collector` interface. Keep ruff clean and avoid adding dependencies when the standard library is enough.

## Payload Contract

Do not change `status.json` keys without updating `tests/test_payload_contract.py` and bumping `schema_version`. The WHM UI depends on that contract.

Pull requests must keep ruff clean and all tests green.
