namespace SeaRise.Domain.Exceptions;

public class GeocodingProviderException : Exception
{
    public GeocodingProviderException(string message) : base(message) { }
    public GeocodingProviderException(string message, Exception innerException) : base(message, innerException) { }
}
