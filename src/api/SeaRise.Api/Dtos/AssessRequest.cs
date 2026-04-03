namespace SeaRise.Api.Dtos;

public record AssessRequest(
    double? Latitude,
    double? Longitude,
    string? ScenarioId,
    int? HorizonYear);
