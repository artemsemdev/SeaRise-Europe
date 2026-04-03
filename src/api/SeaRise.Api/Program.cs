using System.Diagnostics;
using System.Text.Json;
using System.Text.Json.Serialization;
using FluentValidation;
using Microsoft.Extensions.Diagnostics.HealthChecks;
using SeaRise.Api.Dtos;
using SeaRise.Api.Validators;
using SeaRise.Application.Interfaces;
using SeaRise.Application.Services;
using SeaRise.Domain.Exceptions;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;
using SeaRise.Infrastructure.Clients;
using SeaRise.Infrastructure.Repositories;
using Serilog;
using Serilog.Events;
using Serilog.Formatting.Compact;

// ---------------------------------------------------------------------------
// Serilog bootstrap
// ---------------------------------------------------------------------------
Log.Logger = new LoggerConfiguration()
    .Enrich.FromLogContext()
    .Enrich.WithProperty("service", "searise-api")
    .WriteTo.Console(new RenderedCompactJsonFormatter())
    .MinimumLevel.Information()
    .MinimumLevel.Override("Microsoft.AspNetCore", LogEventLevel.Warning)
    .CreateLogger();

try
{
    var builder = WebApplication.CreateBuilder(args);
    builder.Host.UseSerilog();

    // ---------------------------------------------------------------------------
    // Configuration
    // ---------------------------------------------------------------------------
    var databaseUrl = Environment.GetEnvironmentVariable("DATABASE_URL")
                      ?? builder.Configuration.GetConnectionString("PostgreSql")
                      ?? "";
    var tilerBaseUrl = Environment.GetEnvironmentVariable("TILER_BASE_URL")
                       ?? builder.Configuration["Tiler:BaseUrl"]
                       ?? "http://localhost:8000";
    var geocodingBaseUrl = Environment.GetEnvironmentVariable("GEOCODING_BASE_URL")
                           ?? builder.Configuration["Geocoding:BaseUrl"]
                           ?? "https://nominatim.openstreetmap.org";
    var corsOrigins = (Environment.GetEnvironmentVariable("CORS_ALLOWED_ORIGINS") ?? "http://localhost:3000")
                       .Split(',', StringSplitOptions.RemoveEmptyEntries | StringSplitOptions.TrimEntries);
    var blobConnectionString = Environment.GetEnvironmentVariable("AZURE_STORAGE_CONNECTION_STRING")
                               ?? builder.Configuration["BlobStorage:ConnectionString"]
                               ?? "";

    // ---------------------------------------------------------------------------
    // Services
    // ---------------------------------------------------------------------------
    builder.Services.AddMemoryCache();

    // Domain/Infrastructure registrations
    builder.Services.AddSingleton<IGeographyRepository>(new PostGisGeographyRepository(databaseUrl));
    builder.Services.AddSingleton<ILayerResolver>(new LayerRepository(databaseUrl));
    builder.Services.AddSingleton<IScenarioRepository>(sp =>
        new ScenarioRepository(databaseUrl, sp.GetRequiredService<Microsoft.Extensions.Caching.Memory.IMemoryCache>()));
    builder.Services.AddSingleton<IMethodologyRepository>(sp =>
        new MethodologyRepository(databaseUrl, sp.GetRequiredService<Microsoft.Extensions.Caching.Memory.IMemoryCache>()));

    // Geocoding HTTP client (5s timeout)
    builder.Services.AddHttpClient<IGeocodingService, NominatimGeocodingClient>(client =>
    {
        client.BaseAddress = new Uri(geocodingBaseUrl);
        client.Timeout = TimeSpan.FromSeconds(5);
        client.DefaultRequestHeaders.Add("User-Agent", "SeaRise-Europe/1.0 (development)");
    });

    // TiTiler HTTP client (3s timeout)
    builder.Services.AddHttpClient<IExposureEvaluator, TiTilerExposureEvaluator>(client =>
    {
        client.BaseAddress = new Uri(tilerBaseUrl);
        client.Timeout = TimeSpan.FromSeconds(3);
    });

    // Application services
    builder.Services.AddScoped<IAssessmentService, AssessmentService>();

    // Validators
    builder.Services.AddScoped<IValidator<GeocodeRequest>, GeocodeRequestValidator>();
    builder.Services.AddScoped<IValidator<AssessRequest>, AssessRequestValidator>();

    // CORS
    builder.Services.AddCors(options =>
    {
        options.AddPolicy("frontend", policy =>
        {
            policy.WithOrigins(corsOrigins)
                  .AllowAnyMethod()
                  .AllowAnyHeader();
        });
    });

    // Health checks
    builder.Services.AddHealthChecks()
        .AddNpgSql(databaseUrl, name: "postgres")
        .AddAzureBlobStorage(
            sp => new Azure.Storage.Blobs.BlobServiceClient(blobConnectionString),
            name: "blobStorage");

    // JSON serialization
    builder.Services.ConfigureHttpJsonOptions(options =>
    {
        options.SerializerOptions.PropertyNamingPolicy = JsonNamingPolicy.CamelCase;
        options.SerializerOptions.DefaultIgnoreCondition = JsonIgnoreCondition.WhenWritingNull;
        options.SerializerOptions.Converters.Add(new JsonStringEnumConverter(JsonNamingPolicy.CamelCase));
    });

    var app = builder.Build();

    // ---------------------------------------------------------------------------
    // Middleware
    // ---------------------------------------------------------------------------
    app.UseCors("frontend");

    // Correlation ID middleware (must run before Serilog request logging
    // so that requestId is included in the structured log properties)
    app.Use(async (context, next) =>
    {
        var correlationId = context.Request.Headers["X-Correlation-Id"].FirstOrDefault()
                            ?? $"req_{Guid.NewGuid():N}"[..16];
        context.Items["RequestId"] = correlationId;
        context.Response.Headers["X-Correlation-Id"] = correlationId;

        using (Serilog.Context.LogContext.PushProperty("requestId", correlationId))
        {
            await next();
        }
    });

    app.UseSerilogRequestLogging();

    // ---------------------------------------------------------------------------
    // Endpoints
    // ---------------------------------------------------------------------------

    // POST /v1/geocode
    app.MapPost("/v1/geocode", async (
        GeocodeRequest request,
        IValidator<GeocodeRequest> validator,
        IGeocodingService geocodingService,
        HttpContext httpContext) =>
    {
        var requestId = httpContext.Items["RequestId"]?.ToString() ?? "";
        var sw = Stopwatch.StartNew();

        // Validate
        var validation = await validator.ValidateAsync(request);
        if (!validation.IsValid)
        {
            var firstError = validation.Errors.First();
            return Results.Json(
                new ErrorResponse(requestId, new ErrorDetail("VALIDATION_ERROR", firstError.ErrorMessage, firstError.PropertyName.ToLowerInvariant())),
                statusCode: 400);
        }

        try
        {
            Log.ForContext("requestId", requestId).Debug("GeocodeRequested");

            var candidates = await geocodingService.GeocodeAsync(request.Query!, httpContext.RequestAborted);

            sw.Stop();
            Log.ForContext("requestId", requestId)
               .Information("GeocodeCompleted {CandidateCount} {DurationMs}", candidates.Count, sw.ElapsedMilliseconds);

            var candidateDtos = candidates.Select(c => new CandidateDto(
                c.Rank, c.Label, c.Country, c.Latitude, c.Longitude, c.DisplayContext)).ToList();

            return Results.Ok(new GeocodeResponse(requestId, candidateDtos));
        }
        catch (GeocodingProviderException ex)
        {
            sw.Stop();
            Log.ForContext("requestId", requestId)
               .Error("GeocodeProviderError {DurationMs}", sw.ElapsedMilliseconds);

            return Results.Json(
                new ErrorResponse(requestId, new ErrorDetail("GEOCODING_PROVIDER_ERROR", ex.Message)),
                statusCode: 500);
        }
    });

    // POST /v1/assess
    app.MapPost("/v1/assess", async (
        AssessRequest request,
        IValidator<AssessRequest> validator,
        IAssessmentService assessmentService,
        HttpContext httpContext) =>
    {
        var requestId = httpContext.Items["RequestId"]?.ToString() ?? "";
        var sw = Stopwatch.StartNew();

        // Validate
        var validation = await validator.ValidateAsync(request);
        if (!validation.IsValid)
        {
            var firstError = validation.Errors.First();
            var errorCode = firstError.ErrorCode switch
            {
                "UNKNOWN_SCENARIO" => "UNKNOWN_SCENARIO",
                "UNKNOWN_HORIZON" => "UNKNOWN_HORIZON",
                _ => "VALIDATION_ERROR"
            };
            return Results.Json(
                new ErrorResponse(requestId, new ErrorDetail(errorCode, firstError.ErrorMessage, firstError.PropertyName.ToLowerInvariant())),
                statusCode: 400);
        }

        try
        {
            Log.ForContext("requestId", requestId)
               .Debug("AssessmentRequested {ScenarioId} {HorizonYear}", request.ScenarioId, request.HorizonYear);

            var query = new AssessmentQuery(
                request.Latitude!.Value,
                request.Longitude!.Value,
                request.ScenarioId!,
                request.HorizonYear!.Value);

            var result = await assessmentService.AssessAsync(query, requestId, httpContext.RequestAborted);

            sw.Stop();
            Log.ForContext("requestId", requestId)
               .Information("AssessmentCompleted {ResultState} {ScenarioId} {HorizonYear} {DurationMs}",
                   result.ResultState.ToString(), request.ScenarioId, request.HorizonYear, sw.ElapsedMilliseconds);

            var response = new AssessResponse(
                RequestId: result.RequestId,
                ResultState: result.ResultState.ToString(),
                Location: new LocationDto(result.Location.Latitude, result.Location.Longitude),
                Scenario: new ScenarioDto(result.Scenario.Id, result.Scenario.DisplayName),
                Horizon: new HorizonDto(result.Horizon.Year, result.Horizon.DisplayLabel),
                MethodologyVersion: result.MethodologyVersion,
                LayerTileUrlTemplate: result.LayerTileUrlTemplate,
                LegendSpec: result.LegendSpec is not null
                    ? new LegendSpecDto(result.LegendSpec.ColorStops.Select(
                        cs => new ColorStopDto(cs.Value, cs.Color, cs.Label)).ToList())
                    : null,
                GeneratedAt: result.GeneratedAt);

            return Results.Ok(response);
        }
        catch (Exception ex)
        {
            sw.Stop();
            Log.ForContext("requestId", requestId)
               .Error(ex, "AssessmentError {ErrorCode} {DurationMs}", "INTERNAL_ERROR", sw.ElapsedMilliseconds);

            return Results.Json(
                new ErrorResponse(requestId, new ErrorDetail("INTERNAL_ERROR", "An unexpected error occurred.")),
                statusCode: 500);
        }
    });

    // GET /v1/config/scenarios
    app.MapGet("/v1/config/scenarios", async (
        IScenarioRepository scenarioRepo,
        HttpContext httpContext) =>
    {
        var requestId = httpContext.Items["RequestId"]?.ToString() ?? "";

        var scenarios = await scenarioRepo.GetAllAsync(httpContext.RequestAborted);
        var horizons = await scenarioRepo.GetHorizonsAsync(httpContext.RequestAborted);

        var defaultScenario = scenarios.FirstOrDefault(s => s.IsDefault);
        var defaultHorizon = horizons.FirstOrDefault(h => h.IsDefault);

        return Results.Ok(new ConfigScenariosResponse(
            RequestId: requestId,
            Scenarios: scenarios.Select(s =>
                new ScenarioConfigDto(s.Id, s.DisplayName, s.Description, s.SortOrder)).ToList(),
            Horizons: horizons.Select(h =>
                new HorizonConfigDto(h.Year, h.DisplayLabel, h.SortOrder)).ToList(),
            Defaults: new DefaultsDto(
                ScenarioId: defaultScenario?.Id ?? "ssp2-45",
                HorizonYear: defaultHorizon?.Year ?? 2050)));
    });

    // GET /v1/config/methodology
    app.MapGet("/v1/config/methodology", async (
        IMethodologyRepository methodologyRepo,
        HttpContext httpContext) =>
    {
        var requestId = httpContext.Items["RequestId"]?.ToString() ?? "";

        var methodology = await methodologyRepo.GetActiveAsync(httpContext.RequestAborted);

        var limitations = new List<string>();
        try
        {
            var parsed = JsonSerializer.Deserialize<List<string>>(methodology.Limitations);
            if (parsed is not null) limitations = parsed;
        }
        catch
        {
            limitations.Add(methodology.Limitations);
        }

        return Results.Ok(new ConfigMethodologyResponse(
            RequestId: requestId,
            MethodologyVersion: methodology.Version,
            SeaLevelProjectionSource: new SourceDto(
                Name: "IPCC AR6 sea-level projections",
                Provider: "NASA Sea Level Change Team",
                Url: "https://sealevel.nasa.gov/ipcc-ar6-sea-level-projection-tool"),
            ElevationSource: new SourceDto(
                Name: "Copernicus DEM (Digital Surface Model, GLO-30)",
                Provider: "Copernicus / DLR",
                Url: "https://dataspace.copernicus.eu/explore-data/data-collections/copernicus-contributing-missions/collections-description/COP-DEM"),
            WhatItDoes: methodology.WhatItDoes,
            WhatItDoesNotAccountFor: limitations,
            ResolutionNote: methodology.ResolutionNote,
            InterpretationGuidance: new InterpretationGuidanceDto(
                ModeledExposureDetected: "The selected point falls within a zone where modeled sea-level rise reaches or exceeds the terrain elevation under the selected scenario and time horizon.",
                NoModeledExposureDetected: "The selected point does not fall within a modeled exposure zone under the selected scenario and time horizon. This does not constitute a safety determination."),
            UpdatedAt: methodology.UpdatedAt));
    });

    // GET /health
    app.MapGet("/health", async (HttpContext httpContext) =>
    {
        var healthCheckService = httpContext.RequestServices.GetRequiredService<HealthCheckService>();
        var report = await healthCheckService.CheckHealthAsync(httpContext.RequestAborted);

        var postgresStatus = report.Entries.TryGetValue("postgres", out var pgEntry)
            ? (pgEntry.Status == HealthStatus.Healthy ? "healthy" : "unhealthy")
            : "unknown";
        var blobStatus = report.Entries.TryGetValue("blobStorage", out var blobEntry)
            ? (blobEntry.Status == HealthStatus.Healthy ? "healthy" : "unhealthy")
            : "unknown";

        var overallStatus = report.Status == HealthStatus.Healthy ? "healthy" : "unhealthy";
        var statusCode = report.Status == HealthStatus.Healthy ? 200 : 503;

        Log.Debug("HealthCheckCompleted {Postgres} {BlobStorage}", postgresStatus, blobStatus);

        return Results.Json(
            new HealthResponse(overallStatus, new HealthComponentsDto(postgresStatus, blobStatus), DateTime.UtcNow),
            statusCode: statusCode);
    });

    app.Run();
}
catch (Exception ex)
{
    Log.Fatal(ex, "Application start-up failed");
    throw;
}
finally
{
    Log.CloseAndFlush();
}

// Make Program class accessible for WebApplicationFactory in integration tests
public partial class Program { }
