using SeaRise.Domain.Models;
using static SeaRise.Domain.Models.GeographyClassification;

namespace SeaRise.Domain.Logic;

public static class ResultStateDeterminator
{
    public static ResultState Determine(
        GeographyClassification geography,
        ExposureLayer? layer,
        bool? isExposed) => (geography, layer, isExposed) switch
        {
            (OutsideEurope, _, _) => ResultState.UnsupportedGeography,
            (InEuropeOutsideCoastalZone, _, _) => ResultState.OutOfScope,
            (InEuropeAndCoastalZone, null, _) => ResultState.DataUnavailable,
            (InEuropeAndCoastalZone, _, true) => ResultState.ModeledExposureDetected,
            (InEuropeAndCoastalZone, _, false) => ResultState.NoModeledExposureDetected,
            _ => ResultState.DataUnavailable // safe fallback
        };
}
