.PHONY: lint test contracts local-only phase0 phase1 phase2 phase3 phase4 phase5 phase6 phase6.5 phase7-readiness phase7-local-sources phase7-local-readiness build wheelhouse

lint:
	uv run ruff check .
	uv run ruff format --check .

test:
	uv run pytest -q --cov=data_source_harness --cov-branch --cov-report=term-missing --cov-fail-under=85

contracts:
	uv run harness-contracts validate

local-only:
	uv run python scripts/check-local-only.py

build:
	uv build
	uv run --no-project --isolated --with ./dist/orchestra_data_source_harness-0.11.0-py3-none-any.whl python -c 'from importlib.resources import files; import data_source_harness as h; root = files("data_source_harness"); assert h.__version__ == "0.11.0"; assert (root / "resources/schemas/v1/data-batch.schema.json").is_file(); assert (root / "resources/schemas/v1/connector-worker-profile.schema.json").is_file(); assert (root / "resources/schemas/v1/live-acceptance-campaign.schema.json").is_file(); assert (root / "resources/schemas/v1/local-source-evidence.schema.json").is_file(); assert (root / "resources/deployment/profiles/local-laptop.json").is_file()'
	uv run --no-project --isolated --with ./dist/orchestra_data_source_harness-0.11.0-py3-none-any.whl harness-contracts validate

wheelhouse: build
	bash scripts/build-airgap-wheelhouse.sh

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

phase3: phase2
	uv run python -m reference_labs.cold_chain.certify --output phase3-report.json
	uv run python -m reference_labs.cold_chain.bundle build
	uv run python -m reference_labs.cold_chain.bundle verify

phase4: phase3
	uv run python -m reference_labs.certify_phase4 --output phase4-report.json
	uv run python -m reference_labs.white_goods.bundle build
	uv run python -m reference_labs.white_goods.bundle verify
	uv run python -m reference_labs.cold_chain.bundle build
	uv run python -m reference_labs.cold_chain.bundle verify

phase5: phase4
	uv run python -m reference_labs.certify_phase5 --output phase5-report.json
	uv run python -m reference_labs.white_goods.bundle build
	uv run python -m reference_labs.white_goods.bundle verify
	uv run python -m reference_labs.cold_chain.bundle build
	uv run python -m reference_labs.cold_chain.bundle verify

phase6: phase5
	uv run python -m reference_labs.certify_phase6 --output phase6-report.json
	uv run python -m reference_labs.white_goods.runtime_bundle build
	uv run python -m reference_labs.white_goods.runtime_bundle verify
	uv run python -m reference_labs.white_goods.runtime_bundle readiness

phase6.5: phase6 wheelhouse
	uv run python -m reference_labs.certify_phase6_5 --output phase6.5-report.json
	uv run python -m reference_labs.white_goods.runtime_bundle build
	uv run python -m reference_labs.white_goods.runtime_bundle verify
	uv run python -m reference_labs.white_goods.runtime_bundle readiness

phase7-local-readiness: phase6.5 local-only
	uv run python -m reference_labs.certify_phase7_readiness --output phase7-readiness-report.json

phase7-local-sources: local-only
	uv run python -m reference_labs.white_goods.live.local_lab --lock-output compatibility/phase7-local-images.lock.json --output compatibility/phase7-local-source-evidence.json

phase7-readiness: phase7-local-readiness
