/**
 * `apiFetch` 与 `apiFetchEnvelope` 的返回口径 + 调用方的静态守卫（2026-10-08）。
 *
 * 背景：`apiFetch` 返回响应体的 `data` 字段，但约 48 处调用把返回值当成**完整
 * 信封**去读（`res?.ok`、`res.data`、`res.data_quality`）：
 * - 顶层平铺的端点（`/pnl/summary`、`/sell-off/simulate`、`/bot/test-send`…）
 *   拿到 `undefined`，面板永远空着或永远报「发送失败」；
 * - 包了 `data` 的端点被多拆一层，`res.data` 又是 `undefined`。
 * 类型参数全是 `any` 或手写的信封形状，编译器一声没吭。
 *
 * 修法是 `apiFetchEnvelope`（返回完整响应体）。本文件钉住两件事：
 *   1. 两个函数的返回口径（mock fetch，测真实源文件）；
 *   2. 没有人再用**信封形状**的类型参数调 `apiFetch` —— 那正是这个 bug 的指纹。
 */

import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { dirname, join, relative } from 'node:path';
import { afterEach, beforeEach, describe, it } from 'node:test';
import { fileURLToPath } from 'node:url';

import { apiFetch, apiFetchEnvelope } from './api.ts';

const realFetch = globalThis.fetch;

function mockFetch(body: unknown, status = 200) {
  globalThis.fetch = (async () => new Response(JSON.stringify(body), { status })) as typeof fetch;
}

describe('apiFetch / apiFetchEnvelope 返回口径', () => {
  beforeEach(() => mockFetch({}));
  afterEach(() => {
    globalThis.fetch = realFetch;
  });

  it('apiFetch 拆掉一层 data', async () => {
    mockFetch({ ok: true, data: { items: [1, 2] }, data_quality: { quality: 'simulated' } });
    assert.deepEqual(await apiFetch('/x'), { items: [1, 2] });
  });

  it('apiFetch 遇到顶层平铺的端点得到 undefined —— 这正是旧 bug 的形态', async () => {
    mockFetch({ ok: true, total_claimed_projects: 3, records: [] });
    assert.equal(await apiFetch('/pnl/summary'), undefined);
  });

  it('apiFetchEnvelope 原样返回完整响应体（平铺 / 包 data 两种都行）', async () => {
    mockFetch({ ok: true, total_claimed_projects: 3, records: [] });
    assert.deepEqual(await apiFetchEnvelope('/pnl/summary'), { ok: true, total_claimed_projects: 3, records: [] });

    mockFetch({ ok: true, data: [{ id: 'r1' }], count: 1 });
    assert.deepEqual(await apiFetchEnvelope('/gas/alerts/rules'), { ok: true, data: [{ id: 'r1' }], count: 1 });
  });

  it('两者报错口径一致：ok=false / HTTP 错误都抛同一条消息', async () => {
    mockFetch({ ok: false, error: { code: 'X', message: 'boom' } });
    await assert.rejects(apiFetch('/x'), /boom/);
    await assert.rejects(apiFetchEnvelope('/x'), /boom/);

    mockFetch({ detail: 'nope' }, 404);
    await assert.rejects(apiFetch('/x'), /nope/);
    await assert.rejects(apiFetchEnvelope('/x'), /nope/);
  });
});

const ROOT = dirname(fileURLToPath(import.meta.url));
const SCAN_DIRS = ['../components', '../app'];

function collectTsx(): string[] {
  const files: string[] = [];
  for (const d of SCAN_DIRS) {
    const walk = (cur: string) => {
      for (const entry of readdirSync(cur, { withFileTypes: true })) {
        const full = join(cur, entry.name);
        if (entry.isDirectory()) walk(full);
        else if (entry.name.endsWith('.tsx')) files.push(full);
      }
    };
    walk(join(ROOT, d));
  }
  return files;
}

describe('调用方静态守卫', () => {
  it('apiFetchEnvelope 确实被大量使用（守卫自身不空转）', () => {
    const n = collectTsx().reduce((acc, f) => acc + (readFileSync(f, 'utf8').match(/\bapiFetchEnvelope</g) ?? []).length, 0);
    assert.ok(n >= 40, `只找到 ${n} 处 apiFetchEnvelope —— 扫描路径或正则失效了？`);
  });

  it('没有人用信封形状（{ ok / { data 开头）的类型参数调 apiFetch', () => {
    // apiFetch 给的是 json.data，类型参数写成 { ok; data } 等于声明「我要完整信封」——
    // 运行时拿到的却是里面一层。要完整信封请用 apiFetchEnvelope。
    const offenders: string[] = [];
    for (const file of collectTsx()) {
      const src = readFileSync(file, 'utf8');
      for (const m of src.matchAll(/\bapiFetch<\{\s*(ok|data)\??\s*:/g)) {
        const line = src.slice(0, m.index).split('\n').length;
        offenders.push(`${relative(join(ROOT, '..'), file)}:${line}`);
      }
    }
    assert.deepEqual(offenders, [], `这些调用应改用 apiFetchEnvelope：\n${offenders.join('\n')}`);
  });
});
