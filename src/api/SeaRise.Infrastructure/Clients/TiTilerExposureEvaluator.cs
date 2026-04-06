using System.Diagnostics;
using System.Text.Json;
using System.Text.RegularExpressions;
using Microsoft.Extensions.Logging;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Infrastructure.Clients;

public partial class TiTilerExposureEvaluator : IExposureEvaluator
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<TiTilerExposureEvaluator> _logger;

    [GeneratedRegex(@"^[a-z0-9][a-z0-9/_\-\.]*\.tif$", RegexOptions.Compiled)]
    private static partial Regex BlobPathPattern();

    public TiTilerExposureEvaluator(HttpClient httpClient, ILogger<TiTilerExposureEvaluator> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<bool> IsExposedAsync(double latitude, double longitude, ExposureLayer layer, CancellationToken ct)
    {
        var sw = Stopwatch.StartNew();

        if (!BlobPathPattern().IsMatch(layer.BlobPath) || layer.BlobPath.Contains(".."))
        {
            _logger.LogError("InvalidBlobPath {BlobPath}", layer.BlobPath);
            throw new InvalidOperationException($"Layer blob path failed validation: {layer.BlobPath}");
        }

        var cogUrl = $"az://geospatial/{layer.BlobPath}";
        var url = $"/cog/point/{longitude},{latitude}?url={Uri.EscapeDataString(cogUrl)}";

        var response = await _httpClient.GetAsync(url, ct);
        response.EnsureSuccessStatusCode();

        var json = await response.Content.ReadAsStringAsync(ct);
        var result = JsonSerializer.Deserialize<TilerPointResponse>(json, JsonOptions);

        var pixelValue = result?.Values?.FirstOrDefault()?.FirstOrDefault();

        sw.Stop();
        _logger.LogDebug("TilerQueryCompleted {PixelValue} {DurationMs}", pixelValue, sw.ElapsedMilliseconds);

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
