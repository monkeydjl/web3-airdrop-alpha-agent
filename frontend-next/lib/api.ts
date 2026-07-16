export const API_BASE = process.env.NEXT_PUBLIC_API_BASE || '/api/v1';

export interface ApiResponse<T> {
  ok: boolean;
  data?: T;
  error?: { code: string; message: string };
}

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
  } catch {
    throw new Error(
      `无法连接 API（${url}）。请确认后端已在 8002 启动，前端 3002 的 rewrite 指向 127.0.0.1:8002。`,
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
    const fallback = `Request failed: ${res.status}`;
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
