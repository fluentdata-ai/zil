/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const docsDestination =
      process.env.DOCS_URL || "https://zil-docs.vercel.app";
    return [
      { source: "/docs", destination: `${docsDestination}/docs` },
      { source: "/docs/:path+", destination: `${docsDestination}/docs/:path+` },
    ];
  },
};

module.exports = nextConfig;
