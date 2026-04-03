using Microsoft.Extensions.Caching.Memory;
using SeaRise.Infrastructure.Repositories;

namespace SeaRise.Api.Tests.Integration;

[Trait("Category", "Integration")]
public class ScenarioRepositoryTests : IClassFixture<TestDbFixture>
{
    private readonly ScenarioRepository _repo;

    public ScenarioRepositoryTests(TestDbFixture fixture)
    {
        _repo = new ScenarioRepository(fixture.ConnectionString, new MemoryCache(new MemoryCacheOptions()));
    }

    [Fact]
    public async Task ReturnsSeededScenarios()
    {
        var scenarios = await _repo.GetAllAsync(CancellationToken.None);

        Assert.Equal(3, scenarios.Count);
        Assert.Contains(scenarios, s => s.Id == "ssp1-26");
        Assert.Contains(scenarios, s => s.Id == "ssp2-45");
        Assert.Contains(scenarios, s => s.Id == "ssp5-85");
    }

    [Fact]
    public async Task DefaultScenarioIsSsp245()
    {
        var scenarios = await _repo.GetAllAsync(CancellationToken.None);
        var defaultScenario = scenarios.FirstOrDefault(s => s.IsDefault);

        Assert.NotNull(defaultScenario);
        Assert.Equal("ssp2-45", defaultScenario.Id);
    }

    [Fact]
    public async Task ReturnsHorizons()
    {
        var horizons = await _repo.GetHorizonsAsync(CancellationToken.None);

        Assert.Equal(3, horizons.Count);
        Assert.Contains(horizons, h => h.Year == 2030);
        Assert.Contains(horizons, h => h.Year == 2050);
        Assert.Contains(horizons, h => h.Year == 2100);
    }

    [Fact]
    public async Task DefaultHorizonIs2050()
    {
        var horizons = await _repo.GetHorizonsAsync(CancellationToken.None);
        var defaultHorizon = horizons.FirstOrDefault(h => h.IsDefault);

        Assert.NotNull(defaultHorizon);
        Assert.Equal(2050, defaultHorizon.Year);
    }
}
