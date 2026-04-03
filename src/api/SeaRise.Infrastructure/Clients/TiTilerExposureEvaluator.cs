using System.Text.Json;
using Microsoft.Extensions.Logging;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Infrastructure.Clients;

public class TiTilerExposureEvaluator : IExposureEvaluator
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<TiTilerExposureEvaluator> _logger;

    public TiTilerExposureEvaluator(HttpClient httpClient, ILogger<TiTilerExposureEvaluator> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<bool> IsExposedAsync(double latitude, double longitude, ExposureLayer layer, CancellationToken ct)
    {
        var cogUrl = $"az://geospatial/{layer.BlobPath}";
        var url = $"/cog/point/{longitude},{latitude}?url={Uri.EscapeDataString(cogUrl)}";

        var response = await _httpClient.GetAsync(url, ct);
        response.EnsureSuccessStatusCode();

        var json = await response.Content.ReadAsStringAsync(ct);
        var result = JsonSerializer.Deserialize<TilerPointResponse>(json, JsonOptions);

        var pixelValue = result?.Values?.FirstOrDefault()?.FirstOrDefault();

        _logger.LogDebug("TilerQueryCompleted {PixelValue} {DurationMs}", pixelValue, 0);

        return pixelValue == 1;
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    private record TilerPointResponse
    {
        public List<List<int?>>? Values { get; init; }
    }
}
