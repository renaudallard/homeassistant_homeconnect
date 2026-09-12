# Run the same checks CI runs (see .github/workflows/test.yml), so a local
# pass cannot hide a CI failure. Uses the virtualenv under tmp/ when it is
# there, otherwise whatever ruff/mypy/pytest are on PATH.
BIN := $(if $(wildcard tmp/venv/bin),tmp/venv/bin/,)

.PHONY: check lint types test
check: lint types test

lint:
	$(BIN)ruff check .
	$(BIN)ruff format --check .

types:
	$(BIN)mypy custom_components/ tests/ tools/

test:
	$(BIN)pytest tests/ -q
