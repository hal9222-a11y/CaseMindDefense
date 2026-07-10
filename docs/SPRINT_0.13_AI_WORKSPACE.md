# Sprint 0.13 — AI Investigation Workspace (MVP)

## Goal

`/ai/ask` returns a real answer synthesized by a **local** LLM, grounded
only in stored evidence, with citation markers — or degrades to
citation-only mode when no LLM is available.

## Delivered (part 1 — RAG core)

- `llm_service`: Ollama HTTP client (`CASEMIND_OLLAMA_URL`,
  `CASEMIND_LLM_MODEL`, `CASEMIND_LLM_TIMEOUT`); availability probe;
  answer synthesis with a hard evidence-only prompt (per-claim `[n]`
  markers, `NOT_FOUND` contract, question-language pinning for small
  models); artifact cleanup (bad markers, hallucinated citation indices,
  latin junk glued to Hebrew)
- `answer_with_evidence`: retrieval → LLM synthesis when available →
  response carries `mode` (`llm` / `citations_only` / `none`) and
  `model`; **any** LLM failure falls back to citation-only, never errors
- Default model: `qwen2.5:3b-instruct` — best Hebrew at a size that fits
  a 4 GB GPU; beat `llama3.2:3b` head-to-head on a real Hebrew case
  question. Stronger hardware → set `CASEMIND_LLM_MODEL`.

## Verified

- 30/30 tests ×2 (LLM paths covered with monkeypatched synthesis; the
  citations-only fallback is what CI exercises — no Ollama needed)
- Live E2E on a real Hebrew court document: Hebrew question → Hebrew
  answer grounded in the indictment response, citations [1]-[4]

## Delivered (part 2 — bilingual embeddings)

- Default model `intfloat/multilingual-e5-small` with `query:`/`passage:`
  prefixes; model-name mismatch guard in semantic search (MiniLM and e5
  are both 384-d — dimension checks cannot catch cross-space mixing)
- Verified live after full reindex: Hebrew query matched English
  evidence at 0.86 cosine

## Delivered (part 3 — Hebrew NER)

- `ner_service`: DictaBERT (`dicta-il/dictabert-ner`, env-overridable)
  at index time; entities stored per chunk in `extractedentity`;
  deterministic patterns (phone/ID/plate) always included; full regex
  fallback when the model is missing (CI needs no model)
- `/entities` aggregates the table (SQL GROUP BY) with a legacy scan
  fallback for pre-NER data; reindex replaces an evidence's entities
- Live on the real court document: the defendant and witnesses
  identified as persons, Tel Aviv as location, times/phones/plates typed
- Known quirks for later: subword-truncated names, prepositions glued
  to locations (strip ב/ל prefixes)

## Delivered (part 4 — contradiction engine)

- Candidate pairs: cosine ≥ threshold (env-tunable) across different
  evidence, capped chunks/pairs (O(n²) documented ceiling — sqlite-vec
  KNN when corpora grow); LLM verdict drops consistent pairs and
  explains contradictions; `unverified` mode without Ollama
- Live catch: two witness statements disagreeing on the car color were
  flagged with the correct explanation ("The car colors are different")
- Known limits (3B model): occasional false positives on metadata-only
  differences; explanations kept in English (Hebrew pinning produced
  mixed-script output) — larger CASEMIND_LLM_MODEL improves both

## Delivered (part 5 — graph, case picker, AI mode)

- `/entities/graph`: co-occurrence graph (top-N entities, edge weight =
  shared evidence count); desktop Entity Graph page renders it in a
  QGraphicsScene circle layout (size = mentions, color = type,
  double-click = search occurrences)
- Case picker in the Evidence toolbar: filter by case, import into the
  selected case, create cases inline
- AI page shows the answer mode (LLM model name / citations-only)

**v0.13 scope complete.** Next: run the MVP acceptance test — a real
case folder end to end — then v0.14 (reporting).
