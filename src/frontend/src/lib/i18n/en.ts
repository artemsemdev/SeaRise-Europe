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
    OutOfScope: (cityName: string) => `${cityName} is not on the coast`,
    UnsupportedGeography: (cityName: string) => `${cityName} is outside Europe`,
  },

  resultSummaries: {
    ModeledExposureDetected: (locationLabel: string, scenarioDisplayName: string, horizonYear: number) =>
      `Under the ${scenarioDisplayName} scenario at ${horizonYear}, ${locationLabel} shows modeled coastal exposure. Areas at or below projected sea levels may experience periodic or permanent inundation under this scenario.`,
    NoModeledExposureDetected: (locationLabel: string, scenarioDisplayName: string, horizonYear: number) =>
      `Based on current models, this location does not show significant coastal exposure under this scenario. This does not mean it is safe \u2014 conditions may change.`,
    DataUnavailable: (locationLabel: string, scenarioDisplayName: string, horizonYear: number) =>
      `We don\u2019t have enough data for this exact combination of location, forecast model, and timeframe. Try a different model or timeframe \u2014 other combinations may have data.`,
    OutOfScope: (locationLabel: string) =>
      `We currently only cover coastal locations across Europe. ${locationLabel} is too far inland for sea-level rise to apply here.`,
    OutOfScopeSuggestion: "Try searching for a city near the coast \u2014 like Hamburg, Amsterdam, or Barcelona.",
    UnsupportedGeography: (locationLabel: string) =>
      `SeaRise Europe only covers European coastlines right now. We hope to expand to other regions in the future.`,
    UnsupportedGeographySuggestion: "Try a European coastal city like Lisbon, Naples, or Copenhagen.",
  },

  locSub: (horizonYear: number, currentYear: number, scenarioDisplayName: string) => {
    const diff = horizonYear - currentYear;
    return `In ${diff} years (year ${horizonYear}) \u00b7 ${scenarioDisplayName}`;
  },

  loading: {
    title: "Calculating\u2026",
    subtitle: (locationLabel: string) =>
      `Checking sea-level data for ${locationLabel}\u2026`,
    geocoding: "Searching for locations\u2026",
    assessing: (locationLabel: string) =>
      `Calculating exposure for ${locationLabel}\u2026`,
    steps: [
      "Location confirmed",
      "Elevation data loaded",
      "Running sea-level models\u2026",
      "Generating exposure report",
    ] as readonly string[],
  },

  errors: {
    geocodingFailure: {
      heading: "Search temporarily unavailable",
      body: "We could not complete your search right now. Please try again.",
    },
    assessmentFailure: {
      heading: "Something went wrong while calculating",
      body: "Please try again.",
    },
    unexpected: {
      heading: "Something went wrong",
      body: "An unexpected error occurred. Reload the page and try again. If this continues, try a different browser.",
    },
  },

  disclaimer:
    "This is a model estimate, not an engineering or legal assessment.",

  disclaimerNoExposure:
    "This is a model estimate. No result should be taken as a safety guarantee.",

  source: "Source: IPCC AR6 sea-level projections \u00b7 Copernicus DEM elevation data",

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
    tryNextHorizon: "Try +50 yr",
    tryIpccModel: "Try IPCC model",
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
