export const strings = {
  emptyState: {
    heading: "Explore coastal sea-level exposure in Europe",
    body: "Enter a European address, city, or location to see how it appears in scenario-based sea-level projections. Choose a scenario and time horizon to compare different outlooks.",
    subtext:
      "Results are model-based estimates, not engineering assessments. See methodology for details.",
  },

  resultStates: {
    ModeledExposureDetected: "Risk detected",
    NoModeledExposureDetected: "No risk detected",
    DataUnavailable: "Data not available",
    OutOfScope: "This location is too far from the coast",
    UnsupportedGeography: "This location is outside Europe",
  },

  loading: {
    geocoding: "Searching for locations\u2026",
    assessing: (locationLabel: string) =>
      `Calculating exposure for ${locationLabel}\u2026`,
  },

  errors: {
    geocodingFailure: {
      heading: "Search temporarily unavailable",
      body: "We could not complete your search right now. Please try again.",
    },
    assessmentFailure: {
      heading: "Result temporarily unavailable",
      body: "We could not calculate the exposure for this location right now. Please try again.",
    },
    unexpected: {
      heading: "Something went wrong",
      body: "An unexpected error occurred. Reload the page and try again. If this continues, try a different browser.",
    },
  },

  disclaimer:
    "This result is a scenario-based model estimate for informational purposes only. It is not an engineering assessment, structural survey, legal determination, insurance evaluation, mortgage guidance, or financial advice. Do not rely on this result for decisions requiring professional expertise.",

  noResults: {
    heading: "No locations found",
    body: (query: string) =>
      `We could not find a match for \u201c${query}\u201d. Try a more specific address, a city name, or a well-known landmark.`,
  },

  search: {
    placeholder: "Search for a European location",
    submitLabel: "Search",
  },

  candidateList: {
    heading: "Select a location",
  },
} as const;
