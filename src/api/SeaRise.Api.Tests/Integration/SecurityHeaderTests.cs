using System.Net;
using System.Text.Json;
using Microsoft.AspNetCore.Hosting;
using Microsoft.AspNetCore.Mvc.Testing;
using Microsoft.Extensions.DependencyInjection;
using Moq;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Api.Tests.Integration;

[Trait("Category", "Integration")]
public class SecurityHeaderTests : IClassFixture<SecurityHeaderTests.SecurityTestFactory>
{
    private readonly HttpClient _client;

    private static readonly IReadOnlyList<Scenario> FakeScenarios = new List<Scenario>
    {
        new("ssp2-45", "Intermediate emissions (SSP2-4.5)", "desc", 2, true),
    };

    private static readonly IReadOnlyList<Horizon> FakeHorizons = new List<Horizon>
    {
        new(2050, "2050", true, 2),
    };

    private static readonly MethodologyVersion FakeMethodology = new(
        "v1.0", true, "IPCC AR6", "Copernicus DEM", "what it does",
        "[\"limitation\"]", "resolution note", "threshold desc", DateTime.UtcNow);

    public SecurityHeaderTests(SecurityTestFactory factory)
    {
        _client = factory.CreateClient();
    }

    // -------------------------------------------------------------------------
    // HSTS (A05)
    // -------------------------------------------------------------------------

    [Fact]
    public async Task Response_ContainsHstsHeader()
    {
        var response = await _client.GetAsync("/health");
        Assert.True(response.Headers.Contains("Strict-Transport-Security"));
        var hsts = response.Headers.GetValues("Strict-Transport-Security").First();
        Assert.Contains("max-age=", hsts);
        Assert.Contains("includeSubDomains", hsts);
    }

    // -------------------------------------------------------------------------
    // Standard security headers (A05)
    // -------------------------------------------------------------------------

    [Fact]
    public async Task Response_ContainsXContentTypeOptions()
    {
        var response = await _client.GetAsync("/health");
        Assert.True(response.Headers.Contains("X-Content-Type-Options"));
        Assert.Equal("nosniff", response.Headers.GetValues("X-Content-Type-Options").First());
    }

    [Fact]
    public async Task Response_ContainsXFrameOptions()
    {
        var response = await _client.GetAsync("/health");
        Assert.True(response.Headers.Contains("X-Frame-Options"));
        Assert.Equal("DENY", response.Headers.GetValues("X-Frame-Options").First());
    }

    [Fact]
    public async Task Response_ContainsReferrerPolicy()
    {
        var response = await _client.GetAsync("/health");
        Assert.True(response.Headers.Contains("Referrer-Policy"));
        Assert.Equal("strict-origin-when-cross-origin", response.Headers.GetValues("Referrer-Policy").First());
    }

    [Fact]
    public async Task Response_ContainsPermissionsPolicy()
    {
        var response = await _client.GetAsync("/health");
        Assert.True(response.Headers.Contains("Permissions-Policy"));
    }

    // -------------------------------------------------------------------------
    // Health endpoint detail restriction (A09)
    // -------------------------------------------------------------------------

    [Fact]
    public async Task Health_WithoutDetailHeader_OmitsComponents()
    {
        var response = await _client.GetAsync("/health");
        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);

        Assert.True(doc.RootElement.TryGetProperty("status", out _));
        Assert.False(doc.RootElement.TryGetProperty("components", out _),
            "Health response should NOT include component details without X-Health-Detail header");
    }

    [Fact]
    public async Task Health_WithDetailHeader_IncludesComponents()
    {
        var request = new HttpRequestMessage(HttpMethod.Get, "/health");
        request.Headers.Add("X-Health-Detail", "true");
        var response = await _client.SendAsync(request);

        var json = await response.Content.ReadAsStringAsync();
        using var doc = JsonDocument.Parse(json);

        Assert.True(doc.RootElement.TryGetProperty("status", out _));
        Assert.True(doc.RootElement.TryGetProperty("components", out _),
            "Health response should include component details with X-Health-Detail header");
    }

    // -------------------------------------------------------------------------
    // Test factory
    // -------------------------------------------------------------------------

    public class SecurityTestFactory : WebApplicationFactory<Program>
    {
        protected override void ConfigureWebHost(IWebHostBuilder builder)
        {
            builder.UseEnvironment("Testing");

            builder.ConfigureServices(services =>
            {
                var healthDescriptors = services.Where(d =>
                    d.ServiceType.FullName?.Contains("HealthCheck") == true).ToList();
                foreach (var d in healthDescriptors)
                    services.Remove(d);
                services.AddHealthChecks();

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
