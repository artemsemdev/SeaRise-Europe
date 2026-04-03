namespace SeaRise.Domain.Models;

public record Horizon(
    int Year,
    string DisplayLabel,
    bool IsDefault,
    int SortOrder);
