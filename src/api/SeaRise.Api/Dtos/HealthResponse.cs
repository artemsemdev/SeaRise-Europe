namespace SeaRise.Api.Dtos;

public record HealthResponse(string Status, HealthComponentsDto? Components, DateTime Timestamp);

public record HealthComponentsDto(string Postgres, string BlobStorage);
