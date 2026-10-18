.PHONY: up ingest index eval ui test

up:
	docker compose up -d

# Stages 1-4: parse, clean, chunk, metadata (run `python -m scripts.download_docs` first).
ingest:
	uv run python -m src.ingest

# Stages 5-6: embed and store in Qdrant (needs `make up`). Safe to re-run.
index:
	uv run python -m src.index

eval:
	uv run python -m eval.run

ui:
	uv run python -m src.ui

test:
	uv run pytest
