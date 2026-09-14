.PHONY: install pre-commit list mock example prepare test lint coverage smoke-mock smoke

install:
	uv venv --python 3.12 .venv
	uv sync --extra dev
	pre-commit install

list:
	.venv/bin/python -m dumemeval list

mock:
	.venv/bin/python -m dumemeval run --config examples/user_preference.yaml --mock

example:
	.venv/bin/python -m dumemeval run --config examples/locomo_mini.yaml --mock --no-resume

# 一键下载完整官方数据集到缓存（smoke 子集已随仓库捆绑在 data/smoke/，无需下载）
prepare:
	.venv/bin/python -m dumemeval prepare

# 默认 real smoke 四臂：2 数据 × (transfer | test_only)
SMOKE_CFGS = \
	configs/smoke/locomo_transfer.yaml \
	configs/smoke/locomo_test_only.yaml \
	configs/smoke/shopping_transfer.yaml \
	configs/smoke/shopping_test_only.yaml

smoke-mock:
	@for c in $(SMOKE_CFGS); do \
		echo "==> mock $$c"; \
		.venv/bin/python -m dumemeval run --config $$c --mock --no-resume || exit 1; \
	done

smoke:
	@for c in $(SMOKE_CFGS); do \
		echo "==> harbor $$c"; \
		.venv/bin/python -m dumemeval run --config $$c --no-resume || echo "WARN: $$c failed"; \
	done

test:
	.venv/bin/python -m pytest tests/ -m "not e2e"

lint:
	.venv/bin/ruff check src/dumemeval tests
	.venv/bin/ruff format --check src/dumemeval tests
	.venv/bin/mypy

coverage:
	.venv/bin/python -m pytest tests/ -m "not e2e" --cov=dumemeval --cov-report=term-missing
