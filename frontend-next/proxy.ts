/**
 * Next.js Proxy (formerly middleware) — 按路径分级注入后端凭据。
 *
 * ## 为什么不再全路径注入管理员密钥
 *
 * 此前 matcher 是 `['/api/:path*']` 且无条件 `set('X-API-Key', apiKey)`，
 * 于是**任何能触达本服务的请求都是管理员**——包括未登录访客。后端
 * `ADMIN_ONLY_PREFIXES` 那套双令牌分级在这条路径上完全失效，因为前端
 * 根本没有"匿名"这一档。公网部署等于零鉴权。
 *
 * 现在分两档：
 *
 * - **管理动作**（`ADMIN_PREFIXES` / `ADMIN_METHOD_RULES`，与后端
 *   `app/auth.py` 逐项对齐）→ 注入 `X-API-Key`
 * - **其余读请求** → 注入后端签发的**匿名 token**（`Bearer`）
 *
 * ## 匿名 token 为什么在服务端取
 *
 * 后端中间件在 `settings.api_key` 非空时要求**任何**请求都带凭据，
 * 「非管理员」不等于「免鉴权」——匿名 token 也是一种凭据
 * （实测：不带任何头访问 `/api/v1/public-config` 得 401，不是 200）。
 *
 * 由代理在服务端换取并缓存，浏览器完全不接触任何凭据，客户端
 * `lib/api.ts` 的 `apiFetch` 一行都不用改。
 *
 * Next.js 16: middleware → proxy 重命名（codemod 提示）。
 */
import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

/**
 * 整前缀管理员专属，需与后端 `app/auth.py::ADMIN_ONLY_PREFIXES` 保持一致。
 *
 * 这里写的是**去掉 `/api/v1` 之后**的路径片段，因为 proxy 看到的是
 * 浏览器发出的 `/api/v1/...`，与后端判定用的完整路径同形，直接前缀匹配即可。
 *
 * `re-score` 保留：后端没有对应路由，但前缀在鉴权表里（打过去会先 403）。
 * 两边保持一致比"只列真实存在的路由"更重要——漏一项就是一个静默的越权口子。
 */
const ADMIN_PREFIXES = [
  '/api/v1/run',
  '/api/v1/re-score',
  '/api/v1/quarantine',
  '/api/v1/export',
  '/api/v1/import',
  '/api/v1/settings',
  '/api/v1/archive',
  '/api/v1/scheduler',
  '/api/v1/notify',
  '/api/v1/watched-wallets',
];

/**
 * 按方法受限的路径，对齐后端 `ADMIN_ONLY_METHOD_RULES`：
 * 同一路径读开放、写受限，前缀匹配表达不了。
 */
const ADMIN_METHOD_RULES: { methods: string[]; test: (p: string) => boolean }[] = [
  {
    methods: ['POST', 'PATCH', 'PUT', 'DELETE'],
    test: (p) => p === '/api/v1/collections' || p.startsWith('/api/v1/collections/'),
  },
  {
    methods: ['POST', 'PATCH', 'PUT', 'DELETE'],
    // /api/v1/projects/{id}/funding —— 通配段在路径中间
    test: (p) => /^\/api\/v1\/projects\/[^/]+\/funding(\/|$)/.test(p),
  },
];

function requiresAdmin(method: string, path: string): boolean {
  if (ADMIN_PREFIXES.some((prefix) => path.startsWith(prefix))) return true;
  const m = method.toUpperCase();
  return ADMIN_METHOD_RULES.some((rule) => rule.methods.includes(m) && rule.test(path));
}

/**
 * 匿名 token 的服务端缓存。
 *
 * 每个请求都去换一次 token 会让后端多承受一倍 QPS，而 token 有效期是 3 天
 * （后端 `expires_in` 259200 秒）。这里按 `expires_in` 缓存并留 5 分钟余量，
 * 避免在临界点用一个刚过期的 token。
 *
 * 模块级变量在 Next.js 的每个服务端实例里各存一份——这是可接受的：
 * 多实例只是各自多换一次 token，没有正确性问题（token 是无状态签名的）。
 */
let cachedAnonToken: { token: string; expiresAt: number } | null = null;
let inflight: Promise<string | null> | null = null;

const ANON_TOKEN_SAFETY_MARGIN_MS = 5 * 60 * 1000;

async function getAnonymousToken(requestOrigin: string): Promise<string | null> {
  const now = Date.now();
  if (cachedAnonToken && cachedAnonToken.expiresAt > now) {
    return cachedAnonToken.token;
  }
  // 并发去重：首屏往往同时发多个请求，没有这一步会同时打出去 N 个换 token 请求
  if (inflight) return inflight;

  inflight = (async () => {
    try {
      // ⚠️ 不能用 request.nextUrl.origin：它来自浏览器的 Host（也就是公网域名）。
      // 在容器里 fetch 自己的公网域名会走 DNS → 外网/负载均衡 → nginx → Next，
      // 依赖公网回环和 TLS，任一环节不支持就 catch 并退化为裸请求 → 全站 401。
      //
      // `API_PROXY_TARGET` 是同一台 Next 服务用来 rewrite /api 的后端内网地址
      // （生产 compose: http://web:8002）。直连它既少一圈网络也不把凭据换取
      // 绑死在公网 DNS 上；开发未配置时才回退 requestOrigin，保留 npm run dev。
      const backendOrigin = (process.env.API_PROXY_TARGET || requestOrigin).replace(/\/$/, '');
      const res = await fetch(`${backendOrigin}/api/v1/auth/anonymous`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        cache: 'no-store',
      });
      if (!res.ok) return null;
      const body = (await res.json()) as { access_token?: string; expires_in?: number };
      const token = body.access_token;
      if (!token) return null;
      const ttlMs = Math.max(0, (body.expires_in ?? 0) * 1000 - ANON_TOKEN_SAFETY_MARGIN_MS);
      cachedAnonToken = { token, expiresAt: Date.now() + ttlMs };
      return token;
    } catch {
      // 换不到 token 不能让页面直接崩：放行让请求裸奔到后端拿 401，
      // 前端各页面对失败请求已有降级处理。把 502 变成 401 更好定位问题。
      return null;
    } finally {
      inflight = null;
    }
  })();

  return inflight;
}

export async function proxy(request: NextRequest) {
  const apiKey = process.env.BACKEND_API_KEY || process.env.API_KEY;

  // 后端 API_KEY 为空时是 MVP 无鉴权模式，不注入任何头
  if (!apiKey) {
    return NextResponse.next();
  }

  // 客户端已自带凭据则不覆盖。注意浏览器可以任意设这个头，但那只会让请求
  // 拿到 401 —— 拿不到比预期更高的权限，所以这条短路是安全的。
  if (request.headers.get('X-API-Key') || request.headers.get('Authorization')) {
    return NextResponse.next();
  }

  const { pathname } = request.nextUrl;

  // 换 token 的端点自己必须放行，否则代理会递归：
  // 拦到它 → 去换 token → 又发一次这个请求 → 再被拦到 → …
  // 它在后端 PUBLIC_PREFIXES 里，本来就不需要凭据。
  if (pathname.startsWith('/api/v1/auth/')) {
    return NextResponse.next();
  }

  const requestHeaders = new Headers(request.headers);

  if (requiresAdmin(request.method, pathname)) {
    requestHeaders.set('X-API-Key', apiKey);
  } else {
    const token = await getAnonymousToken(request.nextUrl.origin);
    if (token) {
      requestHeaders.set('Authorization', `Bearer ${token}`);
    }
  }

  return NextResponse.next({ request: { headers: requestHeaders } });
}

export const config = {
  // 仅拦截 API 路径；/health 在后端 PUBLIC_PREFIXES 中，不需要鉴权
  matcher: ['/api/:path*'],
};
