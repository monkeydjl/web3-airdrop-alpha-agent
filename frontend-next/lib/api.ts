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
 */
export async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  let res: Response;
  try {
    res = await fetch(url, {
      ...init,
      headers: {
        'Content-Type': 'application/json',
        ...(init?.headers || {}),
      },
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
  let json: ApiResponse<T> & { detail?: unknown };
  try {
    json = text ? JSON.parse(text) : ({} as ApiResponse<T>);
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
  return json.data as T;
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
