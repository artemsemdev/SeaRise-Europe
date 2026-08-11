# Settlement search engine evaluation foundation

This foundation compares MiniSearch 7.2.0 and FlexSearch 0.8.212 without
selecting either engine. It defines synthetic contract and adapter evidence
only. It does not measure production quality, browser latency, compressed
size, or worker memory, and it does not change settlement v3 serialization.

## Contracts and invariants

`contracts/search-evaluation/v1` defines reviewed query expectations and the
future production report shape. JSON Schema is paired with executable semantic
validation for unique and sorted identifiers, known-gap references, exact
engine order and versions, corpus arithmetic, metric nullability, fixture
hashes, and hash-bound adapter evidence. Reports always keep engine selection
`deferred`.

Both adapters use the same normalized document text and private dense numeric
ordinals. Public place identity remains the stable source ID. Shared ranking
orders canonical, alternate, prefix, and bounded fuzzy matches before
population, administrative importance, coastal distance, and the numeric ID
suffix. Normalization rejects controls and unpaired UTF-16, folds diacritics,
and computes edit distance over Unicode code points. Transliteration comes
only from supplied aliases.

Serialized test indexes bind their exact engine and package, adapter options,
evaluation and shard IDs, document count, and document SHA-256. Deserialization
rejects unknown envelope fields, invalid UTF-8, identity drift, corpus drift,
MiniSearch serialization drift, and changed FlexSearch chunk order or set
before invoking the package importer.

## Local validation

Install the exact lock and run the synthetic suite:

```bash
cd src/frontend
npm ci
npm test -- src/search/evaluation
npm run type-check
```

Production ingestion is deliberately absent from this foundation, so there is
no fixture fallback or command that can be mistaken for production validation.
The follow-up production benchmark must add fail-closed shard validation and
receipt binding, bind complete deterministic inputs, replace `not-measured`
values with real browser evidence, and retain `selection.status = deferred`.
A later reviewed PR may freeze one engine in a successor settlement format and
integrate it into the dedicated Web Worker.
