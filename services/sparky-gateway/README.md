# sparky-gateway

Authenticated internal API surface for Sparky (DGX Spark main intelligence
machine). Implements PLAN.md §12 (gateway requirements) and the Phase 3
foundation routes from §5.1: `/health`, `/ready`, `/v1/models`, `/metrics`.

External callers (Maestro, AI Router, MaestroUI, DarkBase) reach Sparky
through this gateway — never the raw runtime ports. The OpenAPI contract
lives in [`config/api-contract.yaml`](../../config/api-contract.yaml).

## Local development

```bash
pip install -e ../sparky-common
pip install -e '.[test]'

export SPARKY_API_KEY="$(openssl rand -hex 32)"
export SPARKY_MODEL_REGISTRY_PATH="$PWD/../../config/model-registry.yaml"

uvicorn --factory sparky_gateway.main:create_app --host 127.0.0.1 --port 8080
```

## Tests

```bash
pytest -q
```

The gateway refuses to boot without `SPARKY_API_KEY`. Tests inject a
fixed key via the `Settings` dataclass — no environment leakage.
