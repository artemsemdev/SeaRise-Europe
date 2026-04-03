using SeaRise.Domain.Logic;
using SeaRise.Domain.Models;
using static SeaRise.Domain.Models.GeographyClassification;

namespace SeaRise.Api.Tests.Domain;

public class ResultStateDeterminatorTests
{
    private static readonly ExposureLayer SampleLayer = new(
        Id: Guid.NewGuid(),
        ScenarioId: "ssp2-45",
        HorizonYear: 2050,
        MethodologyVersion: "v1.0",
        BlobPath: "layers/v1.0/ssp2-45/2050.tif",
        LegendColormap: null);

    [Trait("Category", "Unit")]
    [Theory]
    [MemberData(nameof(AllCombinations))]
    public void Determine_AllCombinations_ReturnExpectedState(
        GeographyClassification geography,
        ExposureLayer? layer,
        bool? isExposed,
        ResultState expected)
    {
        var result = ResultStateDeterminator.Determine(geography, layer, isExposed);
        Assert.Equal(expected, result);
    }

    public static IEnumerable<object?[]> AllCombinations()
    {
        // Outside Europe — always UnsupportedGeography regardless of layer/exposure
        yield return new object?[] { OutsideEurope, SampleLayer, true, ResultState.UnsupportedGeography };
        yield return new object?[] { OutsideEurope, SampleLayer, false, ResultState.UnsupportedGeography };
        yield return new object?[] { OutsideEurope, null, null, ResultState.UnsupportedGeography };

        // In Europe, outside coastal zone — always OutOfScope
        yield return new object?[] { InEuropeOutsideCoastalZone, SampleLayer, true, ResultState.OutOfScope };
        yield return new object?[] { InEuropeOutsideCoastalZone, null, null, ResultState.OutOfScope };

        // In coastal zone, no layer — DataUnavailable
        yield return new object?[] { InEuropeAndCoastalZone, null, null, ResultState.DataUnavailable };

        // In coastal zone, layer present, exposed
        yield return new object?[] { InEuropeAndCoastalZone, SampleLayer, true, ResultState.ModeledExposureDetected };

        // In coastal zone, layer present, not exposed
        yield return new object?[] { InEuropeAndCoastalZone, SampleLayer, false, ResultState.NoModeledExposureDetected };
    }
}
