namespace SeaRise.Domain.Models;

public record MethodologyVersion(
    string Version,
    bool IsActive,
    string SeaLevelSourceName,
    string ElevationSourceName,
    string WhatItDoes,
    string Limitations,
    string ResolutionNote,
    string ExposureThresholdDesc,
    DateTime UpdatedAt);
