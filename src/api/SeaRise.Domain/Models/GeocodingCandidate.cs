namespace SeaRise.Domain.Models;

public record GeocodingCandidate(
    int Rank,
    string Label,
    string Country,
    double Latitude,
    double Longitude,
    string DisplayContext);
