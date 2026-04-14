using Npgsql;
using Testcontainers.PostgreSql;

namespace SeaRise.Api.Tests.Integration;

public class TestDbFixture : IAsyncLifetime
{
    private readonly PostgreSqlContainer _container = new PostgreSqlBuilder()
        .WithImage("postgis/postgis:16-3.4")
        .WithDatabase("searise_test")
        .WithUsername("test")
        .WithPassword("test")
        .Build();

    public string ConnectionString => _container.GetConnectionString();

    public async Task InitializeAsync()
    {
        await _container.StartAsync();
        await SeedDatabaseAsync();
    }

    public async Task DisposeAsync()
    {
        await _container.DisposeAsync();
    }

    private async Task SeedDatabaseAsync()
    {
        await using var conn = new NpgsqlConnection(ConnectionString);
        await conn.OpenAsync();

        // Read and execute init.sql from the infra directory
        var initSqlPath = FindInitSql();
        if (initSqlPath is not null)
        {
            var sql = await File.ReadAllTextAsync(initSqlPath);
            await using var cmd = new NpgsqlCommand(sql, conn);
            await cmd.ExecuteNonQueryAsync();
        }
        else
        {
            await SeedMinimalSchemaAsync(conn);
        }

        // Seed test geometry data (simplified bounding boxes for testing)
        await SeedGeographyBoundariesAsync(conn);
    }

    private static string? FindInitSql()
    {
        var dir = Directory.GetCurrentDirectory();
        for (var i = 0; i < 8; i++)
        {
            var candidate = Path.Combine(dir, "infra", "db", "init.sql");
            if (File.Exists(candidate)) return candidate;
            var parent = Directory.GetParent(dir);
            if (parent is null) break;
            dir = parent.FullName;
        }
        return null;
    }

    private static async Task SeedMinimalSchemaAsync(NpgsqlConnection conn)
    {
        const string schema = @"
            CREATE EXTENSION IF NOT EXISTS postgis;

            CREATE TABLE scenarios (
                id VARCHAR(64) PRIMARY KEY,
                display_name VARCHAR(255) NOT NULL,
                description TEXT,
                sort_order INTEGER NOT NULL,
                is_default BOOLEAN NOT NULL DEFAULT false,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE UNIQUE INDEX scenarios_default_idx ON scenarios (is_default) WHERE is_default = true;

            CREATE TABLE horizons (
                year INTEGER PRIMARY KEY,
                display_label VARCHAR(32) NOT NULL,
                is_default BOOLEAN NOT NULL DEFAULT false,
                sort_order INTEGER NOT NULL
            );
            CREATE UNIQUE INDEX horizons_default_idx ON horizons (is_default) WHERE is_default = true;

            CREATE TABLE methodology_versions (
                version VARCHAR(32) PRIMARY KEY,
                is_active BOOLEAN NOT NULL DEFAULT false,
                sea_level_source_name TEXT NOT NULL,
                elevation_source_name TEXT NOT NULL,
                what_it_does TEXT NOT NULL,
                limitations TEXT NOT NULL,
                resolution_note TEXT NOT NULL,
                exposure_threshold NUMERIC,
                exposure_threshold_desc TEXT NOT NULL,
                updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );

            CREATE TABLE layers (
                id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
                scenario_id VARCHAR(64) NOT NULL REFERENCES scenarios(id),
                horizon_year INTEGER NOT NULL REFERENCES horizons(year),
                methodology_version VARCHAR(32) NOT NULL REFERENCES methodology_versions(version),
                blob_path TEXT NOT NULL,
                blob_container TEXT NOT NULL DEFAULT 'geospatial',
                cog_format BOOLEAN NOT NULL DEFAULT true,
                layer_valid BOOLEAN NOT NULL DEFAULT false,
                legend_colormap JSONB,
                generated_at TIMESTAMPTZ NOT NULL,
                UNIQUE (scenario_id, horizon_year, methodology_version)
            );
            CREATE INDEX layers_lookup_idx ON layers (scenario_id, horizon_year, methodology_version) WHERE layer_valid = true;

            CREATE TABLE geography_boundaries (
                name VARCHAR(64) PRIMARY KEY,
                geom GEOMETRY(MULTIPOLYGON, 4326) NOT NULL,
                description TEXT,
                source TEXT,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE INDEX geography_boundaries_geom_idx ON geography_boundaries USING GIST(geom);

            INSERT INTO scenarios (id, display_name, description, sort_order, is_default) VALUES
                ('ssp1-26', 'Lower emissions (SSP1-2.6)', 'Lower-emissions AR6 pathway.', 1, false),
                ('ssp2-45', 'Intermediate emissions (SSP2-4.5)', 'Mid-range AR6 pathway.', 2, true),
                ('ssp5-85', 'Higher emissions (SSP5-8.5)', 'Higher-emissions AR6 pathway.', 3, false);

            INSERT INTO horizons (year, display_label, is_default, sort_order) VALUES
                (2030, '2030', false, 1),
                (2050, '2050', true, 2),
                (2100, '2100', false, 3);

            INSERT INTO methodology_versions (version, is_active, sea_level_source_name, elevation_source_name, what_it_does, limitations, resolution_note, exposure_threshold_desc, updated_at) VALUES
                ('v1.0', true, 'IPCC AR6', 'Copernicus DEM GLO-30', 'Combines projections with elevation.', '[]', 'Approx 30m resolution.', 'Binary.', now());

            INSERT INTO geography_boundaries (name, geom, description, source) VALUES
                ('europe', ST_GeomFromText('MULTIPOLYGON EMPTY', 4326), 'Europe boundary.', 'Natural Earth'),
                ('coastal_analysis_zone', ST_GeomFromText('MULTIPOLYGON EMPTY', 4326), 'Coastal zone.', 'Copernicus');
        ";

        await using var cmd = new NpgsqlCommand(schema, conn);
        await cmd.ExecuteNonQueryAsync();
    }

    private static async Task SeedGeographyBoundariesAsync(NpgsqlConnection conn)
    {
        // Seed synthetic test bounding boxes for integration tests. Real
        // production geometries live in infra/db/init-geography.sql, which
        // uses psql meta-commands and is not loaded by this fixture (see the
        // header comment in init.sql). ON CONFLICT keeps us compatible with
        // both code paths (init.sql-found and SeedMinimalSchemaAsync fallback).
        const string upsertEurope = @"
            INSERT INTO geography_boundaries (name, geom, description, source)
            VALUES (
                'europe',
                ST_GeomFromText('MULTIPOLYGON(((-25 34, 45 34, 45 72, -25 72, -25 34)))', 4326),
                'Integration-test synthetic Europe bbox.',
                'TestDbFixture'
            )
            ON CONFLICT (name) DO UPDATE SET
                geom = EXCLUDED.geom,
                description = EXCLUDED.description,
                source = EXCLUDED.source";

        const string upsertCoastal = @"
            INSERT INTO geography_boundaries (name, geom, description, source)
            VALUES (
                'coastal_analysis_zone',
                ST_GeomFromText('MULTIPOLYGON(((-10 35, 10 35, 10 60, -10 60, -10 35)))', 4326),
                'Integration-test synthetic coastal-zone strip.',
                'TestDbFixture'
            )
            ON CONFLICT (name) DO UPDATE SET
                geom = EXCLUDED.geom,
                description = EXCLUDED.description,
                source = EXCLUDED.source";

        await using var cmd1 = new NpgsqlCommand(upsertEurope, conn);
        await cmd1.ExecuteNonQueryAsync();

        await using var cmd2 = new NpgsqlCommand(upsertCoastal, conn);
        await cmd2.ExecuteNonQueryAsync();

        // Idempotent: init.sql may already seed this row; ON CONFLICT keeps the fixture
        // compatible with both pre- and post-P1.5 database images.
        const string insertLayer = @"
            INSERT INTO layers (scenario_id, horizon_year, methodology_version, blob_path, layer_valid, generated_at)
            VALUES ('ssp2-45', 2050, 'v1.0', 'layers/v1.0/ssp2-45/2050.tif', true, now())
            ON CONFLICT (scenario_id, horizon_year, methodology_version) DO NOTHING";

        await using var cmd3 = new NpgsqlCommand(insertLayer, conn);
        await cmd3.ExecuteNonQueryAsync();
    }
}
