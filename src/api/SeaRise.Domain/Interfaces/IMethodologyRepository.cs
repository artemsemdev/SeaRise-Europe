using SeaRise.Domain.Models;

namespace SeaRise.Domain.Interfaces;

public interface IMethodologyRepository
{
    Task<MethodologyVersion> GetActiveAsync(CancellationToken ct);
}
