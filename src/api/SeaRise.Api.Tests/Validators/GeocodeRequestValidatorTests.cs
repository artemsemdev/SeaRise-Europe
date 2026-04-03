using SeaRise.Api.Dtos;
using SeaRise.Api.Validators;

namespace SeaRise.Api.Tests.Validators;

public class GeocodeRequestValidatorTests
{
    private readonly GeocodeRequestValidator _validator = new();

    [Trait("Category", "Unit")]
    [Fact]
    public void EmptyQuery_Fails()
    {
        var result = _validator.Validate(new GeocodeRequest(""));
        Assert.False(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void NullQuery_Fails()
    {
        var result = _validator.Validate(new GeocodeRequest(null));
        Assert.False(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void QueryOver200Chars_Fails()
    {
        var longQuery = new string('a', 201);
        var result = _validator.Validate(new GeocodeRequest(longQuery));
        Assert.False(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void ValidQuery_Passes()
    {
        var result = _validator.Validate(new GeocodeRequest("Amsterdam"));
        Assert.True(result.IsValid);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public void QueryExactly200Chars_Passes()
    {
        var query = new string('a', 200);
        var result = _validator.Validate(new GeocodeRequest(query));
        Assert.True(result.IsValid);
    }
}
