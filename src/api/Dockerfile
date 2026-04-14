FROM mcr.microsoft.com/dotnet/sdk:8.0 AS build
WORKDIR /src

# Copy solution and project files for restore
COPY SeaRise.sln .
COPY SeaRise.Domain/SeaRise.Domain.csproj SeaRise.Domain/
COPY SeaRise.Application/SeaRise.Application.csproj SeaRise.Application/
COPY SeaRise.Infrastructure/SeaRise.Infrastructure.csproj SeaRise.Infrastructure/
COPY SeaRise.Api/SeaRise.Api.csproj SeaRise.Api/
RUN dotnet restore SeaRise.Api/SeaRise.Api.csproj

# Copy everything and publish
COPY . .
RUN dotnet publish SeaRise.Api/SeaRise.Api.csproj -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:8.0 AS runtime
WORKDIR /app

# curl is required by the container healthcheck in docker-compose.yml.
# The aspnet:8.0 base image does not include it.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

RUN addgroup --system --gid 1001 appgroup && \
    adduser --system --uid 1001 appuser

COPY --from=build --chown=appuser:appgroup /app/publish .

USER appuser
ENV ASPNETCORE_URLS=http://+:8080
EXPOSE 8080

ENTRYPOINT ["dotnet", "SeaRise.Api.dll"]
