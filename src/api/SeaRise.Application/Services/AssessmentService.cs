using Microsoft.Extensions.Logging;
using SeaRise.Application.Interfaces;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Logic;
using SeaRise.Domain.Models;

namespace SeaRise.Application.Services;

public class AssessmentService : IAssessmentService
{
    private readonly IGeographyRepository _geographyRepo;
    private readonly ILayerResolver _layerResolver;
    private readonly IExposureEvaluator _exposureEvaluator;
    private readonly IScenarioRepository _scenarioRepo;
    private readonly IMethodologyRepository _methodologyRepo;
    private readonly ILogger<AssessmentService> _logger;

    public AssessmentService(
        IGeographyRepository geographyRepo,
        ILayerResolver layerResolver,
        IExposureEvaluator exposureEvaluator,
        IScenarioRepository scenarioRepo,
        IMethodologyRepository methodologyRepo,
        ILogger<AssessmentService> logger)
    {
        _geographyRepo = geographyRepo;
        _layerResolver = layerResolver;
        _exposureEvaluator = exposureEvaluator;
        _scenarioRepo = scenarioRepo;
        _methodologyRepo = methodologyRepo;
        _logger = logger;
    }

    public async Task<AssessmentResult> AssessAsync(AssessmentQuery query, string requestId, CancellationToken ct)
    {
        var methodology = await _methodologyRepo.GetActiveAsync(ct);
        var scenarios = await _scenarioRepo.GetAllAsync(ct);
        var horizons = await _scenarioRepo.GetHorizonsAsync(ct);

        var scenario = scenarios.FirstOrDefault(s => s.Id == query.ScenarioId);
        var horizon = horizons.FirstOrDefault(h => h.Year == query.HorizonYear);

        var scenarioInfo = new ScenarioInfo(query.ScenarioId, scenario?.DisplayName ?? query.ScenarioId);
        var horizonInfo = new HorizonInfo(query.HorizonYear, horizon?.DisplayLabel ?? query.HorizonYear.ToString());

        // Run Europe and coastal zone checks in parallel
        var europeTask = _geographyRepo.IsWithinEuropeAsync(query.Latitude, query.Longitude, ct);
        var coastalTask = _geographyRepo.IsWithinCoastalZoneAsync(query.Latitude, query.Longitude, ct);
        await Task.WhenAll(europeTask, coastalTask);

        var isInEurope = europeTask.Result;
        var isInCoastalZone = coastalTask.Result;

        var geography = (isInEurope, isInCoastalZone) switch
        {
            (false, _) => GeographyClassification.OutsideEurope,
            (true, false) => GeographyClassification.InEuropeOutsideCoastalZone,
            (true, true) => GeographyClassification.InEuropeAndCoastalZone
        };

        _logger.LogDebug("GeographyCheckCompleted {Geography} {IsInEurope} {IsInCoastalZone}",
            geography.ToString(), isInEurope, isInCoastalZone);

        // Short-circuit: outside Europe or outside coastal zone
        if (geography != GeographyClassification.InEuropeAndCoastalZone)
        {
            var earlyState = ResultStateDeterminator.Determine(geography, null, null);
            return BuildResult(requestId, earlyState, query, scenarioInfo, horizonInfo, methodology.Version, null);
        }

        // Resolve layer
        var layer = await _layerResolver.ResolveAsync(query.ScenarioId, query.HorizonYear, ct);
        if (layer is null)
        {
            _logger.LogWarning("LayerNotFound {ScenarioId} {HorizonYear}", query.ScenarioId, query.HorizonYear);
            return BuildResult(requestId, ResultState.DataUnavailable, query, scenarioInfo, horizonInfo, methodology.Version, null);
        }

        _logger.LogDebug("LayerResolved {LayerId} {BlobPath}", layer.Id, layer.BlobPath);

        // Evaluate exposure
        var isExposed = await _exposureEvaluator.IsExposedAsync(query.Latitude, query.Longitude, layer, ct);
        var resultState = ResultStateDeterminator.Determine(geography, layer, isExposed);

        return BuildResult(requestId, resultState, query, scenarioInfo, horizonInfo, methodology.Version, layer);
    }

    private static AssessmentResult BuildResult(
        string requestId,
        ResultState resultState,
        AssessmentQuery query,
        ScenarioInfo scenario,
        HorizonInfo horizon,
        string methodologyVersion,
        ExposureLayer? layer)
    {
        string? tileUrlTemplate = null;
        LegendSpec? legendSpec = null;

        if (resultState == ResultState.ModeledExposureDetected && layer is not null)
        {
            var cogUrl = Uri.EscapeDataString($"az://geospatial/{layer.BlobPath}");
            tileUrlTemplate = $"/cog/tiles/{{z}}/{{x}}/{{y}}.png?url={cogUrl}&colormap_name=reds&rescale=0,1";
            legendSpec = new LegendSpec(new List<ColorStop>
            {
                new(Value: 1, Color: "#E85D04", Label: "Modeled exposure zone")
            });
        }

        return new AssessmentResult(
            RequestId: requestId,
            ResultState: resultState,
            Location: new LocationInfo(query.Latitude, query.Longitude),
            Scenario: scenario,
            Horizon: horizon,
            MethodologyVersion: methodologyVersion,
            LayerTileUrlTemplate: tileUrlTemplate,
            LegendSpec: legendSpec,
            GeneratedAt: DateTime.UtcNow);
    }
}
