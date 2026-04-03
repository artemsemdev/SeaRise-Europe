namespace SeaRise.Api.Dtos;

public record ConfigMethodologyResponse(
    string RequestId,
    string MethodologyVersion,
    SourceDto SeaLevelProjectionSource,
    SourceDto ElevationSource,
    string WhatItDoes,
    IReadOnlyList<string> WhatItDoesNotAccountFor,
    string ResolutionNote,
    InterpretationGuidanceDto InterpretationGuidance,
    DateTime UpdatedAt);

public record SourceDto(string Name, string Provider, string Url);

public record InterpretationGuidanceDto(string ModeledExposureDetected, string NoModeledExposureDetected);
