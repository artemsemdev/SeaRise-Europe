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

The compact `fixtures/assembly/complete-synthetic.json` receipt drives the
normal-CI completeness assembler. It binds all 50 pre-gate fixture inputs,
their grid and pair-parity identities, STAC asset links, redistribution status,
and false claims. Run it as one isolated, non-reentrant process with an absolute,
symlink-free output path whose existing parent is owned by the current user and
is not group/world writable. The boundary excludes hostile code or hooks in the
assembler process, a hostile peer with the same user identity, inherited/open
writable descriptors to staging files, and ACLs that grant another principal
write access despite the mode bits. These capabilities can mutate bytes behind
a held descriptor and cannot be made immutable with portable POSIX path APIs.
Darwin and Linux use native no-overwrite directory renames;
all staging writes, mode changes, syncs, validation, and cleanup use held
directory descriptors. The publication commit point verifies the current
parent and final directory identities before and after validation. A failed
post-promotion check durably moves only the held assembler directory away from
the final name. Publication returns only after a third complete byte/tree pass
reopens the exact final directory through its held parent authority. This is a
point-in-time linearization, not a lease: another authorized process can replace
the pathname after that point. Because
POSIX has no conditional unlink, cleanup prioritizes foreign preservation and
retains at most one high-entropy mode-0700 `.candidate-assembly-*` quarantine
wrapper per invocation outside the public candidate name. Repeated invocations
can therefore retain multiple wrappers. Operators may remove a private
wrapper only after the assembler process exits; ephemeral CI runners remove it
with the job workspace. Its marker payloads are not valid COG, PMTiles,
GeoParquet, or search indexes.

Rollback retries bounded transient rename failures. If the operating system
rejects every quarantine attempt while the exact owned failed directory is
still at the output name, the primary validation error is preserved and gains
an explicit `assembly-rollback` cleanup failure. Treat that workspace as failed
and isolate it before operator cleanup; no success summary is returned.

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
