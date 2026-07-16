/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Dev proxy to local FastAPI (8002)
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: 'http://127.0.0.1:8002/api/:path*',
      },
    ];
  },
};

module.exports = nextConfig;
