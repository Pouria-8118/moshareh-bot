# Persian Poetry Battle Bot (Moshareh)

A Telegram-based conversational agent implementing *Moshareh* — a traditional Persian literary game in which participants alternately recite poetry couplets, each beginning with the terminal grapheme of the preceding verse.

## Abstract

This project presents an end-to-end pipeline for automated validation and retrieval of Persian poetry couplets in a real-time conversational setting. The system ingests a corpus of 666,000+ couplets sourced from the [Ganjoor](https://ganjoor.net) open digital library, applies a multi-stage Persian NLP normalization pipeline, and employs hybrid exact/fuzzy string matching to validate arbitrary user inputs against the canonical corpus with sub-second latency.

## System Architecture

The system comprises three principal subsystems:

### 1. Data Engineering Pipeline

The raw Ganjoor SQLite database (~140 MB, normalized relational schema) is transformed into a denormalized, query-optimized datastore (~700 MB) through an ETL process that:

- Joins four relational tables (`poet`, `cat`, `poem`, `verse`) into a flat couplet representation
- Resolves hierarchical category trees via recursive parent traversal to extract poet attribution
- Pairs hemistichs (mesra) based on positional encoding (`position` field) and sequential ordering (`vorder`)
- Classifies couplets by terminal-grapheme difficulty for adaptive game balancing

### 2. NLP Normalization Pipeline

User inputs undergo a multi-layer normalization process before matching:

| Stage | Operation | Tool |
|-------|-----------|------|
| 1 | Persian text normalization (half-spaces, Arabic→Persian glyph unification) | [Hazm](https://github.com/sobhe/hazm) Normalizer |
| 2 | Diacritics & harakat removal | Custom regex (Unicode ranges U+064B–U+065F, U+0610–U+061A) |
| 3 | Canonical grapheme mapping | Custom lookup table (28 variant→canonical mappings) |
| 4 | Whitespace normalization & ZWNJ handling | Custom pipeline |
| 5 | SHA-256 hash generation (normalized + space-stripped) | hashlib |

This pipeline ensures that orthographic variations common in informal Persian typing (e.g., omitted half-spaces, Arabic yeh/kaf variants, missing diacritics) do not impede correct matching.

### 3. Hybrid Matching Engine

Validation follows a two-phase retrieval strategy:

**Phase 1 — Exact Match (O(1)):**
The normalized and space-stripped SHA-256 hashes of the user input are compared against precomputed indices. This resolves the majority of well-formed inputs in constant time.

**Phase 2 — Fuzzy Match (constrained search):**
If exact matching fails, the engine retrieves a candidate set filtered by:
- Required initial grapheme (mandatory constraint)
- Character-count proximity window (±10, expandable to ±30)

Candidates are then scored using [RapidFuzz](https://github.com/maxbachmann/RapidFuzz) with three complementary metrics:
- Levenshtein-based simple ratio
- Space-stripped sequence ratio
- Token-sort ratio (order-independent word overlap)

The maximum score across all metrics is compared against a configurable acceptance threshold (default: 82%).

## Technical Stack

| Component | Technology |
|-----------|------------|
| Runtime | Python 3.10+ |
| Bot Framework | [python-telegram-bot](https://python-telegram-bot.org/) v21+ (async, JobQueue) |
| Persian NLP | [Hazm](https://github.com/sobhe/hazm) (Normalizer, WordTokenizer) |
| Fuzzy Matching | [RapidFuzz](https://github.com/maxbachmann/RapidFuzz) (C++-accelerated) |
| Database | SQLite3 with composite indices |
| Deployment | Railway (Nixpacks builder) |

## Corpus Statistics

| Metric | Value |
|--------|-------|
| Total couplets | 666,019 |
| Unique poets | 50+ |
| Source poems | 100,000+ |
| Normalization version | 1.0 (Hazm + custom) |
| Database size (optimized) | ~700 MB |

## Acknowledgments

The poetry corpus is derived from the [Ganjoor](https://github.com/ganjoor) open-source digital library of Persian literature. This project would not be feasible without the sustained efforts of the Ganjoor team and its community of contributors in digitizing and structuring classical Persian poetry.

Persian linguistic processing is powered by [Hazm](https://github.com/sobhe/hazm), developed by Sobhe. Fuzzy string matching is provided by [RapidFuzz](https://github.com/maxbachmann/RapidFuzz), a high-performance Python library with C++ backend.

## License

This project is released for **educational and research purposes only**. See [LICENSE](LICENSE) for full terms.

- Reading, studying, and drawing inspiration from the codebase: **Permitted**
- Commercial use, verbatim redistribution, or deployment of identical clones: **Prohibited**

If you use concepts from this project in academic or personal work, please cite this repository as a reference.

---

Built for the preservation and interactive engagement with Persian poetic heritage.