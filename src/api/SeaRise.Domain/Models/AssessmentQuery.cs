namespace SeaRise.Domain.Models;

public record AssessmentQuery(
    double Latitude,
    double Longitude,
    string ScenarioId,
    int HorizonYear);
