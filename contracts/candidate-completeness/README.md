# Candidate completeness contract

This contract defines the exact Phase 1 engineering candidate boundary before
signing. `v1/required-artifacts.json` is the authoritative 53-artifact
inventory; `v1/candidate.schema.json` closes the public document shape and
reuses the release v1 path, hash, role, media-type, scenario, and horizon
definitions.

The deterministic seal order is:

1. write and validate the 50 data, configuration, receipt, rights, quality,
   architecture, STAC, settlement, COG, PMTiles, and GeoParquet artifacts;
2. write the JSON and Markdown gate reports from that pre-terminal snapshot;
3. write `checksums.txt`, covering every artifact except itself;
4. write `manifest.json` last, covering all 53 artifacts without hashing itself;
5. pass the separate supply-chain evidence-envelope and signing gate before any
   publication.

`scripts/release/validate_candidate_bytes.py` applies the read-only byte gate
to an assembled candidate root. It opens the root and descendants without
following symlinks, requires exactly 53 single-link regular files plus
`manifest.json` and no other entries, streams every artifact, and verifies its
declared byte size and SHA-256. It also reconstructs `checksums.txt` from the
52 ordered checksum subjects and rejects any tree or file identity that changes
before the documented linearization point. The gate is read-only: it never
repairs, replaces, or publishes candidate files.

Directory inspection rejects the first unexpected entry without materializing
an attacker-controlled directory listing. Declared content is limited to 64 GiB
per artifact and 256 GiB for all 53 artifacts. Success is linearized when the
candidate pathname is reopened immediately before the last identity pass. That
descriptor remains open for the complete pass. Matching identities observed
during the pass prove the tree had not drifted before this point. The result
records that point-in-time observation; it is not a filesystem lease and does
not make the caller's mutable pathname immutable. Keep the candidate offline
and rerun the gate immediately before any independent consumer opens it.

The manifest-last rule is a completeness boundary, not a filesystem timestamp
claim. The byte gate requires terminal write sequence 54 in the contract and a
complete exact tree when `manifest.json` is read; it does not infer historical
write order from mutable timestamps.

Provenance, signature, and SBOM sidecars are mandatory publication evidence,
not deferred Phase 1 work. Pair validation is still pending: a dependent
validator must bind candidate ID, release ID, provenance class, and the actual
manifest SHA-256. Sidecars stay outside the candidate inventory to avoid a
recursive manifest/signature dependency. Passing the candidate byte gate does
not claim production, publication, scientific approval, or supply-chain
approval.

The checked-in fixture is synthetic. It records no owner geometry approval,
canonical boundary, production, hazard-extent, or publication claim. Schema
validation proves document shape; the executable inventory tests additionally
prove exact artifact identity, rights, counts, 3 x 3 STAC bindings, checksum
coverage, terminal ordering, and the non-recursive supply-chain boundary.
