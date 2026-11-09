# CS3081 Mini Project - build, train, deploy, tear down.
# `make train` reads only training/config.yaml (plus SUBSET / VERSION overrides).
VENV ?= .venv/bin/python
SUBSET ?=
VERSION ?= v1

.PHONY: train
train:
	@if [ -n "$(SUBSET)" ]; then \
		$(VENV) training/train.py --subset $(SUBSET) --version $(VERSION); \
	else \
		$(VENV) training/train.py --version $(VERSION); \
	fi

.PHONY: clean
clean:
	$(VENV) worker/clean.py

.PHONY: up
up:
	bash scripts/make_up.sh

.PHONY: down
down:
	bash scripts/make_down.sh

.PHONY: test
test:
	.venv/bin/python -m pytest tests/ -v
