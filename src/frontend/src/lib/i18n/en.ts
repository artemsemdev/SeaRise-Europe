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

  resultSummaries: {
    ModeledExposureDetected: (locationLabel: string, scenarioDisplayName: string, horizonYear: number) =>
      `Under the ${scenarioDisplayName} scenario at ${horizonYear}, ${locationLabel} shows modeled coastal exposure. Areas at or below projected sea levels may experience periodic or permanent inundation under this scenario.`,
    NoModeledExposureDetected: (locationLabel: string, scenarioDisplayName: string, horizonYear: number) =>
      `Under the ${scenarioDisplayName} scenario at ${horizonYear}, ${locationLabel} does not show modeled coastal exposure. This does not constitute a safety determination \u2014 conditions may change under different scenarios or time horizons.`,
    DataUnavailable: (locationLabel: string, scenarioDisplayName: string, horizonYear: number) =>
      `Data is not available for ${locationLabel} under the ${scenarioDisplayName} scenario at ${horizonYear}. No substitution has been made. Try a different scenario or time horizon \u2014 other combinations may have data.`,
    OutOfScope: (locationLabel: string) =>
      `${locationLabel} is outside the coastal analysis zone. This tool currently covers coastal locations across Europe. Try searching for a location closer to the coast.`,
    UnsupportedGeography: (locationLabel: string) =>
      `${locationLabel} is outside the area currently supported by SeaRise Europe. This tool covers European coastlines only.`,
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

  controls: {
    horizonLabel: "How far into the future?",
    scenarioLabel: "Forecast model",
    infoNote: "Change the year or model to see different outcomes for this location.",
  },

  actions: {
    methodology: "How is this calculated?",
    newSearch: "New search",
    retry: "Retry",
    reset: "Reset",
    searchAnother: "Search another location",
  },

  methodology: {
    title: "How is this calculated?",
    dataSources: "Data sources",
    forecastModels: "Forecast models explained",
    limitations: "What this does NOT include",
    important: "Important",
    limitationItems: [
      "Storm surges and extreme waves",
      "Local flood barriers and drainage",
      "Land sinking (subsidence)",
      "River flooding",
      "Building-level precision (we use 30m satellite data)",
    ] as readonly string[],
    warningText:
      "This is an educational tool based on scientific models. It is not a legal, engineering, insurance, or financial assessment.",
    versionLabel: "Methodology version",
    dataUpdated: "Data updated",
  },

  accessibility: {
    skipToContent: "Skip to main content",
    mapLabel: "Interactive map of Europe",
    mapWithLocation: (locationLabel: string) =>
      `Interactive map showing selected location at ${locationLabel}`,
    mapWithResult: (locationLabel: string, scenarioDisplayName: string, horizonYear: number) =>
      `Map showing exposure assessment for ${locationLabel} under ${scenarioDisplayName} at ${horizonYear}`,
    scenarioControl: "Forecast model selection",
    horizonControl: "Time horizon selection",
    resultRegion: "Assessment result",
    closePanel: "Close panel",
  },
} as const;
