namespace SeaRise.Domain.Interfaces;

public interface IGeographyRepository
{
    Task<bool> IsWithinEuropeAsync(double latitude, double longitude, CancellationToken ct);
    Task<bool> IsWithinCoastalZoneAsync(double latitude, double longitude, CancellationToken ct);
}
