/**
 * proxy.ts 管理员鉴权表与后端 `app/auth.py` 的 parity 守卫。
 *
 * 后端有双向 parity 测试（`tests/test_admin_only_rules.py`），前端这份手工
 * 拷贝却没有对应测试 —— 漂移方向虽是安全的（漏项 → 后端 403，不会越权），
 * 但漏一项的表现是"管理动作莫名 401/403"，排查时要翻两个文件才发现是
 * 前端表没登记。本测试用源码级静态扫描（与 modalShell.test.ts 同款风格）
 * 钉住：后端锁的每一项，前端表里都要有对应的字面量。
 *
 * 注意这是**方向一**（后端 → 前端）；前端多余项由 `requiresAdmin` 的
 * fail-closed 语义兜底（打不存在的路径只会 404）。
 */
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, it } from 'node:test';
import assert from 'node:assert/strict';

const backendAuth = readFileSync(
  fileURLToPath(new URL('../../backend/app/auth.py', import.meta.url)),
  'utf-8',
);
const proxySource = readFileSync(fileURLToPath(new URL('../proxy.ts', import.meta.url)), 'utf-8');

function extractBackendAdminPrefixes(): string[] {
  const start = backendAuth.indexOf('ADMIN_ONLY_PREFIXES = (');
  // 块尾 = 顶格的 `)`。不能用 indexOf('ADMIN_ONLY_METHOD_RULES') 定位——
  // 模块 docstring（第 16 行）会先提到这个名字，把块截成空的。
  const end = backendAuth.indexOf('\n)', start);
  assert.ok(start >= 0 && end > start, 'auth.py 里解析不到 ADMIN_ONLY_PREFIXES —— 结构变了先修本测试');
  const block = backendAuth.slice(start, end);
  // 形如 "/api/v1/run",（排除注释行里的举例）
  return [...block.matchAll(/["'](\/api\/v1\/[a-z0-9\-]+)["']/g)].map((m) => m[1]);
}

function extractBackendMethodRuleTrunks(): string[] {
  const start = backendAuth.indexOf('ADMIN_ONLY_METHOD_RULES');
  assert.ok(start >= 0, 'auth.py 里解析不到 ADMIN_ONLY_METHOD_RULES');
  const block = backendAuth.slice(start);
  // 形如 re.compile(r"^/api/v1/collections(?:/|$)") → 主干 /api/v1/collections
  return [...block.matchAll(/re\.compile\(r"\^(\/api\/v1\/[a-z0-9\-_/{}]+)"/g)].map((m) => m[1]);
}

describe('proxy admin table parity with backend auth.py', () => {
  it('后端每个整前缀锁都在前端 ADMIN_PREFIXES 里有对应字面量', () => {
    const missing = extractBackendAdminPrefixes().filter((p) => !proxySource.includes(`'${p}'`));
    assert.deepEqual(
      missing,
      [],
      `前端 proxy.ts 的 ADMIN_PREFIXES 缺这些后端锁定的前缀（管理动作会在浏览器莫名 401/403）：${missing}`,
    );
  });

  it('后端每个按方法锁的路径主干在前端 ADMIN_METHOD_RULES 里有对应规则', () => {
    const missing = extractBackendMethodRuleTrunks().filter(
      (trunk) => !proxySource.includes(trunk.replace('^', '')),
    );
    assert.deepEqual(
      missing,
      [],
      `前端 proxy.ts 的 ADMIN_METHOD_RULES 缺这些后端按方法锁的路径：${missing}`,
    );
  });
});
