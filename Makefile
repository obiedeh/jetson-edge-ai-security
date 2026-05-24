.PHONY: install install-dev test lint typecheck demo-report static-reports validate-artifacts verify web-install web-dev web-build

PYTHON ?= .venv/bin/python
PIP ?= .venv/bin/pip

.venv:
	python3 -m venv .venv

install: .venv
	$(PIP) install -e .

install-dev: .venv
	$(PIP) install -e ".[dev]"

test: .venv
	PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 $(PYTHON) -m pytest -q -p pytest_asyncio.plugin

lint: .venv
	$(PYTHON) -m ruff check src tests

typecheck: .venv
	$(PYTHON) -m mypy src/jetson_edge_ai_security

demo-report: .venv
	$(PYTHON) -m jetson_edge_ai_security.cli generate-demo-report --output-dir reports/demo

static-reports: .venv
	$(PYTHON) -m jetson_edge_ai_security.cli build-static-reports --reports-dir reports

validate-artifacts:
	test -s reports/demo/runtime_metrics.json
	test -s reports/demo/alerts.jsonl
	test -s reports/demo/replay_report.md
	test -s reports/index.html
	test -s reports/dashboard.html
	test -s reports/tech-brief.html
	test -s reports/business-case.html

verify: lint typecheck test demo-report static-reports validate-artifacts web-build

web-install:
	cd web && pnpm install

web-dev:
	cd web && pnpm dev

web-build:
	cd web && pnpm build
