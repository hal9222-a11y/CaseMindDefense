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

## Remaining in v0.13

- Hebrew NER (DictaBERT) replacing regex entities
- Contradiction engine (semantic pairing + NLI/LLM verdict)
- Entity graph view
- Desktop: show answer mode/model in the AI page
