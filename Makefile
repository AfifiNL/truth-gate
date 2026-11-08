# Everything here runs offline and costs nothing. `make check` is exactly what CI runs.
UV ?= uv

.PHONY: help install lint fmt typecheck test eval eval-baseline cases demo check

help:            ## list targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | sed 's/:.*## /\t/'

install:         ## create .venv with dev tools (locked)
	$(UV) sync

lint:            ## ruff lint + format check
	$(UV) run ruff check src tests evals
	$(UV) run ruff format --check src tests evals

fmt:             ## apply ruff formatting and safe fixes
	$(UV) run ruff format src tests evals
	$(UV) run ruff check --fix src tests evals

typecheck:       ## mypy (strict)
	$(UV) run mypy

test:            ## pytest
	$(UV) run pytest

eval:            ## eval corpus + gate (exits 1 when a floor or the baseline is broken)
	$(UV) run truth-gate eval --out reports/eval.md

eval-baseline:   ## re-record evals/baseline.json (review the diff before committing)
	$(UV) run truth-gate eval --update-baseline

cases:           ## rebuild evals/cases.jsonl from evals/build_cases.py
	$(UV) run python evals/build_cases.py

demo:            ## check the two example documents
	-$(UV) run truth-gate check examples/pass.md --facts examples/facts.yaml
	-$(UV) run truth-gate check examples/fail.md --facts examples/facts.yaml

check: lint typecheck test eval  ## everything CI runs
