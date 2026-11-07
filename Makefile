# rlhfbook-deepdive. `make help` lists the targets. AGENTS.md explains the workflows.

TRANSCRIPT_REPO ?= ../transcript-rag-agent
TRANSCRIPT_API  ?= http://127.0.0.1:8001
CHANNEL         ?= https://www.youtube.com/@natolambert

help: ## list the targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed -E 's/:.*## /\t/' | expand -t 18

setup: ## check out the pinned book and install the dev tools
	git submodule update --init --depth 1 sources/rlhf-book
	uv sync

transcripts: ## export transcripts from transcript-rag-agent (read-only, free)
	uv run scripts/export_transcripts.py

collect: ## queue new channel videos in transcript-rag-agent (spends Supadata credits)
	@curl -fsS -X POST $(TRANSCRIPT_API)/api/index/queue -H 'content-type: application/json' \
		-d '{"mode":"channel","channel":"$(CHANNEL)","latest":50}' >/dev/null \
		|| { echo "No transcript server at $(TRANSCRIPT_API). See 'Add transcripts' in AGENTS.md."; exit 1; }
	@echo "Queued. When the job is done in $(TRANSCRIPT_API), run: make transcripts"

collect-video: ## queue one video: make collect-video URL=https://youtu.be/... (spends credits)
	@test -n "$(URL)" || { echo "usage: make collect-video URL=..."; exit 1; }
	@curl -fsS -X POST $(TRANSCRIPT_API)/api/index/queue -H 'content-type: application/json' \
		-d '{"mode":"video","url":"$(URL)"}' >/dev/null \
		|| { echo "No transcript server at $(TRANSCRIPT_API). See 'Add transcripts' in AGENTS.md."; exit 1; }
	@echo "Queued. When the job is done in $(TRANSCRIPT_API), run: make transcripts"

book-update: ## move the book pin to upstream main (old citations stay valid)
	git -C sources/rlhf-book fetch --depth 1 origin main
	git -C sources/rlhf-book checkout --quiet FETCH_HEAD
	@echo "Pin is now $$(git -C sources/rlhf-book rev-parse --short HEAD). Commit sources/rlhf-book."

search: ## find passages: make search Q="why does RLVR omit the KL penalty"
	@uv run scripts/cite.py search "$(Q)"

resolve: ## show what a citation points at: make resolve ID="yt:6StK9ttLNbQ@00:04:14"
	@uv run scripts/cite.py resolve "$(ID)"

check: ## verify every citation and quote in .lavish/ and notes/
	@uv run scripts/cite.py check

test: ## run the unit tests
	uv run pytest -q

lint: ## ruff and mypy
	uv run ruff format --check scripts tests
	uv run ruff check scripts tests
	uv run mypy

.PHONY: help setup transcripts collect collect-video book-update search resolve check test lint
