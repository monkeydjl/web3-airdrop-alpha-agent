/**
 * 后端文件下载 / 上传辅助。
 *
 * 单独成模块而不是写在页面里，有两个原因：
 * 1. 页面是 `'use client'` + JSX，node 无法直接加载，写在里面的纯逻辑就没法测；
 *    抽出来之后测试导入的是**同一份代码**，不是它的副本。
 *    （测同名副本等于没测 —— 副本和原件长得一样，但改一处不会同步。）
 * 2. `/projects` 等页面将来也要导出，逻辑不该各写一遍。
 */

/** 后端 /export/* 与 /import/* 的挂载前缀，与 lib/api.ts 的 API_BASE 保持一致 */
export const API_PREFIX = process.env.NEXT_PUBLIC_API_BASE || '/api/v1';

/**
 * 从 Content-Disposition 取文件名。
 *
 * 后端两种写法都出现了（实测自 backend/app/routers/v1/export_import.py）：
 *   export/projects  → attachment; filename="projects_all.csv"; filename*=UTF-8''projects_all.csv
 *   export/template  → attachment; filename=import_template.xlsx      ← 无引号
 * 所以既要认带引号的，也要认裸值；`filename*=` 优先 —— 它才是 RFC 5987 里承载
 * 非 ASCII 名字的那个，项目详情导出的文件名带中文（`{name}_详情.xlsx`）。
 */
export function filenameFromDisposition(header: string | null, fallback: string): string {
  if (!header) return fallback;

  const star = /filename\*=UTF-8''([^;]+)/i.exec(header);
  if (star?.[1]) {
    try {
      const decoded = decodeURIComponent(star[1].trim());
      if (decoded) return decoded;
    } catch {
      // 百分号编码坏了就退回普通 filename，不要把报错或半截字符串当文件名塞给用户
    }
  }

  const plain = /filename="([^"]+)"|filename=([^;]+)/i.exec(header);
  const value = (plain?.[1] ?? plain?.[2] ?? '').trim();
  return value || fallback;
}

/**
 * 把后端 JSON 错误体翻译成人能看的一句话。
 *
 * 后端错误有三种形状（实测）：
 *   {"ok":false,"error":{"code":"HTTP_ERROR","message":"没有找到符合条件的项目"}}
 *   {"detail":"不支持的文件格式，请上传 .xlsx 或 .csv 文件"}
 *   {"detail":{"code":"FILE_TOO_LARGE","message":"文件超过大小限制（10MB）"}}
 * 三种都要认。认不出来才退回 HTTP 码 —— 后端已经把原因写清楚了，
 * 只报一个 404 等于把它扔掉。
 */
export function errorMessageFromBody(text: string, status: number, fallbackAction: string): string {
  const generic = `${fallbackAction}失败（HTTP ${status}）`;

  // 鉴权失败要单独说人话。这两组端点在后端的 ADMIN_ONLY_PREFIXES 里
  // （`/api/v1/export`、`/api/v1/import`），密钥由 Next 服务端的 proxy.ts 从
  // BACKEND_API_KEY / API_KEY 注入。没配时后端返回的是英文
  // "Missing API key or token"（实测），直接透给用户，他既看不懂、
  // 也不知道该去哪配。
  if (status === 401) {
    return `${fallbackAction}需要管理员密钥：请在前端服务端设置 BACKEND_API_KEY（与后端 API_KEY 一致）后重启`;
  }
  if (status === 403) {
    return `${fallbackAction}被拒绝：当前身份不是管理员，该接口仅管理员可用`;
  }

  if (!text) return generic;

  let body: unknown;
  try {
    body = JSON.parse(text);
  } catch {
    return generic;
  }
  if (typeof body !== 'object' || body === null) return generic;

  const obj = body as { error?: { message?: unknown }; detail?: unknown };

  if (typeof obj.error?.message === 'string' && obj.error.message) return obj.error.message;
  if (typeof obj.detail === 'string' && obj.detail) return obj.detail;
  if (typeof obj.detail === 'object' && obj.detail !== null) {
    const d = obj.detail as { message?: unknown };
    if (typeof d.message === 'string' && d.message) return d.message;
  }
  return generic;
}

/**
 * 下载后端返回的二进制文件，返回实际落盘的文件名。
 *
 * 不能用 `apiFetch`：它假定响应是 `{ok, data}` JSON 信封，会对 xlsx 字节流调
 * JSON.parse 直接抛错。所以这里走原生 fetch 拿 blob，但错误分支复用
 * `errorMessageFromBody`，保证后端那句话不会被吞掉。
 */
export async function downloadFile(path: string, fallbackName: string): Promise<string> {
  const res = await fetch(`${API_PREFIX}${path}`, { headers: { Accept: '*/*' } });

  if (!res.ok) {
    throw new Error(errorMessageFromBody(await res.text(), res.status, '导出'));
  }

  const blob = await res.blob();
  if (blob.size === 0) throw new Error('导出内容为空');

  const name = filenameFromDisposition(res.headers.get('content-disposition'), fallbackName);
  const url = URL.createObjectURL(blob);
  try {
    const a = document.createElement('a');
    a.href = url;
    a.download = name;
    a.click();
  } finally {
    // 不 revoke 会一直占着 blob 内存，反复导出越用越多
    URL.revokeObjectURL(url);
  }
  return name;
}

/** 上传文件的前端预检结果；`null` 表示通过 */
export function validateUploadFile(name: string, size: number): string | null {
  const MAX_BYTES = 10 * 1024 * 1024;
  const lower = name.toLowerCase();
  if (!lower.endsWith('.xlsx') && !lower.endsWith('.csv')) {
    return '只支持 .xlsx 或 .csv 文件';
  }
  if (size > MAX_BYTES) {
    return `文件 ${(size / 1024 / 1024).toFixed(1)}MB 超过 10MB 上限`;
  }
  if (size === 0) {
    return '文件为空';
  }
  return null;
}
