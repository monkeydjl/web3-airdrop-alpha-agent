export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api/v1';

export interface ApiResponse<T> {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string };
}

/** 请求被 AbortController 取消时抛出的错误（调用方应静默忽略，而非当作故障展示） */
export function isAbortError(err: unknown): boolean {
  return (
    typeof err === 'object' &&
    err !== null &&
    'name' in err &&
    (err as { name?: string }).name === 'AbortError'
  );
}

/**
 * 鉴权由服务端的 `proxy.ts` 注入 X-API-Key（读服务端环境变量 BACKEND_API_KEY /
 * API_KEY），密钥不出服务端。
 *
 * **刻意不再支持 NEXT_PUBLIC_API_KEY 客户端兜底**：Next.js 会把所有
 * `NEXT_PUBLIC_*` 变量内联进浏览器 bundle，任何访客都能在 DevTools 里读到管理员
 * 密钥——那等于把鉴权直接送人。需要本地直连后端调试时，请让后端 API_KEY 留空
 * （MVP 无鉴权模式），而不是把密钥暴露给浏览器。
 *
 * 返回值是响应体的 **`data` 字段**（`{ok, data}` 信封拆掉一层）。后端有不少端点
 * 不包 `data`（`/pnl/summary`、`/sell-off/simulate` 等直接把字段放顶层），或者把
 * `data_quality` / `count` 这类元信息放在信封上 —— 这些要用 `apiFetchEnvelope`。
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const json = await request(path, init);
  return json.data as T;
}

/**
 * 与 `apiFetch` 相同的请求 / 鉴权 / 报错逻辑，但返回**完整响应体**，不拆 `data`。
 *
 * 为什么需要（2026-10-08）：约 10 个面板把 `apiFetch` 的返回值当成完整信封去读
 * （`res?.ok`、`res.data`、`res.data_quality`），而 `apiFetch` 给的是 `json.data` ——
 * 顶层平铺的端点拿到 `undefined`，包了 `data` 的端点被多拆一层，面板永远是空的。
 * 类型全是 `any`，所以编译器一声没吭。
 *
 * `T` 描述整个响应体，例如 `apiFetchEnvelope<{ ok: boolean; data: Foo[]; count: number }>`。
 */
export async function apiFetchEnvelope<T>(path: string, init?: RequestInit): Promise<T> {
  return (await request(path, init)) as T;
}

async function request(path: string, init?: RequestInit): Promise<ApiResponse<unknown> & Record<string, unknown>> {
  const url = `${API_BASE}${path}`;
  let res: Response;
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
  };

  // 客户端凭据自动附加（支持 localStorage / sessionStorage）
  if (typeof window !== 'undefined') {
    const token = localStorage.getItem('auth_token') || sessionStorage.getItem('auth_token');
    const apiKey = localStorage.getItem('api_key') || sessionStorage.getItem('api_key');
    if (apiKey) {
      headers['X-API-Key'] = apiKey;
    } else if (token) {
      headers['Authorization'] = `Bearer ${token}`;
    }
  }

  if (init?.headers) {
    if (init.headers instanceof Headers) {
      init.headers.forEach((v, k) => {
        headers[k] = v;
      });
    } else if (Array.isArray(init.headers)) {
      for (const [k, v] of init.headers) {
        headers[k] = v;
      }
    } else {
      Object.assign(headers, init.headers);
    }
  }

  try {
    res = await fetch(url, {
      ...init,
      headers,
    });
  } catch (cause) {
    // 主动取消不是故障，原样抛出让调用方识别
    if (isAbortError(cause)) throw cause;
    // 保留原始错误，避免把 CORS/TLS/拦截器等问题都误报成"后端没启动"
    throw new Error(
      `无法连接 API（${url}）。请确认后端已在 8002 启动，前端 3002 的 rewrite 指向 127.0.0.1:8002。`,
      { cause },
    );
  }

  const text = await res.text();
  let json: ApiResponse<unknown> & Record<string, unknown> & { detail?: unknown };
  try {
    json = text ? JSON.parse(text) : {};
  } catch {
    const snippet = text.replace(/\s+/g, ' ').slice(0, 180);
    // Next rewrite 失败或后端崩溃时常见 HTML 500
    if (res.status >= 500) {
      throw new Error(
        `后端错误 HTTP ${res.status}（非 JSON）。请确认 uvicorn 在 8002 正常运行，并查看后端终端日志。${snippet ? ` 摘要: ${snippet}` : ''}`,
      );
    }
    throw new Error(
      `API 返回非 JSON（HTTP ${res.status}）${snippet ? `：${snippet}` : ''}`,
    );
  }

  if (!res.ok || json.ok === false) {
    const fallback = `请求失败：${res.status}`;
    if (Array.isArray(json.detail)) {
      throw new Error(
        json.detail.map((d: { msg?: string }) => d.msg).join('; ') || fallback,
      );
    }
    if (typeof json.detail === 'string') {
      throw new Error(json.detail);
    }
    if (json.detail && typeof json.detail === 'object' && 'message' in (json.detail as object)) {
      throw new Error(String((json.detail as { message: string }).message));
    }
    throw new Error(json.error?.message || fallback);
  }
  return json;
}


/**
 * 健康检查专用取数。
 *
 * 不能复用 `apiFetch`：它会自动加上 `/api/v1` 前缀，而 `/health` 在后端根路径；
 * 且它在 `ok === false` 时抛异常，而"后端在线但已降级"恰恰是我们要区分出来
 * 展示的状态，不该和"完全连不上"混为一谈。
 */
export async function fetchHealth(): Promise<{ ok: boolean; status: string } & Record<string, unknown>> {
  const res = await fetch('/health', { headers: { Accept: 'application/json' } });
  const text = await res.text();
  try {
    const json = JSON.parse(text) as { ok?: boolean; status?: string };
    return { ...json, ok: Boolean(json.ok), status: json.status || (res.ok ? 'healthy' : 'degraded') };
  } catch {
    return { ok: false, status: `http_${res.status}` };
  }
}
