run:
	uv run python -m uvicorn src.api.app:app --reload --port 8000

lint:
	uv run ruff check src/

test:
	uv run python -m pytest
