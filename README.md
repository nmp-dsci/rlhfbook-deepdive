# rlhfbook-deepdive

My learning scratch pad for [Reinforcement Learning from Human Feedback](https://rlhfbook.com/) and
[Nathan Lambert's YouTube channel](https://www.youtube.com/@natolambert). I go through the book
chapter by chapter and ask questions, and a coding agent answers from Lambert's own material with a
link to the exact passage behind every claim.

**This is an unofficial personal project, not affiliated with or endorsed by Nathan Lambert.** For
the real thing, read [the book](https://rlhfbook.com/), take
[the course](https://rlhfbook.com/course), or
[buy a copy](https://www.manning.com/books/reinforcement-learning-from-human-feedback).

## How it works

- **The book** is a [git submodule](sources/rlhf-book) pinned to one commit, so line numbers do not
  drift while he keeps editing.
- **Transcripts** live in my
  [transcript-rag-agent](https://github.com/nmp-dsci/transcript-rag-agent) store. This repo exports a
  local copy and commits only [a catalogue](sources/catalog.json) of facts and hashes.
- **[`scripts/cite.py`](scripts/cite.py)** searches both and verifies citations.
  `make check` fails if a quote is not in the passage it cites.
- **[`.lavish/`](.lavish)** holds the answers as HTML pages, reviewed with
  [Lavish](https://www.npmjs.com/package/lavish-axi). Book citations open the exact lines at the
  pinned commit, and video citations open at the second.
- **[`AGENTS.md`](AGENTS.md)** is the rulebook, so any coding agent can do this the same way.

Start with [the course map](.lavish/s00_course-map.html), or see
[a worked answer](.lavish/s01_q-rlvr-kl-penalty.html). GitHub shows these as source, so clone the
repo to read them rendered.

## Setup

```bash
git clone --recurse-submodules --shallow-submodules https://github.com/nmp-dsci/rlhfbook-deepdive
cd rlhfbook-deepdive
make setup
make transcripts   # needs a local transcript-rag-agent store
make check
```

Without the transcript store, book search and citations still work. Transcript citations are checked
against the catalogue only, and `make check` reports them as warnings. `make help` lists the commands.

## Licence and attribution

The book, slides and reference code are © Nathan Lambert and are not copied here. The submodule only
points at [natolambert/rlhf-book](https://github.com/natolambert/rlhf-book).

- **Notes and pages** (`notes/`, `.lavish/*.html`, `templates/`) adapt the book, so they are under
  [CC BY-NC-SA 4.0](LICENSE), the book's own licence. Attribution: Nathan Lambert, *Reinforcement
  Learning from Human Feedback*.
- **Scripts and tests** are [MIT](LICENSE-CODE).
- **`.lavish/fonts/`** is IBM Plex under the [SIL OFL 1.1](.lavish/fonts/LICENSE).
- **Video transcripts** are not licensed for redistribution as far as I can tell, so they are not
  committed. Pages quote at most 60 words at a time and link to the video.
