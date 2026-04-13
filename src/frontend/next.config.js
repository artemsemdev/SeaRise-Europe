/** @type {import('next').NextConfig} */

const tilerBaseUrl = process.env.NEXT_PUBLIC_TILER_BASE_URL || "";
const tilerOrigin = tilerBaseUrl
  ? new URL(tilerBaseUrl).origin
  : "http://localhost:8000";

// Server-side proxy target for /v1/* API calls. The browser always hits the
// frontend origin (same-origin satisfies CSP 'self'); Next rewrites forward
// those requests to the API. next.config.js is evaluated at build time, so
// this value is baked into the image. The default matches the docker compose
// service name. For plain `next dev` outside docker, set API_INTERNAL_URL
// (e.g. http://localhost:8080) in the build env.
const apiInternalUrl = process.env.API_INTERNAL_URL || "http://api:8080";

const nextConfig = {
  output: "standalone",
  async rewrites() {
    return [
      {
        source: "/v1/:path*",
        destination: `${apiInternalUrl}/v1/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/:path*",
        headers: [
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "X-Frame-Options", value: "DENY" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          {
            key: "Strict-Transport-Security",
            value: "max-age=63072000; includeSubDomains; preload",
          },
          {
            key: "Permissions-Policy",
            value: "geolocation=(), camera=(), microphone=()",
          },
          {
            key: "Content-Security-Policy",
            value: [
              "default-src 'self'",
              "script-src 'self' 'unsafe-eval' 'unsafe-inline'",
              "style-src 'self' 'unsafe-inline'",
              `img-src 'self' blob: data: https://*.atlas.microsoft.com ${tilerOrigin}`,
              `connect-src 'self' https://*.atlas.microsoft.com ${tilerOrigin}`,
              "worker-src 'self' blob:",
              "child-src 'self' blob:",
              "font-src 'self'",
            ].join("; "),
          },
        ],
      },
    ];
  },
};

module.exports = nextConfig;
