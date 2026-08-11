# Settlement spatial-stage publication

Run `scripts/release/build_settlement_spatial_stage.py` only in the pinned Python 3.11 spatial environment after the normalized catalogue and cache preflight pass. Supply every path, platform, and the required `production-reviewed` geometry profile explicitly; the CLI derives the fixed production geometry identities from the repository.

The output and receipt directories must already exist, resolve to one owner-controlled directory, and contain neither requested name. The runner snapshots the catalogue pair, checkpoints and closes DuckDB, rejects WAL residue and broadened claims, then independently validates the staged pair.

Publication hard-links the database without overwrite, fsyncs the directory, and links the canonical receipt last as the completion marker. A second independent validation binds the published pair to the exact catalogue and spatial authorities. Publication, owner, scientific, hazard, canonical-geometry, and geometry-eligibility claims remain false.

On failure, rollback quarantines with an exclusive rename and removes only a proven-owned inode. Racing foreign entries are restored or retained in the exact `.spatial-assets-...` staging directory. Alien or pre-identity residue also keeps that directory for inspection and is attached to the primary error. Never clean residues with a glob or recursive deletion; after confirming no process is active, inspect the exact reported directory and remove only entries whose ownership and inode identity have been independently established.
