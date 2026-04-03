using FluentValidation;
using SeaRise.Api.Dtos;

namespace SeaRise.Api.Validators;

public class GeocodeRequestValidator : AbstractValidator<GeocodeRequest>
{
    public GeocodeRequestValidator()
    {
        RuleFor(x => x.Query)
            .NotEmpty().WithMessage("Query must be between 1 and 200 characters.")
            .MaximumLength(200).WithMessage("Query must be between 1 and 200 characters.");
    }
}
