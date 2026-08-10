# Complete public release fixture

[`searise-europe-v1.0.0-20260810-c096aeab4e09`](searise-europe-v1.0.0-20260810-c096aeab4e09/)
is the small, complete on-disk release tree for the v1 public contracts. It has
one manifest, 41 inventoried artifacts, the exact 3 × 3 projection matrix, and
no untracked file inside the release root.

The COG, PMTiles, and projection GeoParquet bytes come from the byte-identical
macOS ARM64 candidate retained as GitHub artifact `8973969557` by trusted run
`31113582612`. The single settlement record and public-contract metadata are
fixture data, so the complete tree is deliberately classified
`synthetic-fixture`, remains `pending-owner`, and requires user-facing status
disclosure. It is not a production release or an owner-approved scientific
output.

The 9.24 GB IPCC source archive and provider caches are not committed. Its
audited identity and licence are recorded in the source receipt. The fixture
contains no provider credential, backend identifier, request identifier,
runtime tile template, or access token.

The permanent Python contract suite validates every document, cross-document
identity, rights mapping, STAC graph and assets, complete inventory, byte size,
SHA-256, and file-format magic. Any metadata or binary change therefore
requires an intentional manifest update and stays fail closed.
