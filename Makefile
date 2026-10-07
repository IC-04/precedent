SEED ?= 7
TEMPLATE ?= northwind
TASK ?= Enter the latest Figma invoice and route it for approval.
WORKER ?= precedent

.PHONY: setup test lint world apps console run grade eval

setup:
	uv sync
	npm ci --no-fund --no-audit
	uv run playwright install chromium
	@test -f .env || cp .env.example .env
	@uv run python -c "import re, secrets, pathlib; p = pathlib.Path('.env'); s = p.read_text(); p.write_text(re.sub(r'(?m)^PRECEDENT_SCENARIO_TOKEN=change-me.*$$', 'PRECEDENT_SCENARIO_TOKEN=' + secrets.token_urlsafe(16), s))"

test:
	uv run pytest -q

lint:
	uv run ruff check src tests
	uv run ruff format --check src tests

world:
	uv run precedent world --template $(TEMPLATE) --seed $(SEED)

apps:
	uv run precedent apps --seed $(SEED)

console:
	uv run precedent console

run:
	uv run precedent run --seed $(SEED) --worker $(WORKER) --task "$(TASK)"

grade:
	uv run precedent grade --seed $(SEED) --task $(TASK_ID) --run $(RUN)

eval:
	uv run precedent eval --template $(TEMPLATE)
