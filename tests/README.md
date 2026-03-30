# PosterShop Tests

## Unit Tests (no running services required)

```
pip install -r tests/requirements.txt
pytest tests/unit/ -v
```

## Integration Tests (requires live stack)

Start all services first:
```
make dev
# or: docker compose up -d
```

Then run:
```
pytest tests/integration/ -v
```

Integration tests seed catalog and inventory via POST /seed before running.
They poll the orders service for up to 30s waiting for status transitions.
