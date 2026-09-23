# Zafar Yaqoob Bedding Store Knowledge Assistant

A bilingual retrieval system over Zafar Yaqoob Bedding Store's own content. It answers customer and internal questions about bedding and home textiles (bed sheets, razai and razai covers, gadda, pillows, blankets, mattress and sofa covers, curtains, jae namaz and dasterkhawan), orders, shipping and store policy in English, Urdu and Roman Urdu, and every answer cites the document it came from.

## Why it exists

Zafar Yaqoob Bedding Store receives the same questions every day across three written forms: English, Urdu script, and Urdu written in Latin letters. Answers live scattered across product pages, a returns policy, shipping tables and <NUMBER> months of past support conversations. Three things make this harder than a document search box:

- The catalog changes daily, so an answer that was correct last week can be wrong today.
- Customers ask about their own orders, so some answers are visible to exactly one person.
- Roman Urdu has no fixed spelling ("razai", "rajai", "rezai"), which defeats keyword matching and most models trained on formal text.

## How it works

1. Content syncs from store sources on a schedule, processing only what changed.
2. Documents are parsed, split into chunks, and tagged with source, type and language.
3. Chunks are indexed for both semantic and keyword search.
4. A question retrieves through both indexes, filtered by metadata and by what the asker is permitted to see.
5. Candidates are reranked for relevance.
6. An answer is generated strictly from the retrieved chunks, with citations to exact source spans — or the system states that it does not have the information.

## What it does not do

- It does not answer from the model's general knowledge. If the answer is not in the corpus, it says so.
- It does not show any customer another customer's data. Permissions are applied before retrieval, not after.
- It does not treat retrieved content as instructions.
- It is not a general assistant, and it does not replace the support team.

## Quality

Every change is measured against a fixed 90-question evaluation set covering English, Urdu script, Roman Urdu, cross-lingual, multi-document and unanswerable questions. Regressions block merges.

| Configuration | Hit rate@5 | Recall@5 | MRR |
|---|---|---|---|
| Baseline — fixed chunking, single embedding model | — | — | — |

Full results and the reasoning behind each choice are in `DECISIONS.md`.

## Stack

Provisional. Every component here is a candidate, not a commitment — choices are made by measurement against the evaluation set and recorded in `DECISIONS.md`.

- Language: Python
- Embeddings: <TBD — benchmarked in Phase 1>
- Vector store: <TBD>
- Lexical search: <TBD>
- Evaluation: custom retrieval metrics, extended in Phase 1

## Status

Phase 0 — evaluation harness and baseline. See `docs/design.md` for the architecture and open questions.
