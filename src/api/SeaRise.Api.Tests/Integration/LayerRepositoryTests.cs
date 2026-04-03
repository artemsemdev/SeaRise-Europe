using SeaRise.Infrastructure.Repositories;

namespace SeaRise.Api.Tests.Integration;

[Trait("Category", "Integration")]
public class LayerRepositoryTests : IClassFixture<TestDbFixture>
{
    private readonly LayerRepository _repo;

    public LayerRepositoryTests(TestDbFixture fixture)
    {
        _repo = new LayerRepository(fixture.ConnectionString);
    }

    [Fact]
    public async Task ResolvesValidLayer()
    {
        var layer = await _repo.ResolveAsync("ssp2-45", 2050, CancellationToken.None);

        Assert.NotNull(layer);
        Assert.Equal("ssp2-45", layer.ScenarioId);
        Assert.Equal(2050, layer.HorizonYear);
        Assert.Equal("v1.0", layer.MethodologyVersion);
    }

    [Fact]
    public async Task ReturnsNullForInvalidScenario()
    {
        var layer = await _repo.ResolveAsync("nonexistent", 2050, CancellationToken.None);
        Assert.Null(layer);
    }

    [Fact]
    public async Task ReturnsNullForInvalidHorizon()
    {
        var layer = await _repo.ResolveAsync("ssp2-45", 2060, CancellationToken.None);
        Assert.Null(layer);
    }
}
