namespace SeaRise.Api.Dtos;

public record GeocodeResponse(string RequestId, IReadOnlyList<CandidateDto> Candidates);

public record CandidateDto(
    int Rank,
    string Label,
    string Country,
    double Latitude,
    double Longitude,
    string DisplayContext);
