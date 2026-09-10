# Coastal atlas content guidelines

Scope: the [accepted main product](COASTAL_ATLAS_PRD.md). US English is the only interface
language. [AR6 reference copy](CONTENT_GUIDELINES.md) remains
separate and retains its relative-level terminology.

Use plain, concise language tied to the selected source condition. Present the
year, depth, and defense assumption before optional methodological detail.

| Context | Required wording or meaning |
| --- | --- |
| Main condition | “Modeled flooding at high tide.” Explain that this is not a permanent shoreline. |
| Positive depth | “0.6 m depth” with the selected year; the value is one source model cell. |
| Valid zero | “No modeled flooding at this point” for that source condition; never a safety statement. |
| Unknown | “No data for this point.” Explain absent coverage or nodata; never call it dry land. |
| Loading failure | State which map or point data could not load and offer retry; do not fabricate a result. |
| Point scope | “One 25 m model cell, not the whole city or a property assessment.” |
| Map legend | Uncolored land may lack data. Color represents depth in meters, not probability. |
| Test edition | Prominent “Illustrative fixture” with “Synthetic data for testing; not a real-world result.” |
| Defense assumption | “No additional defenses” / “High protection”; neither is a guarantee for a place. |

Do not use future certainty (“will be underwater”), property-risk scores,
probabilities absent from the source, or safety guarantees. Do not imply that
zooming increases scientific precision. Keep source coverage and technical
availability distinct. Preserve readable attribution and access to methods.

The interface contains no experimental Lab entry, research controls, or private
filesystem paths. Legacy links may be handled internally without exposing
implementation terminology to a person using the map.
