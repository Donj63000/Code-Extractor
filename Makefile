# Détection basique
MVNW := $(shell [ -x mvnw ] && echo ./mvnw || echo mvn)

.PHONY: install test lint build clean

install:
	@set -e; \
	if [ -f pyproject.toml ]; then \
	  python -m pip install --upgrade pip; \
	  if grep -qi '\[tool.poetry\]' pyproject.toml; then python -m pip install poetry && poetry install --no-interaction; \
	  elif grep -qi '\[tool.pdm\]' pyproject.toml; then python -m pip install pdm && pdm install; \
	  else python -m pip install -e .[dev] || true; [ -f requirements.txt ] && python -m pip install -r requirements.txt || true; \
	  fi; \
	elif ls requirements*.txt >/dev/null 2>&1; then \
	  python -m pip install --upgrade pip; python -m pip install -r requirements.txt || python -m pip install -r requirements-dev.txt; \
	fi; \
	if [ -f pom.xml ]; then \
	  $(MVNW) -B -ntp -DskipTests=true clean package; \
	fi

test:
	@set -e; \
	if [ -f pyproject.toml ] || ls requirements*.txt >/dev/null 2>&1; then \
	  pytest -q || python -m pytest -q; \
	fi; \
	if [ -f pom.xml ]; then \
	  $(MVNW) -B -ntp -DskipTests=false test; \
	fi

lint:
	@set -e; \
	if [ -f pyproject.toml ] || ls requirements*.txt >/dev/null 2>&1; then \
	  python -m pip install "ruff==0.*" "black==24.*"; \
	  ruff check .; black --check .; \
	fi; \
	if [ -f pom.xml ]; then \
	  $(MVNW) -B -ntp -DskipTests=true checkstyle:check || echo "Checkstyle non configuré"; \
	fi

build:
	@set -e; \
	if [ -f pyproject.toml ] || ls requirements*.txt >/dev/null 2>&1; then \
	  python -m pip install build || true; \
	  python -m build || true; \
	fi; \
	if [ -f pom.xml ]; then \
	  $(MVNW) -B -ntp -DskipTests=true package; \
	fi

clean:
	@rm -rf build dist .pytest_cache .ruff_cache .mypy_cache **/__pycache__
	@if [ -f pom.xml ]; then $(MVNW) -B -ntp clean; fi
