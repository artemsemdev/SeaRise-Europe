using System.Text.Json;
using Microsoft.AspNetCore.Http.Json;
using Microsoft.Extensions.Options;

namespace SeaRise.Api;

internal static class StreamJsonResults
{
    public static IResult Ok<TValue>(TValue value) =>
        new StreamJsonResult<TValue>(value, StatusCodes.Status200OK);

    public static IResult Json<TValue>(TValue value, int statusCode) =>
        new StreamJsonResult<TValue>(value, statusCode);

    private sealed class StreamJsonResult<TValue> : IResult
    {
        private readonly TValue _value;
        private readonly int _statusCode;

        public StreamJsonResult(TValue value, int statusCode)
        {
            _value = value;
            _statusCode = statusCode;
        }

        public async Task ExecuteAsync(HttpContext httpContext)
        {
            var serializerOptions = httpContext.RequestServices
                .GetRequiredService<IOptions<JsonOptions>>()
                .Value
                .SerializerOptions;

            httpContext.Response.StatusCode = _statusCode;
            httpContext.Response.ContentType = "application/json; charset=utf-8";

            await JsonSerializer.SerializeAsync(
                httpContext.Response.Body,
                _value,
                serializerOptions,
                httpContext.RequestAborted);
        }
    }
}
