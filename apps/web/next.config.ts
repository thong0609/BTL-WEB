import type { NextConfig } from "next";

const gateway = new URL(process.env.GATEWAY_URL ?? "http://127.0.0.1:3000");
if (
  !["http:", "https:"].includes(gateway.protocol) ||
  gateway.username || gateway.password || gateway.search || gateway.hash ||
  gateway.pathname !== "/"
) {
  throw new Error("GATEWAY_URL must be an HTTP(S) origin without credentials or path");
}

const config: NextConfig = {
  output: "standalone",
  async rewrites() {
    return {
      beforeFiles: [{
        source: "/api/v1/:path*",
        destination: `${gateway.origin}/api/v1/:path*`,
      }],
    };
  },
};

export default config;
