namespace SeaRise.Api.Dtos;

public record ErrorResponse(string RequestId, ErrorDetail Error);

public record ErrorDetail(string Code, string Message, string? Field = null);
