/**
 * lib/download.ts 的单测。
 *
 * 用 node 内置的 `node:test` + `node:assert`，不引入任何测试依赖 ——
 * Node 24 能直接执行 TypeScript（类型擦除），所以这里测的是**真实源文件**，
 * 不是它的副本。测副本等于没测：副本和原件长得一样，但改一处不会同步。
 *
 * 跑法：`npm test`（等价于 `node --test lib/*.test.ts`）
 *
 * 为什么这几个函数值得单测：它们全部在解析**别人给的字符串**——
 * HTTP 头、错误响应体、文件名。这类代码的失败方式是静默的：
 * 解析不出来时不会抛错，只会把一个错的值当成对的用下去
 * （文件名变成 `undefined`，或者后端明明说了原因却只显示 HTTP 404）。
 */

import assert from 'node:assert/strict';
import { describe, it } from 'node:test';

import { errorMessageFromBody, filenameFromDisposition, validateUploadFile } from './download.ts';

describe('filenameFromDisposition', () => {
  it('认后端 export/projects 的带引号 + filename* 写法', () => {
    // 实测自 backend/app/routers/v1/export_import.py 的真实响应头
    const h = `attachment; filename="projects_all.csv"; filename*=UTF-8''projects_all.csv`;
    assert.equal(filenameFromDisposition(h, 'fallback.csv'), 'projects_all.csv');
  });

  it('认后端 export/template 的无引号裸值写法', () => {
    // 同一个后端里的另一种写法 —— 只认带引号的会在这里退回 fallback
    const h = 'attachment; filename=import_template.xlsx';
    assert.equal(filenameFromDisposition(h, 'fallback.xlsx'), 'import_template.xlsx');
  });

  it('filename* 优先，用于承载非 ASCII 名字', () => {
    // 项目详情导出的文件名是 `{name}_详情.xlsx`，普通 filename 那份会被
    // 转义或降级，只有 filename* 是原名
    const encoded = encodeURIComponent('LayerX_详情.xlsx');
    const h = `attachment; filename="LayerX_.xlsx"; filename*=UTF-8''${encoded}`;
    assert.equal(filenameFromDisposition(h, 'x.xlsx'), 'LayerX_详情.xlsx');
  });

  it('filename* 的百分号编码坏掉时退回普通 filename，不返回报错串', () => {
    // `%E4%` 是截断的 UTF-8 序列，decodeURIComponent 会抛
    const h = `attachment; filename="safe.csv"; filename*=UTF-8''%E4%`;
    assert.equal(filenameFromDisposition(h, 'fallback.csv'), 'safe.csv');
  });

  it('没有头时用 fallback', () => {
    assert.equal(filenameFromDisposition(null, 'fallback.csv'), 'fallback.csv');
  });

  it('头里没有 filename 时用 fallback，而不是空字符串', () => {
    // 空文件名会让浏览器下载出一个没名字的文件
    assert.equal(filenameFromDisposition('attachment', 'fallback.csv'), 'fallback.csv');
  });
});

describe('errorMessageFromBody', () => {
  it('认 {ok:false,error:{message}} —— 后端 404 的实际形状', () => {
    const body = '{"ok":false,"error":{"code":"HTTP_ERROR","message":"没有找到符合条件的项目"}}';
    assert.equal(errorMessageFromBody(body, 404, '导出'), '没有找到符合条件的项目');
  });

  it('认 {detail:"字符串"} —— 格式不支持时的形状', () => {
    const body = '{"detail":"不支持的文件格式，请上传 .xlsx 或 .csv 文件"}';
    assert.equal(
      errorMessageFromBody(body, 400, '导入'),
      '不支持的文件格式，请上传 .xlsx 或 .csv 文件',
    );
  });

  it('认 {detail:{code,message}} —— 文件超限时的形状', () => {
    const body = '{"detail":{"code":"FILE_TOO_LARGE","message":"文件超过大小限制（10MB）"}}';
    assert.equal(errorMessageFromBody(body, 413, '导入'), '文件超过大小限制（10MB）');
  });

  it('响应体不是 JSON 时退回 HTTP 码，不把 HTML 原文喷给用户', () => {
    const body = '<html><body>502 Bad Gateway</body></html>';
    assert.equal(errorMessageFromBody(body, 502, '导出'), '导出失败（HTTP 502）');
  });

  it('响应体为空时退回 HTTP 码', () => {
    assert.equal(errorMessageFromBody('', 500, '导入'), '导入失败（HTTP 500）');
  });

  it('JSON 是数组等非对象时退回 HTTP 码，不崩', () => {
    assert.equal(errorMessageFromBody('[1,2,3]', 400, '导出'), '导出失败（HTTP 400）');
    assert.equal(errorMessageFromBody('null', 400, '导出'), '导出失败（HTTP 400）');
    assert.equal(errorMessageFromBody('"just a string"', 400, '导出'), '导出失败（HTTP 400）');
  });

  it('message 存在但是空串时不返回空提示', () => {
    // 返回空串会让 toast 弹出一个没有内容的框
    const body = '{"ok":false,"error":{"message":""}}';
    assert.equal(errorMessageFromBody(body, 404, '导出'), '导出失败（HTTP 404）');
  });

  it('401 换成中文并指明去哪配密钥，不透后端英文原文', () => {
    // 实测后端未配密钥时返回：{"ok":false,"error":{"code":"UNAUTHORIZED",
    // "message":"Missing API key or token"}} —— 用户看不懂，也不知道去哪改
    const body = '{"ok":false,"error":{"code":"UNAUTHORIZED","message":"Missing API key or token"}}';
    const msg = errorMessageFromBody(body, 401, '导出');
    assert.match(msg, /BACKEND_API_KEY/);
    assert.doesNotMatch(msg, /Missing API key/);
  });

  it('403 说明是权限不足而不是没带密钥', () => {
    // 匿名 token 能过鉴权但过不了 ADMIN_ONLY_PREFIXES，两种情况的处置动作不同
    const body = '{"ok":false,"error":{"code":"FORBIDDEN","message":"Admin only"}}';
    const msg = errorMessageFromBody(body, 403, '导入');
    assert.match(msg, /管理员/);
  });
});

describe('validateUploadFile', () => {
  it('放行 .xlsx 与 .csv', () => {
    assert.equal(validateUploadFile('projects.xlsx', 1024), null);
    assert.equal(validateUploadFile('projects.csv', 1024), null);
  });

  it('大小写不敏感', () => {
    assert.equal(validateUploadFile('PROJECTS.XLSX', 1024), null);
    assert.equal(validateUploadFile('Projects.Csv', 1024), null);
  });

  it('拒绝其他扩展名', () => {
    assert.match(String(validateUploadFile('a.txt', 1024)), /只支持/);
    assert.match(String(validateUploadFile('a.json', 1024)), /只支持/);
    // 名字里含 .csv 但结尾不是 —— 只用 includes 判断会漏
    assert.match(String(validateUploadFile('a.csv.exe', 1024)), /只支持/);
  });

  it('恰好 10MB 放行，超一个字节就拒（边界）', () => {
    const tenMB = 10 * 1024 * 1024;
    assert.equal(validateUploadFile('a.csv', tenMB), null);
    assert.match(String(validateUploadFile('a.csv', tenMB + 1)), /超过 10MB/);
  });

  it('拒绝 0 字节文件', () => {
    // 后端会当成"没有有效项目数据"返回 400，前端先挡掉省一次上传
    assert.match(String(validateUploadFile('a.csv', 0)), /文件为空/);
  });
});
