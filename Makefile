SHELL := bash
.SHELLFLAGS := -e -x -c

# Cross-platform Bash
ifeq ($(OS),Windows_NT)
BASH := "C:/Program Files/Git/bin/bash.exe"
else
BASH := bash
endif

.PHONY: install
install: ## 🚀 Set up environment and install project
	@echo "🚀 Syncing dependencies with uv..."
	@if [ -f uv.lock ]; then \
		uv sync --frozen; \
	else \
		uv sync; \
	fi
	@echo "🔧 Installing project in editable mode..."
	uv pip install -e .

.PHONY: check-version
check-version:
	@echo "🔍 Checking the release tag against the package version..."
	@VERSION=$$(uv run hatch version); \
	EXPECTED_TAG="v$$VERSION"; \
	if [ -z "$(RELEASE_TAG)" ]; then \
	    echo "❌ RELEASE_TAG must identify the release being checked."; \
	    exit 1; \
	elif [ "$(RELEASE_TAG)" != "$$EXPECTED_TAG" ]; then \
	    echo "❌ Release tag '$(RELEASE_TAG)' does not match package version '$$VERSION'."; \
	    exit 1; \
	else \
	    echo "✅ Release tag matches package version: $(RELEASE_TAG)"; \
	fi

.PHONY: check-dev-version
check-dev-version:
	@echo "🔍 Checking the computed development version..."
	@VERSION=$$(uv run hatch version); \
	if [[ "$$VERSION" =~ \.dev[0-9]+$$ ]]; then \
	    echo "✅ Development version: $$VERSION"; \
	else \
	    echo "❌ Expected a development version, got: $$VERSION"; \
	    exit 1; \
	fi

.PHONY: check
check: check-frontend ## Run all code quality checks
	@echo "🚀 Checking lock file consistency"
	@if [ -f uv.lock ]; then \
		uv lock --locked; \
	else \
		uv lock; \
	fi
	@echo "🚀 Running pre-commit hooks"
	uv run pre-commit run --all-files

.PHONY: check-frontend
check-frontend: ## Check frontend hooks, accessibility, and formatting
	npm --prefix frontend run lint
	npm --prefix frontend run format:check

.PHONY: test
test: ## Run tests using tox
	@echo "🚀 Testing code: Running tox across Python versions"
	uv run tox

.PHONY: test-local
test-local: ## Run tests in current Python environment using uv
	@echo "🚀 Testing code locally"
	uv run python -m pytest -rvx tests --cov --cov-config=pyproject.toml --cov-report html:coverage-html

.PHONY: test-frontend
test-frontend: ## Run browser tests against isolated storage and fake agent processes
	cd frontend && npm run test:e2e

.PHONY: build
build: clean ## Build package using uv
	@echo "🚀 Building project"
	uv build

.PHONY: clean
clean: ## Clean build artifacts
	@echo "🚀 Removing build artifacts"
	rm -rf dist build *.egg-info
	rm -rf .coverage coverage-html coverage.xml .pytest_cache
	find . -name '*.pyc' -delete

.PHONY: version
version: ## Print the current project version
	uv run hatch version

.PHONY: tag
tag: ## 🏷 Tag the current release version (fixes changelog and pushes tag)
	$(BASH) scripts/tag_release.sh

.PHONY: check-dist
check-dist: ## Validate dist/ artifacts (long description, format)
	@echo "🔍 Validating dist/ artifacts..."
	uv run twine check dist/*
	uv run python scripts/check_distribution_contents.py dist/*

.PHONY: publish
publish: ## Publish to production PyPI
	@echo "🚀 Publishing to PyPI"
	UV_PUBLISH_TOKEN=$(PYPI_TOKEN) uv publish --publish-url=https://upload.pypi.org/legacy/ --no-cache

.PHONY: publish-test
publish-test: ## Publish to TestPyPI (for dry runs)
	@echo "🚀 Publishing to TestPyPI"
	UV_PUBLISH_TOKEN=$(TEST_PYPI_TOKEN) uv publish --publish-url=https://test.pypi.org/legacy/ --no-cache

.PHONY: build-and-publish
build-and-publish: build check-dist publish ## Build and publish in one step

.PHONY: docker-build
docker-build: ## 🐳 Build the Relay container image locally
	$(BASH) scripts/docker.sh build

.PHONY: docker-smoke
docker-smoke: ## 🧪 Smoke-test the Relay container image
	$(BASH) scripts/docker.sh smoke

.PHONY: docker-e2e
docker-e2e: ## 🔁 Run a workflow in the Relay container image and check host Git
	$(BASH) scripts/docker.sh e2e

.PHONY: docker-up
docker-up: ## ▶️ Start Relay in Docker on 127.0.0.1:7845
	$(BASH) scripts/docker.sh up

.PHONY: docker-run
docker-run: docker-up ## ▶️ Alias for docker-up

.PHONY: docker-push
docker-push: ## 📤 Build and push multi-arch Relay container image to GHCR
	$(BASH) scripts/docker.sh push

.PHONY: docker-push-digest
docker-push-digest: ## 📤 Push a single-platform container image by digest to GHCR
	$(BASH) scripts/docker.sh push-digest

.PHONY: docker-publish-manifest
docker-publish-manifest: ## 📦 Publish multi-arch GHCR manifest from verified digests
	$(BASH) scripts/docker.sh publish-manifest

.PHONY: help
help:
	uv run python -c "import re; \
	[[print(f'\033[36m{m[0]:<24}\033[0m {m[1]}') for m in re.findall(r'^([a-zA-Z_-]+):.*?## (.*)$$', open(makefile).read(), re.M)] for makefile in ('$(MAKEFILE_LIST)').strip().split()]"

.DEFAULT_GOAL := help
