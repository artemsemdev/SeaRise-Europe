using SeaRise.Domain.Models;

namespace SeaRise.Domain.Interfaces;

public interface ILayerResolver
{
    Task<ExposureLayer?> ResolveAsync(string scenarioId, int horizonYear, CancellationToken ct);
}
