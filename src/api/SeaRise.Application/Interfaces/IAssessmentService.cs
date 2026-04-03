using SeaRise.Domain.Models;

namespace SeaRise.Application.Interfaces;

public interface IAssessmentService
{
    Task<AssessmentResult> AssessAsync(AssessmentQuery query, string requestId, CancellationToken ct);
}
