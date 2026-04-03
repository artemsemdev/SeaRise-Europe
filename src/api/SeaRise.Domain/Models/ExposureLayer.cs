namespace SeaRise.Domain.Models;

public record ExposureLayer(
    Guid Id,
    string ScenarioId,
    int HorizonYear,
    string MethodologyVersion,
    string BlobPath,
    string? LegendColormap);
