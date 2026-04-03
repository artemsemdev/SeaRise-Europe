namespace SeaRise.Api.Dtos;

public record ConfigScenariosResponse(
    string RequestId,
    IReadOnlyList<ScenarioConfigDto> Scenarios,
    IReadOnlyList<HorizonConfigDto> Horizons,
    DefaultsDto Defaults);

public record ScenarioConfigDto(string Id, string DisplayName, string? Description, int SortOrder);

public record HorizonConfigDto(int Year, string DisplayLabel, int SortOrder);

public record DefaultsDto(string ScenarioId, int HorizonYear);
