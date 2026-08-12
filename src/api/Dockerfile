FROM mcr.microsoft.com/dotnet/sdk:8.0@sha256:e2f26f26169fd10d6f1b426e01c97397717b32e9d5ab4ee4a7d5497ed9403007 AS build
WORKDIR /src

# Copy solution and project files for restore
COPY SeaRise.sln .
COPY Directory.Build.props .
COPY SeaRise.Domain/SeaRise.Domain.csproj SeaRise.Domain/packages.lock.json SeaRise.Domain/
COPY SeaRise.Application/SeaRise.Application.csproj SeaRise.Application/packages.lock.json SeaRise.Application/
COPY SeaRise.Infrastructure/SeaRise.Infrastructure.csproj SeaRise.Infrastructure/packages.lock.json SeaRise.Infrastructure/
COPY SeaRise.Api/SeaRise.Api.csproj SeaRise.Api/packages.lock.json SeaRise.Api/
RUN dotnet restore SeaRise.Api/SeaRise.Api.csproj --locked-mode

# Copy everything and publish
COPY . .
RUN dotnet publish SeaRise.Api/SeaRise.Api.csproj -c Release -o /app/publish

FROM mcr.microsoft.com/dotnet/aspnet:8.0@sha256:fd7596eaea7ad453fe7ac16724a3c9ae36edcda894ba13743d6a5c83d6a3b36d AS runtime
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
