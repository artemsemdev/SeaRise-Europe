using SeaRise.Domain.Models;

namespace SeaRise.Domain.Interfaces;

public interface IGeocodingService
{
    Task<IReadOnlyList<GeocodingCandidate>> GeocodeAsync(string query, CancellationToken cancellationToken);
}
