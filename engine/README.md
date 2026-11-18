# shellslatee-engine

Point it at a folder. Get a course.

Turns a folder of videos into a mirrored, linked vault of Markdown study notes:
crawl → transcribe (whisper.cpp) → structured notes via any OpenAI-compatible
model → index → cards → quiz → course-wide cited answers.

This tree is byte-for-byte the shipped `shellslatee_engine-0.2.0` wheel plus the
0.2.1 fixes recorded in `../tracking.md` (natural-language search, timestamped
citations, concept pruning, `concept_pages` crash). It is vendored here because
the engine repository is not public: see defect D3.

```bash
python -m pip install -e .[dev]
python -m unittest discover -s tests
shellslatee doctor
```

The desktop shell in the parent directory bundles a built wheel from this tree.
