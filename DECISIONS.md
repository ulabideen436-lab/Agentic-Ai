### [NNN] <Decision title>
**Date:** YYYY-MM-DD
**Phase:** <0–6>
**Status:** proposed | active | superseded by [NNN]

**Context**
What problem forced a decision. The constraints that were real at the time —
corpus size, time, cost, what you did and didn't know yet.

**Options considered**
1. <Option> — pro / con
2. <Option> — pro / con
3. <Option> — pro / con

**Decision**
What you chose. One or two sentences.

**Reasoning**
Why this one. Name the tradeoff you accepted, not just the benefit you gained.

**Measured result**
Metric, before, after, and which eval set. If not yet measured, write
"not yet measured" and a date to revisit.

**What I'd revisit**
The conditions under which this becomes the wrong choice.



[001] Baseline retrieval configuration

Date: <2026-09-23> Phase: 0 Status: active

Context Needed a fixed reference point before any optimization work. Every later change in retrieval has to be measured against something, and without a baseline no improvement claim can be checked. Corpus at this point is <N> documents; evaluation set is 90 questions across six categories.

Options considered

Start directly with a vector database — closer to the eventual system, but adds tooling I don't yet understand to the thing being measured.
Brute-force similarity search in numpy — trivial to write, fully understood, and fast enough at this corpus size.
Use an off-the-shelf RAG framework — fastest to stand up, but hides the retrieval behaviour I specifically need to see.

Decision Option 2. Fixed 200-word chunks with 40-word overlap, <MODEL_NAME> embeddings, cosine similarity over normalized vectors, top-5 retrieval.

Reasoning A baseline should measure the corpus and the evaluation set, not the tooling. Accepted that brute force does not scale, in exchange for a result I can fully explain and a codebase with no hidden behaviour.

Measured result Hit rate@5: <x> · Recall@5: <x> · MRR: <x> Worst category: <category> at <x>. Measured on the 90-question evaluation set, <date>.

What I'd revisit Brute force stops being practical once the corpus outgrows memory. The chunking and embedding choices here are placeholders — both are decided properly in Phase 1 and will supersede this entry.