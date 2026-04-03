using SeaRise.Domain.Models;

namespace SeaRise.Domain.Interfaces;

public interface IScenarioRepository
{
    Task<IReadOnlyList<Scenario>> GetAllAsync(CancellationToken ct);
    Task<IReadOnlyList<Horizon>> GetHorizonsAsync(CancellationToken ct);
}
