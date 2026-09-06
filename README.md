# shopfloor

**An on-prem technical documentation assistant.** It answers questions about a plant's
technical documentation — equipment manuals, WPSs, SOPs, spare-part catalogues — **running
entirely inside the plant, with no internet**, and **no number reaches the user without
having been verified against the source document**.

> *shopfloor* = the plant floor, which is where it runs and who it runs for: maintenance at
> three in the morning, offline, with the equipment manual open.

Measured by [`groundcheck`](https://github.com/gabo5612/groundcheck), a sibling repo — an
evaluation harness whose golden set was frozen in git **before** the first run against this
system existed.

## Run it

```bash
docker-compose up -d                     # Postgres 18 + pgvector, on :5433
.venv/bin/python -m uvicorn shopfloor.api.main:app --host 0.0.0.0 --port 8080
.venv/bin/python -m pytest               # 44 tests
```

| What | URL |
|---|---|
| Query portal (mobile) | `http://<server-ip>:8080/` |
| **Upload panel** | `http://<server-ip>:8080/admin` |
| API docs | `http://<server-ip>:8080/api/docs` |

## Pipeline

`parse/` (docling for PDF, Markdown, page number guaranteed) → `chunk/` (structural) →
`embed/` → `retrieve.py` (hybrid dense + lexical, fused with RRF) → `generate.py` (local
Qwen, answers carry citations) → `verify.py` (deterministic number verifier).

## Status

| Milestone | What it adds | Status |
|---|---|---|
| **M0** | Postgres 18.6 + pgvector 0.8.6, `english`/`spanish`/`arabic` text config | ✅ |
| **M1** | docling and Markdown parsers, guaranteed page + structural chunker | ✅ |
| **M2** | Hybrid retrieval (dense + lexical, RRF) | ✅ |
| **M3** | Generation with citations via local Qwen | ✅ |
| **M4** | Deterministic number verifier | ✅ |
| — | Portal + upload panel, background ingestion | ✅ |

## Measured, not claimed (2026-09-06)

First real measurement, 39 questions, 0 errors. Golden set `shopfloor-v2`, sha256
`d2368396ea6d6304…`, committed before any run against this system existed — the harness
refuses to report if that hash no longer matches the file.

| category | n | recall@5 | MRR | grounded | abstention |
|---|---|---|---|---|---|
| factual_lookup | 15 | 1.00 | 0.73 | 0.82 | 0.73 |
| alfanumerico_exacto | 8 | 1.00 | 1.00 | 1.00 | 1.00 |
| procedimental | 7 | 0.86 | 0.79 | 1.00 | 1.00 |
| **negative control** | 9 | n/a | n/a | — | **0.89 (8/9)** |

**What the measurement found, stated rather than hidden:**

- **It stays quiet too often.** Abstention `0.73` on `factual_lookup` — it declines on 4 of
  15 questions that do have an answer in the documentation.
- **It hallucinates, rarely.** 1 of 9 negative controls — questions whose answer does not
  exist — got an answer instead of a silence.
- **Ranges confuse ambiguity detection.** Asked about *"thickness over 20 mm"* it asks back,
  because both `up to 20` and `over 20` contain the number 20. It prefers asking twice over
  choosing wrong.
- **Quality tracks the document.** An old blurry scan does worse than a native PDF.

**The metrics are stable, the wording is not.** Two independent runs eight minutes apart
(`22:16:32` and `22:24:33`) differ textually in 38 of the 39 answers — the local model is
not deterministic — and produce **exactly the same table**. What is being measured survives
the rewording, which is the property that makes a regression in this table mean something.

One detail worth keeping: the first reading gave `grounded 0.18`, and it was **false**.
shopfloor answers with citation markers (`720 +/- 30 N.m [1]`) and the harness read that
`[1]` as a number needing grounding — it was penalising the system **for citing properly**.
The harness was fixed, not the golden set; the answers were already correct.

## Attribution

See `CONTEXTO-SHOPFLOOR.md` §7.1: `microsoft/markitdown` (MIT) was evaluated and measured
before choosing `docling`. No markitdown code is incorporated in this repo.
