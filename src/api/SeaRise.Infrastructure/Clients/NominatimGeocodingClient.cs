using System.Text.Json;
using Microsoft.Extensions.Logging;
using SeaRise.Domain.Exceptions;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Infrastructure.Clients;

public class NominatimGeocodingClient : IGeocodingService
{
    private readonly HttpClient _httpClient;
    private readonly ILogger<NominatimGeocodingClient> _logger;
    private const int MaxCandidates = 5;

    public NominatimGeocodingClient(HttpClient httpClient, ILogger<NominatimGeocodingClient> logger)
    {
        _httpClient = httpClient;
        _logger = logger;
    }

    public async Task<IReadOnlyList<GeocodingCandidate>> GeocodeAsync(string query, CancellationToken cancellationToken)
    {
        try
        {
            var url = $"/search?q={Uri.EscapeDataString(query)}&format=jsonv2&limit={MaxCandidates}&addressdetails=1";
            var response = await _httpClient.GetAsync(url, cancellationToken);
            response.EnsureSuccessStatusCode();

            var json = await response.Content.ReadAsStringAsync(cancellationToken);
            var results = JsonSerializer.Deserialize<List<NominatimResult>>(json, JsonOptions);

            if (results is null || results.Count == 0)
                return Array.Empty<GeocodingCandidate>();

            return results
                .Take(MaxCandidates)
                .Select((r, index) => new GeocodingCandidate(
                    Rank: index + 1,
                    Label: r.DisplayName ?? "",
                    Country: r.Address?.CountryCode?.ToUpperInvariant() ?? "",
                    Latitude: double.TryParse(r.Lat, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var lat) ? lat : 0,
                    Longitude: double.TryParse(r.Lon, System.Globalization.NumberStyles.Float, System.Globalization.CultureInfo.InvariantCulture, out var lng) ? lng : 0,
                    DisplayContext: BuildDisplayContext(r.Address)))
                .ToList();
        }
        catch (HttpRequestException ex)
        {
            _logger.LogError("GeocodeProviderError {StatusCode}", ex.StatusCode);
            throw new GeocodingProviderException("Upstream geocoding provider unavailable", ex);
        }
        catch (TaskCanceledException) when (!cancellationToken.IsCancellationRequested)
        {
            throw new GeocodingProviderException("Geocoding provider request timed out");
        }
    }

    private static string BuildDisplayContext(NominatimAddress? address)
    {
        if (address is null) return "";
        var parts = new List<string>();
        if (!string.IsNullOrEmpty(address.State)) parts.Add(address.State);
        if (!string.IsNullOrEmpty(address.Country)) parts.Add(address.Country);
        return string.Join(", ", parts);
    }

    private static readonly JsonSerializerOptions JsonOptions = new()
    {
        PropertyNamingPolicy = JsonNamingPolicy.SnakeCaseLower
    };

    private record NominatimResult
    {
        public string? Lat { get; init; }
        public string? Lon { get; init; }
        public string? DisplayName { get; init; }
        public NominatimAddress? Address { get; init; }
    }

    private record NominatimAddress
    {
        public string? State { get; init; }
        public string? Country { get; init; }
        public string? CountryCode { get; init; }
    }
}
