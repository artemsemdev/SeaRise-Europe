using Microsoft.Extensions.Logging;
using Moq;
using SeaRise.Application.Services;
using SeaRise.Domain.Interfaces;
using SeaRise.Domain.Models;

namespace SeaRise.Api.Tests.Application;

public class AssessmentServiceTests
{
    private readonly Mock<IGeographyRepository> _geographyRepo = new();
    private readonly Mock<ILayerResolver> _layerResolver = new();
    private readonly Mock<IExposureEvaluator> _exposureEvaluator = new();
    private readonly Mock<IScenarioRepository> _scenarioRepo = new();
    private readonly Mock<IMethodologyRepository> _methodologyRepo = new();
    private readonly Mock<ILogger<AssessmentService>> _logger = new();
    private readonly AssessmentService _sut;

    private static readonly MethodologyVersion ActiveMethodology = new(
        "v1.0", true, "IPCC AR6", "Copernicus DEM", "what it does",
        "limitations", "resolution note", "threshold desc", DateTime.UtcNow);

    private static readonly IReadOnlyList<Scenario> Scenarios = new List<Scenario>
    {
        new("ssp2-45", "Intermediate emissions (SSP2-4.5)", "description", 2, true)
    };

    private static readonly IReadOnlyList<Horizon> Horizons = new List<Horizon>
    {
        new(2050, "2050", true, 2)
    };

    private static readonly ExposureLayer SampleLayer = new(
        Guid.NewGuid(), "ssp2-45", 2050, "v1.0", "layers/v1.0/ssp2-45/2050.tif", null);

    public AssessmentServiceTests()
    {
        _methodologyRepo.Setup(m => m.GetActiveAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(ActiveMethodology);
        _scenarioRepo.Setup(m => m.GetAllAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(Scenarios);
        _scenarioRepo.Setup(m => m.GetHorizonsAsync(It.IsAny<CancellationToken>()))
            .ReturnsAsync(Horizons);

        _sut = new AssessmentService(
            _geographyRepo.Object,
            _layerResolver.Object,
            _exposureEvaluator.Object,
            _scenarioRepo.Object,
            _methodologyRepo.Object,
            _logger.Object);
    }

    private AssessmentQuery MakeQuery(double lat = 52.37, double lng = 4.90) =>
        new(lat, lng, "ssp2-45", 2050);

    [Trait("Category", "Unit")]
    [Fact]
    public async Task AssessAsync_OutsideEurope_ReturnsUnsupportedGeography_WithoutCallingLayerOrExposure()
    {
        _geographyRepo.Setup(g => g.IsWithinEuropeAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);
        _geographyRepo.Setup(g => g.IsWithinCoastalZoneAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);

        var result = await _sut.AssessAsync(MakeQuery(40.71, -74.00), "req_test1", CancellationToken.None);

        Assert.Equal(ResultState.UnsupportedGeography, result.ResultState);
        _layerResolver.Verify(l => l.ResolveAsync(It.IsAny<string>(), It.IsAny<int>(), It.IsAny<CancellationToken>()), Times.Never);
        _exposureEvaluator.Verify(e => e.IsExposedAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<ExposureLayer>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public async Task AssessAsync_InEuropeOutsideCoastal_ReturnsOutOfScope_WithoutCallingLayerOrExposure()
    {
        _geographyRepo.Setup(g => g.IsWithinEuropeAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);
        _geographyRepo.Setup(g => g.IsWithinCoastalZoneAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);

        var result = await _sut.AssessAsync(MakeQuery(50.07, 14.43), "req_test2", CancellationToken.None);

        Assert.Equal(ResultState.OutOfScope, result.ResultState);
        _layerResolver.Verify(l => l.ResolveAsync(It.IsAny<string>(), It.IsAny<int>(), It.IsAny<CancellationToken>()), Times.Never);
        _exposureEvaluator.Verify(e => e.IsExposedAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<ExposureLayer>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public async Task AssessAsync_CoastalNoLayer_ReturnsDataUnavailable_WithoutCallingExposure()
    {
        _geographyRepo.Setup(g => g.IsWithinEuropeAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);
        _geographyRepo.Setup(g => g.IsWithinCoastalZoneAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);
        _layerResolver.Setup(l => l.ResolveAsync(It.IsAny<string>(), It.IsAny<int>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync((ExposureLayer?)null);

        var result = await _sut.AssessAsync(MakeQuery(), "req_test3", CancellationToken.None);

        Assert.Equal(ResultState.DataUnavailable, result.ResultState);
        _exposureEvaluator.Verify(e => e.IsExposedAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<ExposureLayer>(), It.IsAny<CancellationToken>()), Times.Never);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public async Task AssessAsync_CoastalWithLayer_Exposed_ReturnsModeledExposureDetected()
    {
        _geographyRepo.Setup(g => g.IsWithinEuropeAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);
        _geographyRepo.Setup(g => g.IsWithinCoastalZoneAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);
        _layerResolver.Setup(l => l.ResolveAsync("ssp2-45", 2050, It.IsAny<CancellationToken>()))
            .ReturnsAsync(SampleLayer);
        _exposureEvaluator.Setup(e => e.IsExposedAsync(It.IsAny<double>(), It.IsAny<double>(), SampleLayer, It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);

        var result = await _sut.AssessAsync(MakeQuery(), "req_test4", CancellationToken.None);

        Assert.Equal(ResultState.ModeledExposureDetected, result.ResultState);
        Assert.NotNull(result.LayerTileUrlTemplate);
        Assert.NotNull(result.LegendSpec);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public async Task AssessAsync_CoastalWithLayer_NotExposed_ReturnsNoModeledExposureDetected()
    {
        _geographyRepo.Setup(g => g.IsWithinEuropeAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);
        _geographyRepo.Setup(g => g.IsWithinCoastalZoneAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(true);
        _layerResolver.Setup(l => l.ResolveAsync("ssp2-45", 2050, It.IsAny<CancellationToken>()))
            .ReturnsAsync(SampleLayer);
        _exposureEvaluator.Setup(e => e.IsExposedAsync(It.IsAny<double>(), It.IsAny<double>(), SampleLayer, It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);

        var result = await _sut.AssessAsync(MakeQuery(), "req_test5", CancellationToken.None);

        Assert.Equal(ResultState.NoModeledExposureDetected, result.ResultState);
        Assert.Null(result.LayerTileUrlTemplate);
    }

    [Trait("Category", "Unit")]
    [Fact]
    public async Task AssessAsync_AlwaysIncludesMethodologyVersion()
    {
        _geographyRepo.Setup(g => g.IsWithinEuropeAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);
        _geographyRepo.Setup(g => g.IsWithinCoastalZoneAsync(It.IsAny<double>(), It.IsAny<double>(), It.IsAny<CancellationToken>()))
            .ReturnsAsync(false);

        var result = await _sut.AssessAsync(MakeQuery(), "req_test6", CancellationToken.None);

        Assert.Equal("v1.0", result.MethodologyVersion);
        Assert.NotNull(result.Scenario);
        Assert.NotNull(result.Horizon);
        Assert.NotEqual(default, result.GeneratedAt);
    }
}
