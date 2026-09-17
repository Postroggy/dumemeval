.PHONY: install pre-commit list mock example prepare test lint coverage smoke-mock smoke ci

UV ?= uv

# mock 编排不打真实 LLM；smoke / 示例 yaml 里有 ${ANTHROPIC_*} 模板，给占位值让加载通过
CI_MOCK_ENV = ANTHROPIC_AUTH_TOKEN=ci-mock-dummy ANTHROPIC_BASE_URL=https://example.invalid ANTHROPIC_MODEL=ci-mock-dummy

install:
	uv venv --python 3.12 .venv
	uv sync --extra dev
	pre-commit install

list:
	$(UV) run python -m dumemeval list

mock:
	$(CI_MOCK_ENV) $(UV) run python -m dumemeval run --config examples/user_preference.yaml --mock --no-resume

example:
	$(UV) run python -m dumemeval run --config examples/locomo_mini.yaml --mock --no-resume

# 一键下载完整官方数据集到缓存（smoke 子集已随仓库捆绑在 data/smoke/，无需下载）
prepare:
	$(UV) run python -m dumemeval prepare

# 默认 real smoke 四臂：2 数据 × (transfer | test_only)
SMOKE_CFGS = \
	configs/smoke/locomo_transfer.yaml \
	configs/smoke/locomo_test_only.yaml \
	configs/smoke/shopping_transfer.yaml \
	configs/smoke/shopping_test_only.yaml

smoke-mock:
	@for c in $(SMOKE_CFGS); do \
		echo "==> mock $$c"; \
		$(CI_MOCK_ENV) $(UV) run python -m dumemeval run --config $$c --mock --no-resume || exit 1; \
	done

smoke:
	@for c in $(SMOKE_CFGS); do \
		echo "==> harbor $$c"; \
		$(UV) run python -m dumemeval run --config $$c --no-resume || echo "WARN: $$c failed"; \
	done

test:
	$(UV) run pytest tests/ -m "not e2e"

lint:
	$(UV) run ruff check src tests
	$(UV) run ruff format --check src tests
	$(UV) run mypy

coverage:
	$(UV) run pytest tests/ -m "not e2e" --cov=dumemeval --cov-report=term-missing

# 本地与 GitHub Actions 的唯一门禁（.github/workflows/ci.yml 只调用这一条）
ci: lint test
	$(UV) build
	$(MAKE) example
	$(MAKE) mock
	$(MAKE) smoke-mock
