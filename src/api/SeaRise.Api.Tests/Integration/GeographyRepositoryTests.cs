using SeaRise.Infrastructure.Repositories;

namespace SeaRise.Api.Tests.Integration;

[Trait("Category", "Integration")]
public class GeographyRepositoryTests : IClassFixture<TestDbFixture>
{
    private readonly PostGisGeographyRepository _repo;

    public GeographyRepositoryTests(TestDbFixture fixture)
    {
        _repo = new PostGisGeographyRepository(fixture.ConnectionString);
    }

    [Fact]
    public async Task AmsterdamIsInEurope()
    {
        var result = await _repo.IsWithinEuropeAsync(52.3676, 4.9041, CancellationToken.None);
        Assert.True(result);
    }

    [Fact]
    public async Task NewYorkIsNotInEurope()
    {
        var result = await _repo.IsWithinEuropeAsync(40.7128, -74.0060, CancellationToken.None);
        Assert.False(result);
    }

    [Fact]
    public async Task AmsterdamIsInCoastalZone()
    {
        // Amsterdam (4.9041 E, 52.3676 N) is within the test coastal zone bbox (-10..10, 35..60)
        var result = await _repo.IsWithinCoastalZoneAsync(52.3676, 4.9041, CancellationToken.None);
        Assert.True(result);
    }

    [Fact]
    public async Task PragueIsNotInCoastalZone()
    {
        // Prague (14.43 E, 50.07 N) is outside the test coastal zone bbox (-10..10, 35..60)
        var result = await _repo.IsWithinCoastalZoneAsync(50.07, 14.43, CancellationToken.None);
        Assert.False(result);
    }

    [Fact]
    public async Task PragueIsInEurope()
    {
        var result = await _repo.IsWithinEuropeAsync(50.07, 14.43, CancellationToken.None);
        Assert.True(result);
    }
}
