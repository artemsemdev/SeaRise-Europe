using Npgsql;
using SeaRise.Domain.Interfaces;

namespace SeaRise.Infrastructure.Repositories;

public class PostGisGeographyRepository : IGeographyRepository
{
    private readonly string _connectionString;

    public PostGisGeographyRepository(string connectionString)
    {
        _connectionString = connectionString;
    }

    public async Task<bool> IsWithinEuropeAsync(double latitude, double longitude, CancellationToken ct)
    {
        return await CheckWithinBoundaryAsync("europe", latitude, longitude, ct);
    }

    public async Task<bool> IsWithinCoastalZoneAsync(double latitude, double longitude, CancellationToken ct)
    {
        return await CheckWithinBoundaryAsync("coastal_analysis_zone", latitude, longitude, ct);
    }

    private async Task<bool> CheckWithinBoundaryAsync(string boundaryName, double latitude, double longitude, CancellationToken ct)
    {
        const string sql = @"
            SELECT ST_Within(
                ST_SetSRID(ST_Point(@Lng, @Lat), 4326),
                geom
            ) FROM geography_boundaries WHERE name = @Name";

        await using var conn = new NpgsqlConnection(_connectionString);
        await conn.OpenAsync(ct);
        await using var cmd = new NpgsqlCommand(sql, conn);
        cmd.Parameters.AddWithValue("Lng", longitude);
        cmd.Parameters.AddWithValue("Lat", latitude);
        cmd.Parameters.AddWithValue("Name", boundaryName);

        var result = await cmd.ExecuteScalarAsync(ct);
        return result is true;
    }
}
