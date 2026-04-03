using Microsoft.Extensions.Caching.Memory;
using Npgsql;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Infrastructure.Repositories;

public class ScenarioRepository : IScenarioRepository
{
    private readonly string _connectionString;
    private readonly IMemoryCache _cache;
    private static readonly TimeSpan CacheTtl = TimeSpan.FromHours(1);

    public ScenarioRepository(string connectionString, IMemoryCache cache)
    {
        _connectionString = connectionString;
        _cache = cache;
    }

    public async Task<IReadOnlyList<Scenario>> GetAllAsync(CancellationToken ct)
    {
        return await _cache.GetOrCreateAsync("scenarios_all", async entry =>
        {
            entry.AbsoluteExpirationRelativeToNow = CacheTtl;

            const string sql = @"
                SELECT id, display_name, description, sort_order, is_default
                FROM scenarios
                ORDER BY sort_order";

            await using var conn = new NpgsqlConnection(_connectionString);
            await conn.OpenAsync(ct);
            await using var cmd = new NpgsqlCommand(sql, conn);
            await using var reader = await cmd.ExecuteReaderAsync(ct);

            var scenarios = new List<Scenario>();
            while (await reader.ReadAsync(ct))
            {
                scenarios.Add(new Scenario(
                    Id: reader.GetString(0),
                    DisplayName: reader.GetString(1),
                    Description: reader.IsDBNull(2) ? null : reader.GetString(2),
                    SortOrder: reader.GetInt32(3),
                    IsDefault: reader.GetBoolean(4)));
            }
            return (IReadOnlyList<Scenario>)scenarios;
        }) ?? Array.Empty<Scenario>();
    }

    public async Task<IReadOnlyList<Horizon>> GetHorizonsAsync(CancellationToken ct)
    {
        return await _cache.GetOrCreateAsync("horizons_all", async entry =>
        {
            entry.AbsoluteExpirationRelativeToNow = CacheTtl;

            const string sql = @"
                SELECT year, display_label, is_default, sort_order
                FROM horizons
                ORDER BY sort_order";

            await using var conn = new NpgsqlConnection(_connectionString);
            await conn.OpenAsync(ct);
            await using var cmd = new NpgsqlCommand(sql, conn);
            await using var reader = await cmd.ExecuteReaderAsync(ct);

            var horizons = new List<Horizon>();
            while (await reader.ReadAsync(ct))
            {
                horizons.Add(new Horizon(
                    Year: reader.GetInt32(0),
                    DisplayLabel: reader.GetString(1),
                    IsDefault: reader.GetBoolean(2),
                    SortOrder: reader.GetInt32(3)));
            }
            return (IReadOnlyList<Horizon>)horizons;
        }) ?? Array.Empty<Horizon>();
    }
}
