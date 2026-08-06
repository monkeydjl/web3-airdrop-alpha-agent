/** @type {import('next').NextConfig} */
// API 代理目标：生产可通过 API_PROXY_TARGET 指定后端地址。
// 未显式配置时，仅在非生产环境回落到本地 127.0.0.1:8002，
// 避免把开发用的 loopback 代理打进生产构建导致线上 502。
const proxyTarget =
  process.env.API_PROXY_TARGET ||
  (process.env.NODE_ENV !== 'production' ? 'http://127.0.0.1:8002' : '');

const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    if (!proxyTarget) return [];
    return [
      {
        source: '/api/:path*',
        destination: `${proxyTarget}/api/:path*`,
      },
      // /health 在后端根路径而非 /api 下；不代理的话前端只能拿业务接口当探针，
      // 既不准确又白占限流配额
      {
        source: '/health',
        destination: `${proxyTarget}/health`,
      },
    ];
  },
};

module.exports = nextConfig;
