namespace SeaRise.Domain.Models;

public record Scenario(
    string Id,
    string DisplayName,
    string? Description,
    int SortOrder,
    bool IsDefault);
