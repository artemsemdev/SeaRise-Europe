using SeaRise.Api.Dtos;
using SeaRise.Api.Validators;

namespace SeaRise.Api.Tests.Validators;

public class AssessRequestValidatorTests
{
    private readonly AssessRequestValidator _validator = new();

    [Trait("Category", "Unit")]
    [Fact]
    public void ValidRequest_Passes()
    {
        var result = _validator.Validate(new AssessRequest(52.37, 4.90, "ssp2-45", 2050));
        Assert.True(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void LatitudeOutOfRange_Fails()
    {
        var result = _validator.Validate(new AssessRequest(91.0, 4.90, "ssp2-45", 2050));
        Assert.False(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void NegativeLatitudeOutOfRange_Fails()
    {
        var result = _validator.Validate(new AssessRequest(-91.0, 4.90, "ssp2-45", 2050));
        Assert.False(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void LongitudeOutOfRange_Fails()
    {
        var result = _validator.Validate(new AssessRequest(52.37, 181.0, "ssp2-45", 2050));
        Assert.False(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void UnknownScenario_FailsWithCorrectCode()
    {
        var result = _validator.Validate(new AssessRequest(52.37, 4.90, "ssp-invalid", 2050));
        Assert.False(result.IsValid);
        Assert.Contains(result.Errors, e => e.ErrorCode == "UNKNOWN_SCENARIO");
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void UnknownHorizon_FailsWithCorrectCode()
    {
        var result = _validator.Validate(new AssessRequest(52.37, 4.90, "ssp2-45", 2060));
        Assert.False(result.IsValid);
        Assert.Contains(result.Errors, e => e.ErrorCode == "UNKNOWN_HORIZON");
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void MissingLatitude_Fails()
    {
        var result = _validator.Validate(new AssessRequest(null, 4.90, "ssp2-45", 2050));
        Assert.False(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void AllThreeValidScenarios_Pass()
    {
        Assert.True(_validator.Validate(new AssessRequest(0, 0, "ssp1-26", 2030)).IsValid);
        Assert.True(_validator.Validate(new AssessRequest(0, 0, "ssp2-45", 2050)).IsValid);
        Assert.True(_validator.Validate(new AssessRequest(0, 0, "ssp5-85", 2100)).IsValid);
    }
}
