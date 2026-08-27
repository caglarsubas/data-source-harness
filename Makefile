.PHONY: lint test contracts phase0 phase1 phase2 build

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -q

contracts:
	uv run harness-contracts validate

build:
	uv build
	uv run --no-project --isolated --with ./dist/orchestra_data_source_harness-0.3.0-py3-none-any.whl python -c 'from importlib.resources import files; import data_source_harness as h; root = files("data_source_harness"); assert h.__version__ == "0.3.0"; assert (root / "resources/schemas/v1/data-batch.schema.json").is_file(); assert (root / "resources/schemas/v1/promotion-readiness.schema.json").is_file()'

phase0: lint test contracts build
	uv run harness-contracts phase0-gate --output phase0-report.json

phase1: phase0
	uv run python -m reference_labs.white_goods.certify --output phase1-report.json
	uv run python -m reference_labs.white_goods.bundle build
	uv run python -m reference_labs.white_goods.bundle verify

phase2: phase1
	uv run python -m reference_labs.white_goods.certify_phase2 --output phase2-report.json
	uv run python -m reference_labs.white_goods.bundle build
	uv run python -m reference_labs.white_goods.bundle verify
