using SeaRise.Domain.Models;

namespace SeaRise.Domain.Interfaces;

public interface IExposureEvaluator
{
    Task<bool> IsExposedAsync(double latitude, double longitude, ExposureLayer layer, CancellationToken ct);
}
