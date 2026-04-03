namespace SeaRise.Api.Dtos;

public record AssessResponse(
    string RequestId,
    string ResultState,
    LocationDto Location,
    ScenarioDto Scenario,
    HorizonDto Horizon,
    string MethodologyVersion,
    string? LayerTileUrlTemplate,
    LegendSpecDto? LegendSpec,
    DateTime GeneratedAt);

public record LocationDto(double Latitude, double Longitude);

public record ScenarioDto(string Id, string DisplayName);

public record HorizonDto(int Year, string DisplayLabel);

public record LegendSpecDto(IReadOnlyList<ColorStopDto> ColorStops);

public record ColorStopDto(int Value, string Color, string Label);
