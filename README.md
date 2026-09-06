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

## Demo

`demo/` is the same assistant without a server: the real corpus already indexed (6
documents, 1809 chunks) and the answers the local model produced. The lexical search, the
ambiguity detection and the data verifier run in the visitor's browser, identical to the
server; the semantic half and the writing need the local models, which is exactly what the
page says. Deploy with `cd demo && vercel --prod`. See [`demo/README.md`](demo/README.md).

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
| factual_lookup | 15 | 1.00 | 0.73 | 0.79 (11/14) | **1.00 (15/15)** |
| alfanumerico_exacto | 8 | 1.00 | 1.00 | 1.00 (6/6) | 1.00 (8/8) |
| procedimental | 7 | 0.86 | 0.79 | 1.00 (5/5) | 1.00 (7/7) |
| **negative control** | 9 | n/a | n/a | 0.50 (1/2) | **0.78 (7/9)** |

**What the measurement found, stated rather than hidden:**

- **It used to stay quiet too often — fixed, and the fix cost something.** Abstention on
  `factual_lookup` was `0.73`: it declined on 4 of 15 questions the documentation does
  answer. All four were the deterministic ambiguity detector misfiring, not the model. It is
  now `1.00`. **The same change moved negative-control abstention from `0.89` to `0.78`**,
  and that trade is explained below — it is not a wash.
- **It answers from the wrong row.** Asked how long the *M9* bayonet blade is, it answers
  `8 in. (20.32 cm)` — the *OKC-3S* blade. The right answer, 7 in. / 17.78 cm, is in the same
  manual. The golden set lists `20.32` as a forbidden number for that question precisely to
  catch this, and it does.
- **It hallucinates on 2 of 9 negative controls.** Asked for the NSN of a bottle size that
  does not exist, it returns `9150-00-889-3522` — a real NSN from the document, for a
  different item. Same defect as above: a value that exists, from the wrong row.
- **Quality tracks the document.** An old blurry scan does worse than a native PDF.

**Why the negative-control number went down, honestly.** Both wrong answers above were
previously hidden: the system refused those questions, so it never got to be wrong out loud.
It refused them because the ambiguity detector was reading a parts list out of the PDF as if
it were a lookup table and asking *"which (1) item no.?"* with `['', '1']` as the options —
a question nobody can answer. Removing that removed an accidental gag, not a safeguard: the
wrong answers were always what the system would have said. `0.89` was partly earned by a
bug, and a number earned by a bug is worth less than a lower number that is true.

The remaining defect is one defect, not two: **the generator picks a value from a row that
does not match the entity in the question.** That is the same failure the deterministic
ambiguity detector already handles for markdown tables, and it needs the equivalent for
prose and for parts lists. It is the next thing to fix, and it is measured.

**A third instance of it, found and fixed.** The semantic cache served `$249 one-off` — the
*Lifetime* price — to someone asking about the *Single* plan, at 81% similarity and labelled
"already verified". A cache hit requires cosine ≥ 0.80 **and** an identical set of technical
terms, and that second condition was designed against M24 grade 8.8 vs 10.9 — pairs told
apart by a code. Neither pricing question contains a code, so both term sets were empty,
two empty sets are equal, and the guard passed without deciding anything: **vacuous exactly
where cosine is least trustworthy.** Proper nouns and acronyms now count as terms, so
`Single` ≠ `Lifetime` while *"how much is the Single plan"* and *"price of the Single plan"*
still match — which is what a cache is for.

**The metrics are stable, the wording is not.** Two independent runs eight minutes apart
differ textually in 38 of the 39 answers — the local model is not deterministic — and produce
**exactly the same table**. What is being measured survives the rewording, which is the
property that makes a change in this table mean a change in the system.

One detail worth keeping: the first reading gave `grounded 0.18`, and it was **false**.
shopfloor answers with citation markers (`720 +/- 30 N.m [1]`) and the harness read that
`[1]` as a number needing grounding — it was penalising the system **for citing properly**.
The harness was fixed, not the golden set; the answers were already correct.

## The gate

```bash
./scripts/eval.sh                 # measure and compare against eval/baseline.json
./scripts/eval.sh --rebaseline    # accept the current run as the new floor
```

Exit codes come straight from `groundcheck gate`: **0** pass · **1** regression · **2** could
not compare (the golden set moved, or `k` changed). Proven to work rather than assumed: fed
the pre-fix run, it exits 1 and names the three metrics that fell.

**It does not run in GitHub CI, on purpose.** The answers come from a local Qwen, and a
hosted runner has no GPU to hold it. An eval there would measure a stand-in — a gate on
something that never ships, which is worse than no gate because it reads like one. So the
gate runs where the model lives, and CI checks the part that needs no model: that
`eval/baseline.json` still names the golden set it was measured against, byte for byte, and
that it carries real numbers. A baseline that has drifted from its set compares nothing, and
one full of zeros can never fail.

## Attribution

See `CONTEXTO-SHOPFLOOR.md` §7.1: `microsoft/markitdown` (MIT) was evaluated and measured
before choosing `docling`. No markitdown code is incorporated in this repo.
