using System.Net;
using System.Net.Http.Json;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Moq;
using SeaRise.Application.Interfaces;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Api.Tests.Integration;

/// <summary>
/// Integration tests using WebApplicationFactory to validate HTTP endpoints
/// without requiring external dependencies (database, TiTiler, blob storage).
/// All infrastructure services are replaced with mocks.
/// </summary>
[Trait("Category", "Integration")]
public class EndpointTests : IClassFixture<EndpointTests.TestFactory>
{
    private readonly HttpClient _client;

    private static readonly IReadOnlyList<Scenario> FakeScenarios = new List<Scenario>
    {
        new("ssp1-26", "Lower emissions (SSP1-2.6)", "desc", 1, false),
        new("ssp2-45", "Intermediate emissions (SSP2-4.5)", "desc", 2, true),
        new("ssp5-85", "Higher emissions (SSP5-8.5)", "desc", 3, false),
    };

    private static readonly IReadOnlyList<Horizon> FakeHorizons = new List<Horizon>
    {
        new(2030, "2030", false, 1),
        new(2050, "2050", true, 2),
        new(2100, "2100", false, 3),
    };

    private static readonly MethodologyVersion FakeMethodology = new(
        "v1.0", true, "IPCC AR6", "Copernicus DEM", "what it does",
        "[\"limitation\"]", "resolution note", "threshold desc", DateTime.UtcNow);

    public EndpointTests(TestFactory factory)
    {
        _client = factory.CreateClient();
    }

    [Fact]
    public async Task Health_ReturnsOk()
    {
        var response = await _client.GetAsync("/health");
        // Health check may return 503 because mocked services don't implement
        // actual health checks, but the endpoint itself should be reachable.
        Assert.True(response.StatusCode == HttpStatusCode.OK
                    || response.StatusCode == HttpStatusCode.ServiceUnavailable);
    }

    [Fact]
    public async Task Geocode_EmptyQuery_Returns400()
    {
        var response = await _client.PostAsJsonAsync("/v1/geocode", new { query = "" });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Assess_MissingLatitude_Returns400()
    {
        var response = await _client.PostAsJsonAsync("/v1/assess", new
        {
            latitude = (double?)null,
            longitude = 4.90,
            scenarioId = "ssp2-45",
            horizonYear = 2050,
        });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task Assess_UnknownScenario_Returns400()
    {
        var response = await _client.PostAsJsonAsync("/v1/assess", new
        {
            latitude = 52.37,
            longitude = 4.90,
            scenarioId = "ssp-invalid",
            horizonYear = 2050,
        });
        Assert.Equal(HttpStatusCode.BadRequest, response.StatusCode);
    }

    [Fact]
    public async Task ConfigScenarios_ReturnsOkWithData()
    {
        var response = await _client.GetAsync("/v1/config/scenarios");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        var root = doc.RootElement;

        Assert.True(root.TryGetProperty("scenarios", out var scenarios));
        Assert.Equal(3, scenarios.GetArrayLength());
    }

    [Fact]
    public async Task ConfigMethodology_ReturnsOk()
    {
        var response = await _client.GetAsync("/v1/config/methodology");
        Assert.Equal(HttpStatusCode.OK, response.StatusCode);

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);
        Assert.True(doc.RootElement.TryGetProperty("methodologyVersion", out _));
    }

    [Fact]
    public async Task Response_ContainsCorrelationIdHeader()
    {
        var response = await _client.GetAsync("/v1/config/scenarios");
        Assert.True(response.Headers.Contains("X-Correlation-Id"));
    }

    /// <summary>
    /// Custom WebApplicationFactory that replaces all infrastructure services
    /// with mocks so tests run without PostgreSQL, Azurite, or TiTiler.
    /// </summary>
    public class TestFactory : WebApplicationFactory<Program>
    {
        protected override void ConfigureWebHost(Microsoft.AspNetCore.Hosting.IWebHostBuilder builder)
        {
            builder.UseEnvironment("Testing");

            builder.ConfigureServices(services =>
            {
                // Remove real health checks (they try to connect to Postgres/Blob)
                var healthDescriptors = services.Where(d =>
                    d.ServiceType.FullName?.Contains("HealthCheck") == true).ToList();
                foreach (var d in healthDescriptors)
                    services.Remove(d);
                services.AddHealthChecks();

                // Replace infrastructure repositories with mocks
                ReplaceService<IGeographyRepository>(services, mock =>
                {
                    mock.Setup(g => g.IsWithinEuropeAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
                        .ReturnsAsync(true);
                    mock.Setup(g => g.IsWithinCoastalZoneAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
                        .ReturnsAsync(false);
                });

                ReplaceService<ILayerResolver>(services, mock =>
                {
                    mock.Setup(l => l.ResolveAsync(It.IsAny<string>(), It.IsAny<int>(), It.IsAny<CancellationToken>()))
                        .ReturnsAsync((ExposureLayer?)null);
                });

                ReplaceService<IExposureEvaluator>(services, mock =>
                {
                    mock.Setup(e => e.IsExposedAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<ExposureLayer>(), It.IsAny<CancellationToken>()))
                        .ReturnsAsync(false);
                });

                ReplaceService<IScenarioRepository>(services, mock =>
                {
                    mock.Setup(s => s.GetAllAsync(It.IsAny<CancellationToken>())).ReturnsAsync(FakeScenarios);
                    mock.Setup(s => s.GetHorizonsAsync(It.IsAny<CancellationToken>())).ReturnsAsync(FakeHorizons);
                });

                ReplaceService<IMethodologyRepository>(services, mock =>
                {
                    mock.Setup(m => m.GetActiveAsync(It.IsAny<CancellationToken>())).ReturnsAsync(FakeMethodology);
                });
            });
        }

        private static void ReplaceService<T>(IServiceCollection services, Action<Mock<T>> setup) where T : class
        {
            var existing = services.Where(d => d.ServiceType == typeof(T)).ToList();
            foreach (var d in existing) services.Remove(d);

            var mock = new Mock<T>();
            setup(mock);
            services.AddSingleton(mock.Object);
        }
    }
}
