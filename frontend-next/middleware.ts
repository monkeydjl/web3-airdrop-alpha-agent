/**
 * Next.js Middleware — 为 /api/* 请求注入后端鉴权头。
 *
 * 后端 APIKeyMiddleware 在 settings.api_key 非空时要求 X-API-Key。
 * 本中间件从服务端环境变量 BACKEND_API_KEY（或 API_KEY）读取密钥，
 * 注入到请求头后再由 rewrite 代理到后端，密钥不暴露到浏览器。
 *
 * 若后端未设置 API_KEY（本地无鉴权模式），本中间件不注入任何头，
 * 请求照常通过。
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

export function middleware(request: NextRequest) {
  // 优先 BACKEND_API_KEY，其次 API_KEY（与后端共用同一 .env 时）
  const apiKey = process.env.BACKEND_API_KEY || process.env.API_KEY;
  if (!apiKey) {
    return NextResponse.next();
  }

  // 避免重复设置（客户端 apiFetch 也可能带 X-API-Key）
  if (request.headers.get('X-API-Key')) {
    return NextResponse.next();
  }

  const requestHeaders = new Headers(request.headers);
  requestHeaders.set('X-API-Key', apiKey);

  return NextResponse.next({
    request: {
      headers: requestHeaders,
    },
  });
}

export const config = {
  // 仅拦截 API 路径；/health 在后端 PUBLIC_PREFIXES 中，不需要鉴权
  matcher: ['/api/:path*'],
};
