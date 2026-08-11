# Settlement search projection

`searise_pipeline.settlements.search_projection` converts one verified spatial-stage DuckDB database and its canonical receipt into a bounded-memory NDJSON artifact for a static browser search worker. It is a serializer and validator only: it does not publish an artifact, select a browser search engine, benchmark browser behavior, or make production, scientific, owner, hazard, canonical-geometry, or publication claims.

The artifact has one canonical JSON value per line, in this exact order:

1. A `settlement-search-projection-header` binds the SHA-256 of the exact spatial database and receipt, the spatial candidate identity, schema version, provenance, geometry status, and explicit false approval, production, signing, and publication claims.
2. Zero or more strictly ascending `settlement-search-projection-document` records. Each preserves the normalized source spelling, canonical and alternate spelling metadata, country and administrative context, location, population, feature code, source update date, lineage, and spatial membership/distance context.
3. A `settlement-search-projection-footer` binds the count, canonical document-stream SHA-256, and deterministic artifact identity.

The serializer opens only descriptor-bound regular files, snapshots inputs into a private work directory, checks source receipt/database reconciliation, and streams rows in numeric GeoNames order. DuckDB external spilling is disabled because its macOS runtime cannot traverse a held directory descriptor; memory pressure therefore fails closed instead of resolving an attacker-replaceable temporary path. The serializer refuses output overwrite and does not promote its staged output until all source and database authorities close successfully. The validator repeats the source checks and streams artifact records in lockstep with the exact spatial source, rejecting symlinks, path replacement, truncation, duplicate or unstable ordering, noncanonical JSON, source binding drift, and footer tampering.

The output is deliberately an internal pre-publication contract. A later reviewed browser-index stage may select an engine and map these records to a public shard format, but must retain this source binding and must not infer approval or publication eligibility from it.
