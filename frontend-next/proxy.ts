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
 *   `app/auth.py` 逐项对齐）→ 严禁代理自动代签；由客户端显式出示凭据，未带凭证交由后端阻断（401/403，修复 P1-5）
 * - **其余公开/读取请求** → 代理注入服务端换取的**匿名 token**（`Bearer`），免去普通访客鉴权门槛
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
  '/api/v1/ops',
  '/api/v1/llm',
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
  {
    methods: ['POST', 'PATCH', 'PUT', 'DELETE'],
    // /api/v1/projects/{id}/unhide —— 撤销 launch_review 隐藏，管理员动作
    test: (p) => /^\/api\/v1\/projects\/[^/]+\/unhide(\/|$)/.test(p),
  },
  {
    methods: ['POST', 'PATCH', 'PUT', 'DELETE'],
    // /api/v1/project-identity —— 全局身份数据，写操作仅管理员
    test: (p) => p === '/api/v1/project-identity' || p.startsWith('/api/v1/project-identity/'),
  },
  {
    methods: ['POST', 'PATCH', 'PUT', 'DELETE'],
    // /api/v1/bot/test-send —— 出站发送动作，目标 URL 来自请求体（2026-11-13）
    test: (p) => p === '/api/v1/bot/test-send',
  },
];

function requiresAdmin(method: string, path: string): boolean {
  if (ADMIN_PREFIXES.some((prefix) => path.startsWith(prefix))) return true;
  const m = method.toUpperCase();
  return ADMIN_METHOD_RULES.some((rule) => rule.methods.includes(m) && rule.test(path));
}

/**
 * 每浏览器独立 HttpOnly Cookie 承载匿名 token（消除多访客共用单一模块内存 token
 * 导致的串号，以及 72h 过期 / 容器重启后重新生成 anon-<uuid> 导致的个人数据丢失）。
 *
 * - Cookie 本身设 365 天持久化保存 token 字符串；
 * - 每次代理检查 token 内载荷的 `exp`（预留 5 分钟余量），未过期直接复用（零额外后端请求）；
 * - 若 token 临近过期或已过期，将其作为 `previous_token` 发往后端 `/api/v1/auth/anonymous`：
 *   后端校验 HMAC 签名通过后原样续用同一 `anon-<12hex>`，重新签发新有效期并回写 Cookie。
 */
const ANON_COOKIE_NAME = 'airdrop_anon_token';
const ANON_COOKIE_MAX_AGE_SECONDS = 365 * 24 * 60 * 60;
const ANON_TOKEN_SAFETY_MARGIN_MS = 5 * 60 * 1000;

function isAnonTokenFresh(token: string): boolean {
  const dotIdx = token.indexOf('.');
  if (dotIdx <= 0) return false;
  try {
    const b64 = token.slice(0, dotIdx).replace(/-/g, '+').replace(/_/g, '/');
    const padded = b64 + '='.repeat((4 - (b64.length % 4)) % 4);
    const json = JSON.parse(atob(padded)) as { exp?: unknown; role?: unknown };
    if (typeof json.exp !== 'number') return false;
    return json.exp * 1000 - ANON_TOKEN_SAFETY_MARGIN_MS > Date.now();
  } catch {
    return false;
  }
}

async function mintOrRenewAnonymousToken(
  requestOrigin: string,
  previousToken?: string,
): Promise<string | null> {
  try {
    const backendOrigin = (process.env.API_PROXY_TARGET || requestOrigin).replace(/\/$/, '');
    const res = await fetch(`${backendOrigin}/api/v1/auth/anonymous`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(previousToken ? { previous_token: previousToken } : {}),
      cache: 'no-store',
    });
    if (!res.ok) return null;
    const body = (await res.json()) as { access_token?: string };
    return body.access_token || null;
  } catch {
    return null;
  }
}

function isHttpsRequest(request: NextRequest): boolean {
  const forwardedProto = request.headers.get('x-forwarded-proto');
  if (forwardedProto) {
    return forwardedProto.split(',')[0]?.trim().toLowerCase() === 'https';
  }
  return request.nextUrl.protocol === 'https:';
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

  if (requiresAdmin(request.method, pathname)) {
    // P1-5 安全修复：代理严禁无条件代签管理员密钥。
    // 管理端点必须由客户端显式出示凭据（X-API-Key 或 Authorization: Bearer <token>）。
    // 若客户端未提供任何凭证，直接放行交由后端返回 401 UNAUTHORIZED / 403 FORBIDDEN。
    return NextResponse.next();
  }

  const existingCookie = request.cookies.get(ANON_COOKIE_NAME)?.value;
  let token: string | null = null;
  let shouldSetCookie = false;

  if (existingCookie && isAnonTokenFresh(existingCookie)) {
    token = existingCookie;
  } else {
    token = await mintOrRenewAnonymousToken(request.nextUrl.origin, existingCookie);
    shouldSetCookie = Boolean(token);
  }

  const requestHeaders = new Headers(request.headers);
  if (token) {
    requestHeaders.set('Authorization', `Bearer ${token}`);
  }

  const response = NextResponse.next({ request: { headers: requestHeaders } });
  if (shouldSetCookie && token) {
    response.cookies.set({
      name: ANON_COOKIE_NAME,
      value: token,
      httpOnly: true,
      sameSite: 'lax',
      secure: isHttpsRequest(request),
      path: '/',
      maxAge: ANON_COOKIE_MAX_AGE_SECONDS,
    });
  }
  return response;
}

export const config = {
  // 仅拦截 API 路径；/health 在后端 PUBLIC_PREFIXES 中，不需要鉴权
  matcher: ['/api/:path*'],
};
