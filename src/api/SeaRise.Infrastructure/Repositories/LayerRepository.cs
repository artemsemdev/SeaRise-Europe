using Npgsql;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Infrastructure.Repositories;

public class LayerRepository : ILayerResolver
{
    private readonly string _connectionString;

    public LayerRepository(string connectionString)
    {
        _connectionString = connectionString;
    }

    public async Task<ExposureLayer?> ResolveAsync(string scenarioId, int horizonYear, CancellationToken ct)
    {
        const string sql = @"
            SELECT l.id, l.scenario_id, l.horizon_year, l.methodology_version, l.blob_path, l.legend_colormap
            FROM layers l
            INNER JOIN methodology_versions mv ON mv.version = l.methodology_version
            WHERE l.scenario_id = @ScenarioId
              AND l.horizon_year = @HorizonYear
              AND l.layer_valid = true
              AND mv.is_active = true
            LIMIT 1";

        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync(ct);
        await using var cmd = new NpgsqlCommand(sql, conn);
        cmd.Parameters.AddWithValue("ScenarioId", scenarioId);
        cmd.Parameters.AddWithValue("HorizonYear", horizonYear);

        await using var reader = await cmd.ExecuteReaderAsync(ct);
        if (!await reader.ReadAsync(ct))
            return null;

        return new ExposureLayer(
            Id: reader.GetGuid(0),
            ScenarioId: reader.GetString(1),
            HorizonYear: reader.GetInt32(2),
            MethodologyVersion: reader.GetString(3),
            BlobPath: reader.GetString(4),
            LegendColormap: reader.IsDBNull(5) ? null : reader.GetString(5));
    }
}
