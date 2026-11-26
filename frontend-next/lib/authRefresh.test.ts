/**
 * JWT 401 自动续期、单飞并发合并、AdminAuthModal 注册 Tab 与理由中文化回归测试。
 */

import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

import {
  apiFetch,
  clearStoredCredentials,
  getStoredAuthSummary,
  saveJwtSession,
} from './api.ts';
import { reasonZh } from './format.ts';

const ROOT = dirname(fileURLToPath(import.meta.url));
const realFetch = globalThis.fetch;
const realWindow = (globalThis as { window?: unknown }).window;

function makeMemoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear() {
      map.clear();
    },
    getItem(key: string) {
      return map.has(key) ? (map.get(key) ?? null) : null;
    },
    key(index: number) {
      return [...map.keys()][index] ?? null;
    },
    removeItem(key: string) {
      map.delete(key);
    },
    setItem(key: string, value: string) {
      map.set(key, String(value));
    },
  };
}

describe('JWT 401 自动刷新与过期凭据清理', () => {
  beforeEach(() => {
    (globalThis as { window?: unknown }).window = {
      localStorage: makeMemoryStorage(),
      sessionStorage: makeMemoryStorage(),
      dispatchEvent: () => true,
    };
  });

  afterEach(() => {
    clearStoredCredentials(false);
    globalThis.fetch = realFetch;
    if (realWindow === undefined) {
      delete (globalThis as { window?: unknown }).window;
    } else {
      (globalThis as { window?: unknown }).window = realWindow;
    }
  });

  it('access_token 401 时自动调用 /auth/refresh 轮换凭据并重试成功', async () => {
    saveJwtSession('expired-jwt', 'valid-refresh-1', 'alice@example.com', 'admin', true);

    const seenAuthHeaders: Array<string | undefined> = [];
    let refreshCount = 0;

    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        refreshCount += 1;
        return new Response(
          JSON.stringify({
            access_token: 'fresh-jwt-2',
            refresh_token: 'rotated-refresh-2',
            user: { email: 'alice@example.com', role: 'admin' },
          }),
          { status: 200 },
        );
      }
      const hdrs = (init?.headers ?? {}) as Record<string, string>;
      seenAuthHeaders.push(hdrs.Authorization);
      if (hdrs.Authorization === 'Bearer expired-jwt') {
        return new Response(
          JSON.stringify({ ok: false, error: { code: 'UNAUTHORIZED', message: 'Expired' } }),
          { status: 401 },
        );
      }
      return new Response(JSON.stringify({ ok: true, data: { items: ['alpha'] } }), { status: 200 });
    }) as typeof fetch;

    const data = await apiFetch<{ items: string[] }>('/projects');
    assert.deepEqual(data, { items: ['alpha'] });
    assert.equal(refreshCount, 1);
    assert.deepEqual(seenAuthHeaders, ['Bearer expired-jwt', 'Bearer fresh-jwt-2']);
    assert.equal(getStoredAuthSummary().mode, 'jwt');
  });

  it('并发 401 请求共享单飞刷新（避免轮换后的旧 refresh_token 触发误吊销）', async () => {
    saveJwtSession('expired-jwt', 'valid-refresh-1', 'alice@example.com', 'analyst', true);

    let refreshCount = 0;
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        refreshCount += 1;
        await new Promise((r) => setTimeout(r, 10));
        return new Response(
          JSON.stringify({
            access_token: 'fresh-jwt-concurrent',
            refresh_token: 'rotated-refresh-concurrent',
            user: { email: 'alice@example.com', role: 'analyst' },
          }),
          { status: 200 },
        );
      }
      const hdrs = (init?.headers ?? {}) as Record<string, string>;
      if (hdrs.Authorization === 'Bearer expired-jwt') {
        return new Response(
          JSON.stringify({ ok: false, error: { code: 'UNAUTHORIZED', message: 'Expired' } }),
          { status: 401 },
        );
      }
      return new Response(JSON.stringify({ ok: true, data: { okPath: url } }), { status: 200 });
    }) as typeof fetch;

    const results = await Promise.all([
      apiFetch<{ okPath: string }>('/p1'),
      apiFetch<{ okPath: string }>('/p2'),
      apiFetch<{ okPath: string }>('/p3'),
    ]);
    assert.equal(results.length, 3);
    assert.equal(refreshCount, 1, '3 个并发 401 请求应合并为恰好 1 次 /auth/refresh 调用');
  });

  it('refresh_token 亦失效（401）时自动清空本地死凭据并无头重试回退匿名态', async () => {
    saveJwtSession('expired-jwt', 'revoked-refresh', 'alice@example.com', 'viewer', true);

    const seenAuthHeaders: Array<string | undefined> = [];
    globalThis.fetch = (async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      if (url.endsWith('/auth/refresh')) {
        return new Response(
          JSON.stringify({ ok: false, error: { code: 'SESSION_REVOKED', message: 'Revoked' } }),
          { status: 401 },
        );
      }
      const hdrs = (init?.headers ?? {}) as Record<string, string>;
      seenAuthHeaders.push(hdrs.Authorization);
      if (hdrs.Authorization) {
        return new Response(
          JSON.stringify({ ok: false, error: { code: 'UNAUTHORIZED', message: 'Expired' } }),
          { status: 401 },
        );
      }
      return new Response(JSON.stringify({ ok: true, data: { fallback: 'anonymous-ok' } }), {
        status: 200,
      });
    }) as typeof fetch;

    const res = await apiFetch<{ fallback: string }>('/projects');
    assert.deepEqual(res, { fallback: 'anonymous-ok' });
    assert.equal(getStoredAuthSummary().mode, 'none', '失效的 JWT 应已被自动清除');
    assert.deepEqual(seenAuthHeaders, ['Bearer expired-jwt', undefined]);
  });
});

describe('AdminAuthModal 注册入口与理由中文化守卫', () => {
  it('AdminAuthModal 包含注册账号 Tab、/auth/register 提交与可选 bootstrap_token 字段', () => {
    const src = readFileSync(join(ROOT, '../components/AdminAuthModal.tsx'), 'utf8');
    assert.match(src, /注册账号/, 'AdminAuthModal 应提供「注册账号」Tab');
    assert.match(src, /'\/auth\/register'/, 'AdminAuthModal 应调用 /auth/register');
    assert.match(src, /bootstrap_token/, 'AdminAuthModal 应支持可选 bootstrap_token');
  });

  it('资格门监控理由已映射为中文', () => {
    const raw = 'no verified participation path; monitor for a testnet, points, or task portal';
    const zh = reasonZh(raw);
    assert.notEqual(zh, raw);
    assert.match(zh, /交互路径/);
  });
});
