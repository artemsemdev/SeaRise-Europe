using FluentValidation;
using SeaRise.Api.Dtos;

namespace SeaRise.Api.Validators;

public class AssessRequestValidator : AbstractValidator<AssessRequest>
{
    private static readonly HashSet<int> ValidHorizonYears = new() { 2030, 2050, 2100 };
    private static readonly HashSet<string> ValidScenarioIds = new() { "ssp1-26", "ssp2-45", "ssp5-85" };

    public AssessRequestValidator()
    {
        RuleFor(x => x.Latitude)
            .NotNull().WithMessage("Latitude is required.")
            .InclusiveBetween(-90.0, 90.0).WithMessage("Latitude must be between -90 and 90.");

        RuleFor(x => x.Longitude)
            .NotNull().WithMessage("Longitude is required.")
            .InclusiveBetween(-180.0, 180.0).WithMessage("Longitude must be between -180 and 180.");

        RuleFor(x => x.ScenarioId)
            .NotEmpty().WithMessage("ScenarioId is required.")
            .Must(id => id != null && ValidScenarioIds.Contains(id))
            .WithErrorCode("UNKNOWN_SCENARIO")
            .WithMessage("Unknown scenario. Valid scenarios: ssp1-26, ssp2-45, ssp5-85.");

        RuleFor(x => x.HorizonYear)
            .NotNull().WithMessage("HorizonYear is required.")
            .Must(year => year.HasValue && ValidHorizonYears.Contains(year.Value))
            .WithErrorCode("UNKNOWN_HORIZON")
            .WithMessage("Unknown horizon year. Valid values: 2030, 2050, 2100.");
    }
}
