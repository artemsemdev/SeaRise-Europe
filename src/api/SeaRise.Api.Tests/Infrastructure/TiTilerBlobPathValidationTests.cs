using Microsoft.Extensions.Logging;
using Moq;
using Moq.Protected;
using SeaRise.Domain.Models;
using SeaRise.Infrastructure.Clients;

namespace SeaRise.Api.Tests.Infrastructure;

[Trait("Category", "Unit")]
public class TiTilerBlobPathValidationTests
{
    private readonly Mock<ILogger<TiTilerExposureEvaluator>> _logger = new();

    private TiTilerExposureEvaluator CreateEvaluator(HttpMessageHandler? handler = null)
    {
        handler ??= CreateMockHandler();
        var httpClient = new HttpClient(handler) { BaseAddress = new Uri("http://localhost:8000") };
        return new TiTilerExposureEvaluator(httpClient, _logger.Object);
    }

    private static HttpMessageHandler CreateMockHandler()
    {
        var mock = new Mock<HttpMessageHandler>();
        mock.Protected()
            .Setup<Task<HttpResponseMessage>>("SendAsync",
                ItExpr.IsAny<HttpRequestMessage>(),
                ItExpr.IsAny<CancellationToken>())
            .ReturnsAsync(new HttpResponseMessage(System.Net.HttpStatusCode.OK)
            {
                Content = new StringContent("{\"coordinates\":[4.9,52.37],\"values\":[1.0],\"band_names\":[\"b1\"]}")
            });
        return mock.Object;
    }

    [Theory]
    [InlineData("layers/v1.0/ssp2-45/2050.tif")]
    [InlineData("layers/v1.0/ssp1-26/2030.tif")]
    [InlineData("layers/v1.0/ssp5-85/2100.tif")]
    [InlineData("data/europe-coastal.tif")]
    public async Task ValidBlobPath_DoesNotThrow(string blobPath)
    {
        var evaluator = CreateEvaluator();
        var layer = new ExposureLayer(Guid.NewGuid(), "ssp2-45", 2050, "v1.0", blobPath, null);

        var result = await evaluator.IsExposedAsync(52.37, 4.90, layer, CancellationToken.None);

        Assert.True(result);
    }

    [Theory]
    [InlineData("../../../etc/passwd")]
    [InlineData("layers/../../../secrets.tif")]
    [InlineData("http://evil.com/payload.tif")]
    [InlineData("")]
    [InlineData("layers/v1.0/ssp2-45/2050.exe")]
    [InlineData("layers/v1.0/ssp2-45/2050")]
    [InlineData("/absolute/path/file.tif")]
    [InlineData("LAYERS/V1.0/SSP2-45/2050.TIF")]
    public async Task InvalidBlobPath_ThrowsInvalidOperationException(string blobPath)
    {
        var evaluator = CreateEvaluator();
        var layer = new ExposureLayer(Guid.NewGuid(), "ssp2-45", 2050, "v1.0", blobPath, null);

        await Assert.ThrowsAsync<InvalidOperationException>(
            () => evaluator.IsExposedAsync(52.37, 4.90, layer, CancellationToken.None));
    }
}
