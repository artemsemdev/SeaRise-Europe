/** @type {import('next').NextConfig} */

const tilerBaseUrl = process.env.NEXT_PUBLIC_TILER_BASE_URL || "";
const tilerOrigin = tilerBaseUrl
  ? new URL(tilerBaseUrl).origin
  : "http://localhost:8000";

const nextConfig = {
  output: "standalone",
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
