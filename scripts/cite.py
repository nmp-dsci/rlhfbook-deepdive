#!/usr/bin/env python3
"""Find, resolve and verify citations into Nathan Lambert's material. Standard library only.

  cite.py search "why does RLVR omit the KL penalty?"   ranked passages with ready-made ids
  cite.py resolve <id>                                  the link and exact text behind an id
  cite.py check [paths]                                 verify every citation in artifacts and notes

Citation ids (the grammar is documented in AGENTS.md):

  book@<40-char sha>:<path in rlhf-book>#L<start>[-L<end>]     chapters, slides and code
  yt:<video id>@<HH:MM:SS>[-<HH:MM:SS>]                        transcripts

A book id names its commit, so it stays checkable after the pin moves. A transcript id is checked
against the local export when there is one; on a fresh clone it can only be checked against the
catalogue, which is reported as a warning.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import subprocess
import sys
from collections import Counter
from collections.abc import Iterable, Iterator, Sequence
from dataclasses import dataclass, field
from functools import cache
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
BOOK = ROOT / "sources" / "rlhf-book"
TRANSCRIPTS = ROOT / "sources" / "transcripts"
CATALOG = ROOT / "sources" / "catalog.json"
COURSE_MAP = ROOT / "sources" / "course-map.json"
BOOK_REPO_URL = "https://github.com/natolambert/rlhf-book"
BOOK_SITE_URL = "https://rlhfbook.com/c"

BOOK_ID = re.compile(
    r"book@(?P<sha>[0-9a-f]{40}):(?P<path>[^#\s\"'<>]+)#L(?P<start>\d+)(?:-L(?P<end>\d+))?"
)
YT_ID = re.compile(
    r"yt:(?P<video>[\w-]{11})@(?P<start>\d\d:\d\d:\d\d)(?:-(?P<end>\d\d:\d\d:\d\d))?"
)
BLOCK_LINE = re.compile(r"^\[(\d\d:\d\d:\d\d)\] (.*)$")

#: The repo is public and transcripts carry no licence, so a quote stays short. See AGENTS.md.
TRANSCRIPT_QUOTE_WORD_LIMIT = 60
SKIPPED_NAMES = {"AGENTS.md", "CLAUDE.md", "CHANGELOG.md", "CONTRIBUTING.md", "lec9-plan.md"}
MIN_PASSAGE_WORDS = 40
TRANSCRIPT_WINDOW_BLOCKS = 3


class CitationError(ValueError):
    """A citation that does not parse or does not resolve."""


@dataclass(frozen=True)
class Source:
    """What a citation points at."""

    id: str
    url: str
    label: str
    text: str | None  # None: a transcript that has not been exported on this machine
    read_url: str | None = None


# ---- book ---------------------------------------------------------------------------------------


def _git_book(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["git", "-C", str(BOOK), *args], capture_output=True, text=True)


def pinned_sha() -> str:
    result = _git_book("rev-parse", "HEAD")
    if result.returncode != 0:
        raise CitationError(f"{BOOK} is not checked out; run: make setup")
    return result.stdout.strip()


@cache
def _book_lines(sha: str, path: str) -> tuple[str, ...]:
    """A file's lines at a commit, fetching the commit if an older pin is no longer local."""
    if _git_book("cat-file", "-e", f"{sha}^{{commit}}").returncode != 0:
        _git_book("fetch", "--depth", "1", "origin", sha)
    shown = _git_book("show", f"{sha}:{path}")
    if shown.returncode != 0:
        raise CitationError(f"{path} does not exist at {sha[:12]}")
    return tuple(shown.stdout.splitlines())


def _headings(lines: Sequence[str]) -> Iterator[tuple[int, int, str]]:
    """(line number, level, text) of every markdown heading outside a code fence."""
    fenced = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced and (match := re.match(r"^(#{1,6})\s+(.+?)\s*$", line)):
            yield number, len(match.group(1)), match.group(2)


def _slug(heading: str) -> str:
    """Pandoc's automatic heading id, which rlhfbook.com uses."""
    text = re.sub(r"[^\w\s-]", "", heading.lower())
    return re.sub(r"\s+", "-", text.strip())


def _book_label(path: str, lines: Sequence[str], start: int) -> tuple[str, str | None]:
    """A human label for a position in the book repo, and its section on the book site."""
    before = [(level, text) for number, level, text in _headings(lines) if number <= start]
    section = before[-1][1] if before else None
    name = Path(path).name
    if path.startswith("book/chapters/") and name.endswith(".md"):
        title = next((text for _, level, text in _headings(lines) if level == 1), Path(path).stem)
        if match := re.match(r"(\d\d)-", name):
            head = f"Ch. {int(match.group(1))} {title}"
        elif match := re.match(r"appendix-([a-z])-", name):
            head = f"Appendix {match.group(1).upper()} {title}"
        else:
            head = title
        anchor = f"#{_slug(section)}" if section else ""
        label = head if section in (None, title) else f"{head} § {section}"
        return label, f"{BOOK_SITE_URL}/{Path(path).stem}{anchor}"
    if path.startswith("teach/"):
        label = f"Slides {Path(path).stem}"
        return (f"{label} § {section}" if section else label), None
    return f"Code {path}" if path.startswith("code/") else path, None


def _book_source(match: re.Match[str]) -> Source:
    sha, path = match["sha"], match["path"]
    start = int(match["start"])
    end = int(match["end"] or start)
    lines = _book_lines(sha, path)
    if not 1 <= start <= end <= len(lines):
        raise CitationError(f"{match[0]}: {path} has {len(lines)} lines at that commit")
    span = f"L{start}" if start == end else f"L{start}-L{end}"
    plain = "?plain=1" if path.endswith(".md") else ""
    anchor = f"#L{start}" if start == end else f"#L{start}-L{end}"
    label, read_url = _book_label(path, lines, start)
    return Source(
        id=match[0],
        url=f"{BOOK_REPO_URL}/blob/{sha}/{path}{plain}{anchor}",
        label=f"{label} ({span})",
        text="\n".join(lines[start - 1 : end]),
        read_url=read_url,
    )


# ---- transcripts --------------------------------------------------------------------------------


@cache
def catalog() -> dict[str, dict[str, Any]]:
    if not CATALOG.exists():
        return {}
    return {entry["video_id"]: entry for entry in json.loads(CATALOG.read_text())}


def _seconds(stamp: str) -> int:
    hours, minutes, seconds = (int(part) for part in stamp.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _stamp(seconds: float) -> str:
    whole = int(seconds)
    return f"{whole // 3600:02d}:{whole % 3600 // 60:02d}:{whole % 60:02d}"


def _transcript_blocks(video: str) -> list[tuple[int, str]] | None:
    path = TRANSCRIPTS / f"{video}.md"
    if not path.exists():
        return None
    found = (BLOCK_LINE.match(line) for line in path.read_text().splitlines())
    return [(_seconds(match[1]), match[2]) for match in found if match]


def _yt_source(match: re.Match[str]) -> Source:
    video = match["video"]
    entry = catalog().get(video)
    if entry is None:
        raise CitationError(f"{match[0]}: {video} is not in sources/catalog.json")
    start = _seconds(match["start"])
    end = _seconds(match["end"]) if match["end"] else start + 1
    if end <= start:
        raise CitationError(f"{match[0]}: the range ends before it starts")
    if start > entry["duration_seconds"]:
        raise CitationError(f"{match[0]}: the video is {_stamp(entry['duration_seconds'])} long")
    text = None
    if (blocks := _transcript_blocks(video)) is not None:
        chosen = [
            body
            for index, (at, body) in enumerate(blocks)
            if at < end and (index + 1 == len(blocks) or blocks[index + 1][0] > start)
        ]
        if not chosen:
            raise CitationError(f"{match[0]}: no transcript at that time")
        text = " ".join(chosen)
    return Source(
        id=match[0],
        url=f"https://www.youtube.com/watch?v={video}&t={start}s",
        label=f"{entry['title']} @ {match['start']}",
        text=text,
    )


def resolve(citation: str) -> Source:
    if match := BOOK_ID.fullmatch(citation):
        return _book_source(match)
    if match := YT_ID.fullmatch(citation):
        return _yt_source(match)
    raise CitationError(f"not a citation id: {citation!r}")


# ---- search -------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Passage:
    kind: str
    id: str
    text: str
    tokens: tuple[str, ...] = field(default=(), compare=False)


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(re.findall(r"[a-z0-9]+", text.lower()))


def _split_markdown(lines: Sequence[str]) -> Iterator[tuple[int, int]]:
    """1-based line spans cut at blank lines outside code fences, merged to a useful size."""
    start: int | None = None
    words = 0
    fenced = False
    for number, line in enumerate(lines, 1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        if line.strip() or fenced:
            start = start or number
            words += len(line.split())
        elif start is not None and words >= MIN_PASSAGE_WORDS:
            yield start, number - 1
            start, words = None, 0
    if start is not None:
        yield start, len(lines)


def _kind_of(path: str) -> str | None:
    name = Path(path).name
    if name in SKIPPED_NAMES or ".claude/" in path:
        return None
    if path.startswith("book/chapters/") and name.endswith(".md"):
        return "book"
    if path.startswith("teach/") and name.endswith(".md") and name != "README.md":
        return "slides"
    if path.startswith("code/") and name.endswith((".py", ".md")):
        return "code"
    return None


def _book_passages(sha: str) -> Iterator[Passage]:
    listing = _git_book("ls-tree", "-r", "--name-only", sha).stdout.splitlines()
    for path in listing:
        kind = _kind_of(path)
        if kind is None:
            continue
        lines = _book_lines(sha, path)
        for start, end in _split_markdown(lines):
            text = "\n".join(lines[start - 1 : end])
            span = f"L{start}" if start == end else f"L{start}-L{end}"
            yield Passage(kind, f"book@{sha}:{path}#{span}", text, _tokens(text))


def _transcript_passages() -> Iterator[Passage]:
    for video in catalog():
        blocks = _transcript_blocks(video) or []
        for index in range(0, len(blocks), TRANSCRIPT_WINDOW_BLOCKS - 1):
            window = blocks[index : index + TRANSCRIPT_WINDOW_BLOCKS]
            after = index + TRANSCRIPT_WINDOW_BLOCKS
            end = blocks[after][0] if after < len(blocks) else window[-1][0] + 30
            text = " ".join(body for _, body in window)
            citation = f"yt:{video}@{_stamp(window[0][0])}-{_stamp(end)}"
            yield Passage("yt", citation, text, _tokens(text))


def _asked_passages() -> Iterator[Passage]:
    """Reader questions Lambert answered on video: the course page timestamps each one."""
    if not COURSE_MAP.exists():
        return
    for question in json.loads(COURSE_MAP.read_text())["questions"]:
        citation = f"yt:{question['video_id']}@{_stamp(question['seconds'])}"
        yield Passage("asked", citation, question["question"], _tokens(question["question"]))


def rank(query: str, passages: Sequence[Passage], k1: float = 1.5, b: float = 0.75) -> list[Any]:
    """BM25 over passages, best first: deterministic, no index on disk, no model."""
    terms = set(_tokens(query))
    total = len(passages) or 1
    average = sum(len(p.tokens) for p in passages) / total or 1.0
    frequency: Counter[str] = Counter()
    for passage in passages:
        frequency.update(terms & set(passage.tokens))
    scored = []
    for passage in passages:
        counts = Counter(token for token in passage.tokens if token in terms)
        score = 0.0
        for term, count in counts.items():
            idf = math.log(1 + (total - frequency[term] + 0.5) / (frequency[term] + 0.5))
            norm = 1 - b + b * len(passage.tokens) / average
            score += idf * count * (k1 + 1) / (count + k1 * norm)
        if score > 0:
            scored.append((score, passage))
    scored.sort(key=lambda pair: (-pair[0], pair[1].id))
    return scored


def _search(query: str, kinds: Iterable[str], per_kind: int) -> int:
    passages = [*_asked_passages(), *_book_passages(pinned_sha()), *_transcript_passages()]
    ranked = rank(query, passages)
    for kind in kinds:
        hits = [pair for pair in ranked if pair[1].kind == kind][:per_kind]
        print(f"\n== {kind} ({len(hits)})")
        for score, passage in hits:
            source = resolve(passage.id)
            snippet = " ".join(passage.text.split())[:280]
            print(f"\n[{score:.1f}] {source.label}\n  {passage.id}\n  {snippet}")
    if not any(p.kind == "yt" for p in passages):
        print("\nNo transcripts exported on this machine. Run: make transcripts", file=sys.stderr)
    return 0


# ---- check --------------------------------------------------------------------------------------


def normalise(text: str) -> str:
    """Compare words, not markup: pandoc citations, punctuation and case are not evidence."""
    text = re.sub(r"\[@[^\]]*\]", " ", text)
    return " ".join(re.sub(r"[\W_]+", " ", text.lower()).split())


def quote_matches(quote: str, source_text: str) -> bool:
    """True when the quote's parts, split at an ellipsis, appear in order in the source."""
    haystack = f" {normalise(source_text)} "
    position = 0
    parts = [normalise(part) for part in re.split(r"…|\[\.\.\.\]|\.\.\.", quote)]
    parts = [part for part in parts if part]
    if not parts:
        return False
    for part in parts:
        found = haystack.find(f" {part} ", position)
        if found < 0:
            return False
        position = found + len(part) + 1
    return True


@dataclass
class _SourceElement:
    cite: str
    line: int
    element_id: str | None
    tag: str
    depth: int = 1
    hrefs: list[str] = field(default_factory=list)
    quote: list[str] = field(default_factory=list)


class _ArtifactParser(HTMLParser):
    """Collects each [data-cite] element and every in-page reference to a source."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.sources: list[_SourceElement] = []
        self.references: set[str] = set()
        self.scripts: set[str] = set()
        self._open: _SourceElement | None = None
        self._quote_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        if tag == "script" and (src := values.get("src")):
            self.scripts.add(src)
        href = values.get("href")
        if tag == "a" and href and re.fullmatch(r"#s\d+", href):
            self.references.add(href[1:])
        if self._open is None:
            if cite := values.get("data-cite"):
                self._open = _SourceElement(cite, self.getpos()[0], values.get("id"), tag)
                self.sources.append(self._open)
            return
        if tag == self._open.tag:
            self._open.depth += 1
        if tag == "blockquote":
            self._quote_depth += 1
        if tag == "a" and href:
            self._open.hrefs.append(href)

    def handle_endtag(self, tag: str) -> None:
        if self._open is None:
            return
        if tag == "blockquote" and self._quote_depth:
            self._quote_depth -= 1
        if tag == self._open.tag:
            self._open.depth -= 1
            if self._open.depth == 0:
                self._open = None

    def handle_data(self, data: str) -> None:
        if self._open is not None and self._quote_depth:
            self._open.quote.append(data)


@dataclass
class Report:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    verified: int = 0


def _check_artifact(path: Path, report: Report) -> None:
    parser = _ArtifactParser()
    parser.feed(path.read_text())
    if "page.js" not in parser.scripts:
        report.errors.append(f"{path}: must load page.js, or its links do nothing inside Lavish")
    ids = {source.element_id for source in parser.sources}
    for reference in sorted(parser.references - ids):
        report.errors.append(f"{path}: #{reference} has no source element")
    for element in parser.sources:
        where = f"{path}:{element.line}"
        try:
            source = resolve(element.cite)
        except CitationError as error:
            report.errors.append(f"{where}: {error}")
            continue
        if element.element_id not in parser.references:
            report.errors.append(f"{where}: source is never referenced in the page")
        if source.url not in element.hrefs:
            report.errors.append(f"{where}: must link to {source.url}")
        quote = " ".join(" ".join(element.quote).split())
        if not quote:
            report.errors.append(f"{where}: source has no <blockquote> to review")
            continue
        words = len(quote.split())
        if element.cite.startswith("yt:") and words > TRANSCRIPT_QUOTE_WORD_LIMIT:
            report.errors.append(
                f"{where}: {words}-word transcript quote; the limit is "
                f"{TRANSCRIPT_QUOTE_WORD_LIMIT} because transcripts are not licensed for this repo"
            )
        if source.text is None:
            report.warnings.append(f"{where}: quote unverified, no local transcript")
        elif quote_matches(quote, source.text):
            report.verified += 1
        else:
            report.errors.append(f"{where}: quote is not in {element.cite}: {quote[:100]!r}")


def _check_markdown(path: Path, report: Report) -> None:
    text = path.read_text()
    for pattern in (BOOK_ID, YT_ID):
        for match in pattern.finditer(text):
            line = text.count("\n", 0, match.start()) + 1
            try:
                resolve(match[0])
                report.verified += 1
            except CitationError as error:
                report.errors.append(f"{path}:{line}: {error}")


def _check_sources(report: Report) -> None:
    """The committed catalogue and course map agree with the book and the local export."""
    known = catalog()
    sha = pinned_sha()
    if COURSE_MAP.exists():
        course_map = json.loads(COURSE_MAP.read_text())
        for entry in [*course_map["course"], *course_map["talks"]]:
            if entry["video_id"] not in known:
                report.errors.append(f"course-map: {entry['video_id']} is not in the catalogue")
            if slides := entry.get("slides"):
                try:
                    _book_lines(sha, slides)
                except CitationError as error:
                    report.errors.append(f"course-map: {error}")
    for video, entry in known.items():
        path = TRANSCRIPTS / f"{video}.md"
        if not path.exists():
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        if digest != entry["transcript_sha256"]:
            report.warnings.append(f"catalogue: {video} differs from export; make transcripts")


def _targets(paths: Sequence[str]) -> list[Path]:
    if paths:
        return [Path(path) for path in paths]
    return sorted((ROOT / ".lavish").glob("s*.html")) + sorted((ROOT / "notes").rglob("*.md"))


def check(paths: Sequence[str] = ()) -> Report:
    report = Report()
    _check_sources(report)
    for path in _targets(paths):
        if path.suffix == ".html":
            _check_artifact(path, report)
        elif path.suffix == ".md":
            _check_markdown(path, report)
    return report


# ---- cli ----------------------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    commands = parser.add_subparsers(dest="command", required=True)
    search = commands.add_parser("search", help="ranked passages with ready-made citation ids")
    search.add_argument("query")
    search.add_argument("-n", "--per-kind", type=int, default=5)
    search.add_argument(
        "--kinds", default="asked,book,yt,slides,code", help="comma-separated, in print order"
    )
    show = commands.add_parser("resolve", help="the link and exact text behind a citation id")
    show.add_argument("citation")
    verify = commands.add_parser("check", help="verify citations in artifacts and notes")
    verify.add_argument("paths", nargs="*")
    args = parser.parse_args(argv)

    if args.command == "search":
        return _search(args.query, args.kinds.split(","), args.per_kind)
    if args.command == "resolve":
        try:
            source = resolve(args.citation)
        except CitationError as error:
            print(error, file=sys.stderr)
            return 1
        print(f"label: {source.label}\nlink:  {source.url}")
        if source.read_url:
            print(f"read:  {source.read_url}")
        print(f"\n{source.text if source.text is not None else '(not exported on this machine)'}")
        return 0

    report = check(args.paths)
    for warning in report.warnings:
        print(f"warn  {warning}")
    for failure in report.errors:
        print(f"FAIL  {failure}")
    print(
        f"{report.verified} citations verified, "
        f"{len(report.warnings)} warnings, {len(report.errors)} errors"
    )
    return 1 if report.errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
