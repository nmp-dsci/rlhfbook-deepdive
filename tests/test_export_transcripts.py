"""Transcript export: selection, block grouping, and the data the public catalogue may hold."""

from __future__ import annotations

import json
from typing import Any

import export_transcripts as export


def _segment(text: str, start: float) -> dict[str, Any]:
    return {"text": text, "start_seconds": start}


def test_lambert_is_selected_by_either_channel_form_and_others_only_via_the_course_page() -> None:
    # Regression: Supadata returns the handle for some videos, which an id-only filter dropped.
    records: dict[str, dict[str, Any]] = {
        "byid": {"channel_id": "UCayQjCHzSnqPszcHNMmfkSg"},
        "byhandle": {"channel_id": "@natolambert"},
        "stanford": {"channel_id": "UCBa5G_ESCn8Yd4vw5U-gIcg"},
        "stranger": {"channel_id": "UCsomeoneelse"},
    }
    roles = {"stanford": {"role": "talk", "chapters": [8]}}
    assert set(export.select_lambert(records, roles)) == {"byid", "byhandle", "stanford"}


def test_blocks_group_segments_into_timestamped_windows() -> None:
    grouped = export.blocks(
        [_segment("one", 0.0), _segment("two", 12.0), _segment("three", 31.0), _segment(" ", 40.0)]
    )
    assert grouped == [(0.0, "one two"), (31.0, "three")]


def test_timestamp() -> None:
    assert export.timestamp(3725.9) == "01:02:05"


def test_catalog_entry_holds_a_hash_but_no_transcript_text() -> None:
    record = {
        "title": "Lecture",
        "channel_id": "@natolambert",
        "channel_name": "Nathan Lambert",
        "upload_date": "2026-01-01",
        "fetched_at": "2026-11-07",
        "provider": "supadata",
        "duration_seconds": "61.0",
        "document": json.dumps({"segments": [_segment("a very distinctive sentence", 0.0)]}),
    }
    entry, text = export.entry_for("abcdefghijk", record, {})
    assert "distinctive" in text
    assert "distinctive" not in json.dumps(entry)
    assert entry["word_count"] == 4
    assert entry["role"] == "channel"
    assert entry["duration_seconds"] == 61.0
    assert len(entry["transcript_sha256"]) == 64
