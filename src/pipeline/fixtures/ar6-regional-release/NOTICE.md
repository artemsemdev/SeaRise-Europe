# AR6 regional source fixture

`source-fixture.json.gz` is a deterministic, source-native subset of the pinned
IPCC AR6 Sea Level Projections release `20210809`. It contains the three likely
range statistics for the nine required scenario/horizon combinations on the
76 × 46 regional grid. It contains no interpolated or terrain-derived values.

The fixture was generated from the complete archive only after its SHA-256 and
the three selected member SHA-256 values passed the source lock. The generation
receipt records those identities. The 9.24 GB archive and 70 MB NetCDF members
are not stored in Git.

Source: Garner et al. (2021), IPCC AR6 Sea Level Projections, version 20210809,
doi:10.5281/zenodo.5914709.

Licence: [Creative Commons Attribution 4.0 International](https://creativecommons.org/licenses/by/4.0/).

The fixture is suitable for deterministic offline tests and engineering
measurements. Its receipt deliberately sets `scientificReleaseEligible` to
`false`: a production release must re-verify the source archive and members in
that build, rather than treating checked-in derived bytes as the original
source.
