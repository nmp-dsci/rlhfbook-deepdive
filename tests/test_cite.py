"""Citation resolution and checking, against a throwaway book repo and a small fake catalogue."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator
from pathlib import Path

import cite
import pytest

CHAPTER = """# Regularization

## KL Divergence

The KL penalty keeps the model near its reference [@schulman2017].
A second sentence about *optimization* pressure.
"""
TRANSCRIPT = """# Q&A 3

[00:00:00] Hello and welcome back to the course.

[00:00:30] Why does RLVR omit the KL penalty, it is a good question.

[00:01:00] The reward is verifiable so there is less to exploit.
"""
VIDEO = "6StK9ttLNbQ"


def _git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


@pytest.fixture
def sha(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    book = tmp_path / "book"
    chapter = book / "book" / "chapters" / "15-regularization.md"
    chapter.parent.mkdir(parents=True)
    chapter.write_text(CHAPTER)
    _git(tmp_path, "init", "-q", str(book))
    _git(book, "add", ".")
    _git(book, "-c", "user.name=t", "-c", "user.email=t@example.com", "commit", "-qm", "x")

    transcripts = tmp_path / "transcripts"
    transcripts.mkdir()
    (transcripts / f"{VIDEO}.md").write_text(TRANSCRIPT)
    catalog = tmp_path / "catalog.json"
    entry = {
        "video_id": VIDEO,
        "title": "Q&A 3",
        "duration_seconds": 90.0,
        "transcript_sha256": "not-checked-here",
    }
    catalog.write_text(json.dumps([entry]))

    monkeypatch.setattr(cite, "BOOK", book)
    monkeypatch.setattr(cite, "TRANSCRIPTS", transcripts)
    monkeypatch.setattr(cite, "CATALOG", catalog)
    monkeypatch.setattr(cite, "COURSE_MAP", tmp_path / "absent.json")
    monkeypatch.setattr(cite, "ROOT", tmp_path)
    cite.catalog.cache_clear()
    cite._book_lines.cache_clear()
    yield _git(book, "rev-parse", "HEAD")
    cite.catalog.cache_clear()
    cite._book_lines.cache_clear()


def _book_id(sha: str, span: str = "L5-L6") -> str:
    return f"book@{sha}:book/chapters/15-regularization.md#{span}"


def test_book_citation_gives_exact_lines_a_permalink_and_a_section(sha: str) -> None:
    source = cite.resolve(_book_id(sha))
    assert source.text is not None
    assert source.text.startswith("The KL penalty")
    assert "A second sentence" in source.text
    assert source.url.endswith(f"/blob/{sha}/book/chapters/15-regularization.md?plain=1#L5-L6")
    assert source.label == "Ch. 15 Regularization § KL Divergence (L5-L6)"
    assert source.read_url == "https://rlhfbook.com/c/15-regularization#kl-divergence"


def test_book_citation_past_the_end_of_the_file_fails(sha: str) -> None:
    with pytest.raises(cite.CitationError, match="lines at that commit"):
        cite.resolve(_book_id(sha, "L5-L99"))


def test_transcript_citation_links_to_the_second_and_returns_the_overlapping_blocks(
    sha: str,
) -> None:
    source = cite.resolve(f"yt:{VIDEO}@00:00:40-00:01:05")
    assert source.url == f"https://www.youtube.com/watch?v={VIDEO}&t=40s"
    assert source.text is not None
    assert "good question" in source.text
    assert "verifiable" in source.text
    assert "welcome back" not in source.text


def test_transcript_citation_past_the_end_of_the_video_fails(sha: str) -> None:
    with pytest.raises(cite.CitationError, match="long"):
        cite.resolve(f"yt:{VIDEO}@00:09:00")


def test_unknown_video_fails(sha: str) -> None:
    with pytest.raises(cite.CitationError, match="not in sources/catalog.json"):
        cite.resolve("yt:aaaaaaaaaaa@00:00:01")


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("the kl penalty keeps the model", True),  # case
        ("near its reference. A second sentence", True),  # pandoc citation dropped
        ("about optimization pressure", True),  # markdown emphasis dropped
        ("KL penalty … optimization pressure", True),  # ellipsis, in order
        ("optimization pressure … KL penalty", False),  # ellipsis, out of order
        ("the penalty keeps the model", False),  # a word removed
        ("he KL penalty", False),  # no partial words
        ("…", False),  # nothing to match
    ],
)
def test_quote_matching(quote: str, expected: bool) -> None:
    source_text = CHAPTER.split("## KL Divergence")[1]
    assert cite.quote_matches(quote, source_text) is expected


def _artifact(tmp_path: Path, citation: str, url: str, quote: str, ref: str = "#s1") -> Path:
    page = tmp_path / "s00_page.html"
    page.write_text(
        f'<p>Claim <a href="{ref}">1</a></p>'
        f'<figure id="s1" data-cite="{citation}"><blockquote>{quote}</blockquote>'
        f'<figcaption><a href="{url}">source</a></figcaption></figure>'
    )
    return page


def test_check_passes_a_good_artifact(sha: str, tmp_path: Path) -> None:
    citation = _book_id(sha)
    page = _artifact(tmp_path, citation, cite.resolve(citation).url, "The KL penalty keeps")
    report = cite.check([str(page)])
    assert report.errors == []
    assert report.verified == 1


def test_check_fails_a_quote_that_is_not_in_the_cited_range(sha: str, tmp_path: Path) -> None:
    citation = _book_id(sha)
    page = _artifact(tmp_path, citation, cite.resolve(citation).url, "KL is never useful")
    assert any("quote is not in" in error for error in cite.check([str(page)]).errors)


def test_check_fails_a_link_that_is_not_the_permalink(sha: str, tmp_path: Path) -> None:
    page = _artifact(tmp_path, _book_id(sha), "https://rlhfbook.com/", "The KL penalty keeps")
    assert any("must link to" in error for error in cite.check([str(page)]).errors)


def test_check_fails_a_dangling_reference_and_an_unused_source(sha: str, tmp_path: Path) -> None:
    citation = _book_id(sha)
    url = cite.resolve(citation).url
    page = _artifact(tmp_path, citation, url, "The KL penalty keeps", ref="#s2")
    errors = cite.check([str(page)]).errors
    assert any("#s2 has no source element" in error for error in errors)
    assert any("never referenced" in error for error in errors)


def test_check_fails_a_long_transcript_quote(sha: str, tmp_path: Path) -> None:
    citation = f"yt:{VIDEO}@00:00:30"
    url = cite.resolve(citation).url
    quote = " ".join(["good"] * (cite.TRANSCRIPT_QUOTE_WORD_LIMIT + 1))
    page = _artifact(tmp_path, citation, url, quote)
    assert any("word transcript quote" in error for error in cite.check([str(page)]).errors)


def test_a_clone_without_transcripts_warns_rather_than_fails(sha: str, tmp_path: Path) -> None:
    citation = f"yt:{VIDEO}@00:00:30"
    url = cite.resolve(citation).url
    (cite.TRANSCRIPTS / f"{VIDEO}.md").unlink()
    page = _artifact(tmp_path, citation, url, "good question")
    report = cite.check([str(page)])
    assert report.errors == []
    assert any("no local transcript" in warning for warning in report.warnings)


def test_check_validates_ids_in_markdown_notes(sha: str, tmp_path: Path) -> None:
    note = tmp_path / "note.md"
    note.write_text(f"Good: {_book_id(sha)}\nBad: {_book_id(sha, 'L90')}\n")
    report = cite.check([str(note)])
    assert report.verified == 1
    assert len(report.errors) == 1
    assert ":2:" in report.errors[0]


def test_search_ranks_the_passage_with_the_query_terms_first() -> None:
    passages = [
        cite.Passage("yt", "a", "x", cite._tokens("talk about rewards and data")),
        cite.Passage("yt", "b", "x", cite._tokens("the kl penalty in rlvr is often removed")),
        cite.Passage("yt", "c", "x", cite._tokens("unrelated")),
    ]
    ranked = cite.rank("rlvr kl penalty", passages)
    assert [passage.id for _, passage in ranked] == ["b"]
