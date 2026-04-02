using Npgsql;

var builder = WebApplication.CreateBuilder(args);

var app = builder.Build();

app.MapGet("/health", async () =>
{
    var databaseUrl = Environment.GetEnvironmentVariable("DATABASE_URL");
    if (string.IsNullOrEmpty(databaseUrl))
    {
        return Results.Json(new { status = "unhealthy", reason = "DATABASE_URL not configured" }, statusCode: 503);
    }

    try
    {
        await using var conn = new NpgsqlConnection(databaseUrl);
        await conn.OpenAsync();
        await using var cmd = new NpgsqlCommand("SELECT 1", conn);
        await cmd.ExecuteScalarAsync();

        return Results.Json(new { status = "healthy", service = "searise-api" });
    }
    catch (Exception ex)
    {
        return Results.Json(new { status = "unhealthy", reason = ex.Message }, statusCode: 503);
    }
});

app.Run();
