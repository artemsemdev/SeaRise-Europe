using Microsoft.Extensions.Caching.Memory;
using Npgsql;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Infrastructure.Repositories;

public class MethodologyRepository : IMethodologyRepository
{
    private readonly string _connectionString;
    private readonly IMemoryCache _cache;
    private static readonly TimeSpan CacheTtl = TimeSpan.FromMinutes(5);

    public MethodologyRepository(string connectionString, IMemoryCache cache)
    {
        _connectionString = connectionString;
        _cache = cache;
    }

    public async Task<MethodologyVersion> GetActiveAsync(CancellationToken ct)
    {
        return await _cache.GetOrCreateAsync("methodology_active", async entry =>
        {
            entry.AbsoluteExpirationRelativeToNow = CacheTtl;

            const string sql = @"
                SELECT version, is_active, sea_level_source_name, elevation_source_name,
                       what_it_does, limitations, resolution_note, exposure_threshold_desc, updated_at
                FROM methodology_versions
                WHERE is_active = true
                LIMIT 1";

            await using var conn = new NpgsqlConnection(_connectionString);
            await conn.OpenAsync(ct);
            await using var cmd = new NpgsqlCommand(sql, conn);
            await using var reader = await cmd.ExecuteReaderAsync(ct);

            if (!await reader.ReadAsync(ct))
                throw new InvalidOperationException("No active methodology version found in database.");

            return new MethodologyVersion(
                Version: reader.GetString(0),
                IsActive: reader.GetBoolean(1),
                SeaLevelSourceName: reader.GetString(2),
                ElevationSourceName: reader.GetString(3),
                WhatItDoes: reader.GetString(4),
                Limitations: reader.GetString(5),
                ResolutionNote: reader.GetString(6),
                ExposureThresholdDesc: reader.GetString(7),
                UpdatedAt: reader.GetDateTime(8));
        }) ?? throw new InvalidOperationException("No active methodology version found.");
    }
}
