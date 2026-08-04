using System.Text.Json;
using SeaRise.Domain.Logic;
using SeaRise.Domain.Models;
using static SeaRise.Domain.Models.GeographyClassification;

namespace SeaRise.Api.Tests.Domain;

public class SharedResultStateFixtureTests
{
    private static readonly ExposureLayer SampleLayer = new(
        Id: Guid.Parse("2e293120-b212-4b74-b139-8169893865bb"),
        ScenarioId: "ssp2-45",
        HorizonYear: 2050,
        MethodologyVersion: "legacy-v1.0-characterization",
        BlobPath: "characterization/not-a-release.tif",
        LegendColormap: null);

    public static IEnumerable<object[]> SharedCases()
    {
        var path = Path.Combine(AppContext.BaseDirectory, "Fixtures", "five-state-characterization-v1.json");
        var fixture = JsonSerializer.Deserialize<SharedFixture>(
            File.ReadAllText(path),
            new JsonSerializerOptions { PropertyNameCaseInsensitive = true });

        return fixture!.Cases.Select(testCase => new object[] { testCase });
    }

    [Trait("Category", "Unit")]
    [Theory]
    [MemberData(nameof(SharedCases))]
    public void LegacyDeterminator_MatchesSharedCharacterization(SharedCase testCase)
    {
        var geography = testCase.Input.InEurope switch
        {
            false => OutsideEurope,
            true when testCase.Input.InCoastalZone is false => InEuropeOutsideCoastalZone,
            _ => InEuropeAndCoastalZone
        };
        // The legacy enum has no "coastal membership unknown" value. Compare
        // its fail-closed no-layer path when the target fixture represents it.
        var layer = testCase.Input.ClassValue is null || testCase.Input.InCoastalZone is null
            ? null
            : SampleLayer;
        var exposed = testCase.Input.ClassValue switch
        {
            1 => true,
            0 => false,
            _ => (bool?)null
        };

        var actual = ResultStateDeterminator.Determine(geography, layer, exposed);

        Assert.Equal(testCase.ExpectedState, actual.ToString());
    }

    public sealed record SharedFixture(IReadOnlyList<SharedCase> Cases);

    public sealed record SharedCase(string Id, SharedInput Input, string ExpectedState)
    {
        public override string ToString() => Id;
    }

    public sealed record SharedInput(bool InEurope, bool? InCoastalZone, int? ClassValue);
}
