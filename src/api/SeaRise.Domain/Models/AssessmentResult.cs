namespace SeaRise.Domain.Models;

public record AssessmentResult(
    string RequestId,
    ResultState ResultState,
    LocationInfo Location,
    ScenarioInfo Scenario,
    HorizonInfo Horizon,
    string MethodologyVersion,
    string? LayerTileUrlTemplate,
    LegendSpec? LegendSpec,
    DateTime GeneratedAt);

public record LocationInfo(double Latitude, double Longitude);

public record ScenarioInfo(string Id, string DisplayName);

public record HorizonInfo(int Year, string DisplayLabel);

public record LegendSpec(IReadOnlyList<ColorStop> ColorStops);

public record ColorStop(int Value, string Color, string Label);
