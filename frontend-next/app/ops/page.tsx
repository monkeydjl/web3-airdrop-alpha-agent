'use client';

import { EmptyState, Switch, Toast } from '@/components/ui';
import { TopBar } from '@/components/TopBar';
import { apiFetch, fetchHealth } from '@/lib/api';
import { relativeTime, sourceZh } from '@/lib/format';
import { normalizeCollectionSource } from '@/lib/types';
import type { CollectionSource, CollectionSourceApi, HealthData } from '@/lib/types';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Clock, Download, FileSpreadsheet, FileText, HeartPulse, UploadCloud } from 'lucide-react';

interface QuarantineItem {
  raw_id: string;
  source_id?: string;
  discovery_score?: number;
  quarantine_reason?: string;
  raw_data?: { name?: string; sector?: string };
}

/** /settings/config 的 automation 块（真实调度配置） */
interface AutomationConfig {
  SCHEDULER_ENABLED?: boolean;
  COLLECTION_SCHEDULER_ENABLED?: boolean;
  COLLECTION_AUTO_RUN_ENABLED?: boolean;
  CRON_EXPRESSION?: string;
  ANALYSIS_RUN_LIMIT?: number;
  SCHEDULER_MISFIRE_GRACE_SECONDS?: number;
  ARCHIVE_SCHEDULER_ENABLED?: boolean;
  ARCHIVE_CRON?: string;
}

interface SettingsConfig {
  automation?: AutomationConfig;
  /** 各采集源的真实配置，含 cron —— 用于替代原先写死的 SOURCE_CRONS 表 */
  sources?: Record<string, { cron?: string; kol_cron?: string; keyword_cron?: string }>;
}

/**
 * 一次导入的结果。刻意保留 `errors`：后端会在部分行有问题时**照样导入合法行**
 * 并把逐行错误放在 `validation_errors` 里，只报「成功 N 项」会把它们藏掉。
 */
interface ImportOutcome {
  filename: string;
  at: string;
  projectCount: number;
  topScore: number | null;
  errors: string[];
}

function boolZh(v?: boolean): string {
  if (v === undefined) return '—';
  return v ? '已启用' : '已停用';
}

/**
 * 调度器任务表（`GET /api/v1/scheduler/jobs`）。
 *
 * 这一块此前整个运维台都没有 —— 而归档功能从上线到 2026-08-24
 * **一次都没被触发过**，是靠翻数据库才发现的。任务表看不见，
 * 「archive_cleanup 根本不在列表里」这个一眼可见的事实就没有地方可见。
 */
interface SchedulerJob {
  id: string;
  name: string;
  next_run_time: string | null;
  owner_switch: string;
}

interface SchedulerJobsPayload {
  /** not_initialized | disabled | running | read_error —— 四种「空」的原因不同 */
  scheduler_state: string;
  running: boolean;
  timezone: string;
  jobs: SchedulerJob[];
  /** read_error 时是 null，不是 0 —— 读不出来和确实没有是两件事 */
  job_count: number | null;
  expected_job_count: number;
  missing_jobs: string[] | null;
  switches: Record<string, boolean>;
  read_error: string | null;
  note: string | null;
}

/**
 * 把 `scheduler_state` 翻成人话 + 该不该报警。
 *
 * 关键是 `running` 且 0 个任务这一种：它和"开关全关"在界面上极易混为一谈，
 * 但前者是故障、后者是配置。所以这里必须给出不同的语气与颜色。
 */
function schedulerStateLabel(p?: SchedulerJobsPayload | null): {
  text: string;
  tone: 'farm' | 'watch' | 'default';
  detail: string;
} {
  if (!p) return { text: '—', tone: 'default', detail: '' };
  if (p.scheduler_state === 'read_error') {
    return {
      text: '读取失败',
      tone: 'watch',
      detail: p.read_error ? `诊断接口自身出错：${p.read_error}` : '诊断接口自身出错',
    };
  }
  if (p.scheduler_state === 'not_initialized') {
    return {
      text: '未初始化',
      tone: 'watch',
      detail: p.note ?? '调度器对象不存在；生产环境出现这个值意味着启动流程没走完',
    };
  }
  if (p.scheduler_state === 'disabled') {
    return {
      text: '已停用',
      tone: 'default',
      detail: '三个调度开关都是关的 —— 这是配置，不是故障',
    };
  }
  if (p.job_count === 0) {
    return {
      text: '运行中但无任务',
      tone: 'watch',
      detail: '开关开着、调度器在跑，却一个任务都没注册 —— 这是故障，请查启动日志',
    };
  }
  return { text: '运行中', tone: 'farm', detail: '' };
}

function formatNextRun(iso: string | null): string {
  if (!iso) return '未排期';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString('zh-CN', { hour12: false });
}

function numOr(v?: number, suffix = ''): string {
  return v == null ? '—' : `${v}${suffix}`;
}

/**
 * 从 /settings/config 的 sources 块取某个源的真实 cron。
 *
 * 这里此前是一张写死的对照表 `SOURCE_CRONS`。实测下来 11 项里有 **5 项是错的**：
 *   cryptorank  写 `0 9 * * *`   实际 `15 9 * * *`
 *   rootdata    写 `0 10 * * *`  实际 `45 9 * * *`
 *   twitter_kol 写 `0 6 * * *`   实际每小时一次    ← 前端说一天一次
 *   etherscan   写 `0 7 * * *`   实际每 6 小时一次
 *   layer3      写 `0 11 * * *`  实际 `30 10 * * *`
 * 运维台是用来判断"这个源什么时候会自己跑"的，显示错的排期比不显示更糟。
 * （上面刻意不写出含斜杠星号的 cron 字面量：那个组合会提前结束本注释块。）
 *
 * twitter 在后端拆成 `kol_cron` / `keyword_cron` 两个字段（没有 `cron`），
 * 所以要按 source_id 分别取。
 */
function cronOf(
  sourceId: string,
  sources?: Record<string, { cron?: string; kol_cron?: string; keyword_cron?: string }>,
): string | undefined {
  if (!sources) return undefined;
  if (sourceId === 'twitter_kol') return sources.twitter?.kol_cron;
  if (sourceId === 'twitter_keyword' || sourceId === 'twitter') {
    return sources.twitter?.keyword_cron;
  }
  return sources[sourceId]?.cron;
}


function formatUsd(n?: number | null) {
  if (n == null || Number.isNaN(Number(n))) return '—';
  const v = Number(n);
  const sign = v < 0 ? '-' : '';
  const abs = Math.abs(v);
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function syncStatusZh(s?: string | null) {
  if (!s) return null;
  if (s === 'idle') return '空闲';
  if (s === 'success' || s === 'ok') return '成功';
  if (s === 'error') return '错误';
  if (s === 'disabled') return '已禁用';
  if (s === 'not_registered') return '未注册';
  return s;
}

/** 导入导出的取数逻辑抽在 lib/download.ts，那里可被 node 直接加载做单测 */
import { API_PREFIX, downloadFile, errorMessageFromBody, validateUploadFile } from '@/lib/download';

function Kv({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-3 border-b border-line py-2 text-[13px] last:border-b-0">
      <span className="text-ink-muted">{k}</span>
      <span className="font-mono text-[12.5px] font-medium tabular-nums text-ink">{v}</span>
    </div>
  );
}

function Metric({
  label,
  value,
  hint,
  tone,
}: {
  label: string;
  value: React.ReactNode;
  hint?: string;
  tone?: 'farm' | 'watch' | 'default';
}) {
  const valueCls =
    tone === 'farm'
      ? 'text-farm dark:text-farm'
      : tone === 'watch'
        ? 'text-watch dark:text-watch'
        : 'text-ink';
  return (
    <div className="ops-card px-4 py-3.5">
      <div className="font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-muted">
        {label}
      </div>
      <div className={`mt-1.5 font-mono text-2xl font-semibold tabular-nums leading-none ${valueCls}`}>
        {value}
      </div>
      {hint ? <div className="mt-1.5 text-xs text-ink-faint">{hint}</div> : null}
    </div>
  );
}

export default function OpsPage() {
  const [sources, setSources] = useState<CollectionSource[]>([]);
  const [quarantine, setQuarantine] = useState<QuarantineItem[]>([]);
  const [qCount, setQCount] = useState(0);
  const [ixSummary, setIxSummary] = useState<{
    total?: number;
    total_cost_usd?: number;
    total_profit_usd?: number;
    net_usd?: number;
    total_hours?: number;
  } | null>(null);
  const [health, setHealth] = useState<HealthData | null>(null);
  const [automation, setAutomation] = useState<AutomationConfig | null>(null);
  const [runtimeSources, setRuntimeSources] = useState<SettingsConfig['sources']>(undefined);
  const [schedJobs, setSchedJobs] = useState<SchedulerJobsPayload | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [partialError, setPartialError] = useState<string[]>([]);
  const [busy, setBusy] = useState<string | null>(null);
  const [importResult, setImportResult] = useState<ImportOutcome | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(
    null,
  );

  const showToast = (message: string, type: 'success' | 'error' | 'info' = 'info') => {
    setToast({ message, type });
    setTimeout(() => setToast(null), 3500);
  };

  const load = useCallback(async () => {
    setLoading(true);
    setError('');
    setPartialError([]);
    try {
      const [src, q, ix, h, cfg, sj] = await Promise.all([
        apiFetch<{ sources: CollectionSourceApi[] }>('/collections/sources'),
        apiFetch<{ count: number; items: QuarantineItem[] }>('/quarantine?limit=50').catch(
          (err: unknown) => {
            setPartialError((prev) => [...prev, '隔离区加载失败']);
            void err;
            return { count: -1, items: [] as QuarantineItem[] };
          },
        ),
        apiFetch<{
          total?: number;
          total_cost_usd?: number;
          total_profit_usd?: number;
          net_usd?: number;
          total_hours?: number;
        }>('/interactions/summary').catch((err: unknown) => {
          setPartialError((prev) => [...prev, '成本汇总加载失败']);
          void err;
          return null;
        }),
        fetchHealth().catch(() => null),
        apiFetch<SettingsConfig>('/settings/config').catch((err: unknown) => {
          setPartialError((prev) => [...prev, '调度配置加载失败']);
          void err;
          return null;
        }),
        apiFetch<SchedulerJobsPayload>('/scheduler/jobs').catch((err: unknown) => {
          setPartialError((prev) => [...prev, '调度器任务表加载失败']);
          void err;
          return null;
        }),
      ]);
      setSources((src.sources || []).map(normalizeCollectionSource));
      setQuarantine(q.items || []);
      setQCount(typeof q.count === 'number' ? q.count : 0);
      setIxSummary(ix);
      if (h) setHealth(h as HealthData);
      setAutomation(cfg?.automation ?? null);
      setRuntimeSources(cfg?.sources);
      setSchedJobs(sj);
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '加载失败');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const setSourceEnabled = async (sourceId: string, enabled: boolean) => {
    const prev = sources;
    setSources((list) =>
      list.map((s) =>
        s.source_id === sourceId
          ? { ...s, operatorEnabled: enabled, enabled: s.configReady && enabled }
          : s,
      ),
    );
    setBusy(`toggle-${sourceId}`);
    try {
      const res = await apiFetch<CollectionSourceApi>(`/collections/${sourceId}`, {
        method: 'PATCH',
        body: JSON.stringify({ enabled }),
      });
      const next = normalizeCollectionSource(res);
      setSources((list) => list.map((s) => (s.source_id === sourceId ? next : s)));
      const name = next.source_name || sourceZh(sourceId);
      showToast(
        `${name} ${next.operatorEnabled ? '已启用' : '已禁用'}${
          next.operatorEnabled && !next.configReady ? '（配置未就绪，仍不可采集）' : ''
        }`,
        next.operatorEnabled ? 'success' : 'info',
      );
    } catch (err: unknown) {
      setSources(prev);
      showToast(err instanceof Error ? err.message : '更新开关失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  const trigger = async (sourceId: string) => {
    setBusy(sourceId);
    try {
      const res = await apiFetch<{ status?: string; items_collected?: number }>(
        `/collections/${sourceId}/trigger`,
        { method: 'POST', body: '{}' },
      );
      showToast(
        `${sourceZh(sourceId)} 完成 · ${res.items_collected ?? '—'} items`,
        'success',
      );
      load();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : `${sourceId} 失败`, 'error');
    } finally {
      setBusy(null);
    }
  };

  const triggerAllEnabled = async () => {
    const list = sources.filter((s) => s.enabled);
    if (!list.length) {
      showToast('没有可触发的采集源（需开关打开且配置就绪）', 'error');
      return;
    }
    setBusy('all');
    let ok = 0;
    let fail = 0;
    for (const s of list) {
      try {
        await apiFetch(`/collections/${s.source_id}/trigger`, { method: 'POST', body: '{}' });
        ok += 1;
      } catch {
        fail += 1;
      }
    }
    showToast(`已触发 ${ok} 个源${fail ? ` · 失败 ${fail}` : ''}`, fail ? 'error' : 'success');
    setBusy(null);
    load();
  };

  const release = async (rawId: string) => {
    setBusy(rawId);
    try {
      await apiFetch('/quarantine/release', {
        method: 'POST',
        body: JSON.stringify({ raw_id: rawId }),
      });
      showToast('已释放出隔离区', 'success');
      load();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '释放失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  const operatorOn = sources.filter((s) => s.operatorEnabled).length;

  /** 导出项目列表（Excel / CSV）。走后端 /export/projects，不是前端自己拼 CSV。 */
  const exportProjects = async (format: 'excel' | 'csv') => {
    setBusy(`export-${format}`);
    try {
      const name = await downloadFile(
        `/export/projects?format=${format}`,
        format === 'excel' ? 'projects.xlsx' : 'projects.csv',
      );
      showToast(`已导出 ${name}`, 'success');
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '导出失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  /** 下载导入模板（后端 /export/template 生成，含示例行与字段说明） */
  const downloadTemplate = async () => {
    setBusy('template');
    try {
      const name = await downloadFile('/export/template', 'import_template.xlsx');
      showToast(`已下载 ${name}`, 'success');
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '下载模板失败', 'error');
    } finally {
      setBusy(null);
    }
  };

  /**
   * 上传并导入。
   *
   * 三件事必须自己做，不能交给 apiFetch：
   * 1. 用 FormData，且**不能设 Content-Type** —— 手动设会覆盖掉 multipart
   *    的 boundary，后端解析直接失败。apiFetch 恰好写死了 application/json。
   * 2. 前端先挡掉超限文件。后端有 10MB / 100 项上限，但等传完再被拒
   *    是白等一次上传。
   * 3. 导入成功后 `load()` 刷新，否则页面上的统计还是导入前的旧值。
   */
  const importProjects = async (file: File) => {
    const reject = validateUploadFile(file.name, file.size);
    if (reject) {
      showToast(reject, 'error');
      return;
    }

    setBusy('import');
    setImportResult(null);
    try {
      const form = new FormData();
      form.append('file', file);
      // 注意：不要设 Content-Type，交给浏览器生成带 boundary 的 multipart 头
      const res = await fetch(`${API_PREFIX}/import/projects`, { method: 'POST', body: form });
      const text = await res.text();

      if (!res.ok) {
        throw new Error(errorMessageFromBody(text, res.status, '导入'));
      }

      let json: {
        ok?: boolean;
        data?: { project_count?: number; top_score?: number; validation_errors?: string[] };
      };
      try {
        json = JSON.parse(text) as typeof json;
      } catch {
        throw new Error(`导入失败：后端返回非 JSON（HTTP ${res.status}）`);
      }
      if (json.ok === false) {
        throw new Error(errorMessageFromBody(text, res.status, '导入'));
      }

      const data = json.data ?? {};
      const errors = data.validation_errors ?? [];
      setImportResult({
        filename: file.name,
        at: new Date().toISOString(),
        projectCount: data.project_count ?? 0,
        topScore: typeof data.top_score === 'number' ? data.top_score : null,
        errors,
      });
      showToast(
        `导入 ${data.project_count ?? 0} 项${errors.length ? ` · ${errors.length} 行有问题` : ''}`,
        errors.length ? 'info' : 'success',
      );
      load();
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : '导入失败', 'error');
    } finally {
      setBusy(null);
      // 清空 input，否则选同一个文件不会再触发 change
      if (fileInputRef.current) fileInputRef.current.value = '';
    }
  };

  const runnable = sources.filter((s) => s.enabled).length;
  const net = ixSummary?.net_usd ?? 0;

  return (
    <>
      {toast ? <Toast message={toast.message} type={toast.type} /> : null}

      {/* topbar — unified header */}
      <TopBar
        title="运维台"
        subtitle={
          <>
            采集源管理 · 隔离区 · 健康检查 · 开关写入{' '}
            <code className="font-mono text-[11px]">data_sources.enabled</code>
          </>
        }
      >
        <button
          type="button"
          className="btn-secondary inline-flex items-center gap-1.5"
          onClick={load}
          disabled={loading}
        >
          <HeartPulse className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">健康检查</span>
        </button>
        <button
          type="button"
          className="btn-primary"
          onClick={triggerAllEnabled}
          disabled={busy === 'all' || runnable === 0 || loading}
          title={runnable === 0 ? '请先启用至少一个可触发源' : `触发 ${runnable} 个源`}
        >
          {busy === 'all' ? '触发中…' : '触发全部已启用源'}
        </button>
      </TopBar>

    <div className="app-content animate-fade-in">

      {error ? (
        <div className="mt-4 border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
          {error}
          <button type="button" className="ml-3 underline" onClick={load}>
            重试
          </button>
        </div>
      ) : null}

      {partialError.length > 0 ? (
        <div className="mt-4 border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
          部分数据加载失败：{partialError.join('、')}
        </div>
      ) : null}

      {/* 4 metrics like design */}
      <div className="mt-5 grid grid-cols-2 gap-2.5 lg:grid-cols-4">
        <Metric
          label="采集源"
          value={loading ? '—' : sources.length}
          hint={`启用 ${operatorOn}`}
        />
        <Metric
          label="健康"
          value={health == null ? '…' : health.ok ? 'OK' : 'DOWN'}
          hint={health?.db_backend || health?.status || '—'}
          tone={health?.ok ? 'farm' : 'default'}
        />
        <Metric
          label="隔离"
          value={qCount < 0 ? '—' : qCount}
          hint="待复核"
          tone="watch"
        />
        <Metric
          label="净成本"
          value={formatUsd(net)}
          hint={`${ixSummary?.total ?? 0} 条记录`}
          tone={net < 0 ? 'watch' : 'farm'}
        />
      </div>

      {/* main grid: sources | cost + health */}
      <div className="mt-4 grid grid-cols-1 gap-3 lg:grid-cols-[1.25fr_0.75fr]">
        {/* sources panel */}
        <section className="mt-4">
          <div className="mb-3 flex items-baseline justify-between gap-3">
            <h2 className="text-sm font-semibold text-ink">采集源</h2>
            <span className="font-mono text-[11px] text-ink-faint">
              {operatorOn} / {sources.length} 启用 · 可触发 {runnable}
            </span>
          </div>

          {loading ? (
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
              {[...Array(6)].map((_, i) => (
                <div key={i} className="ops-card skeleton h-40" />
              ))}
            </div>
          ) : sources.length === 0 ? (
            <div className="ops-card p-5">
              <EmptyState title="无采集源" description="后端未注册采集器" />
            </div>
          ) : (
            <div className="ops-sources-grid" role="list">
              {sources.map((s) => {
                const name = s.source_name || sourceZh(s.source_id);
                const toggling = busy === `toggle-${s.source_id}`;
                const cronExpr = cronOf(s.source_id, runtimeSources);
                return (
                  <article
                    key={s.source_id}
                    role="listitem"
                    className={`ops-card ops-source ${!s.operatorEnabled ? 'opacity-75' : ''}`}
                  >
                    <div className="ops-source-top">
                      <span className="ops-source-name">{name}</span>
                      <Switch
                        checked={s.operatorEnabled}
                        disabled={toggling || busy === s.source_id}
                        label={`${name}${s.operatorEnabled ? '：已启用' : '：已禁用'}`}
                        onChange={(next) => setSourceEnabled(s.source_id, next)}
                      />
                    </div>
                    <div className="ops-source-meta">
                      <span className="font-mono text-[11px] text-ink-faint">{s.source_id}</span>
                      <span className="badge bg-surface-3 text-ink-muted">API</span>
                    </div>
                    <div className="ops-source-schedule">
                      <span className="ops-cron">
                        <Clock className="h-3.5 w-3.5 text-ink-muted" strokeWidth={2} />
                        <span className="font-mono text-xs">{cronExpr ?? '—'}</span>
                      </span>
                      <span className="text-[11px] text-ink-faint">
                        {s.last_sync ? `上次 ${relativeTime(s.last_sync)}` : '从未同步'}
                        {s.sync_status && s.operatorEnabled ? ` · ${syncStatusZh(s.sync_status)}` : ''}
                      </span>
                    </div>
                    <div className="ops-source-foot">
                      {/* 用后端真实的 api_calls_today，不再画写死的配额进度条 */}
                      <span className="text-[11px] text-ink-faint">
                        {s.apiCallsToday != null ? `今日调用 ${s.apiCallsToday} 次` : '今日调用 —'}
                      </span>
                      <button
                        type="button"
                        className="btn-secondary !min-h-8 !px-3 !text-xs"
                        disabled={!s.enabled || busy === s.source_id || toggling}
                        title={!s.operatorEnabled ? '请先打开开关' : !s.configReady ? '配置未就绪' : '立即采集'}
                        onClick={() => trigger(s.source_id)}
                      >
                        {busy === s.source_id ? '…' : '采集'}
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          )}
        </section>

        {/* right rail */}
        <div className="flex flex-col gap-3">
          <section className="ops-card p-4 sm:p-5">
            <h2 className="mb-3 text-sm font-semibold text-ink">交互成本汇总</h2>
            <Kv k="记录数" v={ixSummary?.total ?? 0} />
            <Kv k="总成本" v={formatUsd(ixSummary?.total_cost_usd)} />
            <Kv k="总收益" v={formatUsd(ixSummary?.total_profit_usd)} />
            <Kv k="净额" v={formatUsd(ixSummary?.net_usd)} />
            <Kv k="总工时" v={`${(ixSummary?.total_hours ?? 0).toFixed(1)} h`} />
          </section>

          <section className="ops-card p-4 sm:p-5">
            <div className="mb-3 flex items-center justify-between gap-2">
              <h2 className="text-sm font-semibold text-ink">健康检查</h2>
              <button
                type="button"
                className="btn-ghost !min-h-7 !px-2 !text-xs"
                onClick={load}
                disabled={loading}
              >
                刷新
              </button>
            </div>
            <Kv
              k="状态"
              v={
                <span
                  className={`badge ${
                    health?.ok
                      ? 'bg-farm-soft text-farm dark:bg-farm/15 dark:text-farm'
                      : 'bg-surface-3 text-ink-muted'
                  }`}
                >
                  {health?.status || (health?.ok ? 'healthy' : '—')}
                </span>
              }
            />
            <Kv k="版本" v={health?.version || '—'} />
            <Kv k="数据库" v={health?.db_backend || health?.db || '—'} />
            <Kv k="鉴权" v={health?.auth_required ? '需要' : '关闭'} />
            <Kv k="反馈" v={health?.feedback_enabled === false ? '关闭' : '开启'} />
          </section>
        </div>
      </div>

      {/* quarantine table full width */}
      <section className="mt-3 ops-card">
        <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <h2 className="text-sm font-semibold text-ink">隔离区 Quarantine</h2>
          <span className="font-mono text-[11px] text-ink-faint">
            {qCount < 0 ? '加载失败' : `${qCount} 条`}
          </span>
        </div>

        {quarantine.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-ink-faint">
            {qCount < 0 ? '隔离区数据加载失败' : '隔离区为空'}
          </div>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left text-sm">
              <thead className="border-b border-line bg-surface-2/80">
                <tr className="font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-muted">
                  <th className="px-4 py-2.5 font-semibold sm:px-5">名称</th>
                  <th className="px-3 py-2.5 font-semibold">源</th>
                  <th className="px-3 py-2.5 font-semibold">发现分</th>
                  <th className="px-3 py-2.5 font-semibold">原因</th>
                  <th className="px-4 py-2.5 font-semibold sm:px-5" />
                </tr>
              </thead>
              <tbody>
                {quarantine.map((q) => (
                  <tr key={q.raw_id} className="border-b border-line last:border-b-0">
                    <td className="px-4 py-3 sm:px-5">
                      <div className="font-medium text-ink">{q.raw_data?.name || q.raw_id}</div>
                      <div className="font-mono text-[11px] text-ink-faint">
                        {q.raw_data?.sector || '—'}
                      </div>
                    </td>
                    <td className="px-3 py-3 font-mono text-xs text-ink-muted">
                      {q.source_id || '—'}
                    </td>
                    <td className="px-3 py-3 font-mono text-xs tabular-nums text-ink-muted">
                      {q.discovery_score != null ? q.discovery_score.toFixed(2) : '—'}
                    </td>
                    <td className="max-w-[240px] px-3 py-3 text-xs text-ink-muted">
                      {q.quarantine_reason || '—'}
                    </td>
                    <td className="px-4 py-3 text-right sm:px-5">
                      <button
                        type="button"
                        className="btn-secondary !min-h-8 !px-3 !text-xs"
                        disabled={busy === q.raw_id}
                        onClick={() => release(q.raw_id)}
                      >
                        {busy === q.raw_id ? '…' : '释放'}
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {/* Import/Export */}
      <section className="mt-4">
        <div className="mb-3 flex items-baseline gap-3">
          <h2 className="text-sm font-semibold text-ink">数据导入导出</h2>
        </div>
        <div className="ops-io-grid">
          <article className="ops-card ops-io-card">
            <span className="text-xs text-ink-muted">按当前筛选导出项目列表</span>
            <div className="ops-io-actions">
              <button
                type="button"
                className="btn-secondary inline-flex items-center gap-1.5"
                onClick={() => exportProjects('excel')}
                disabled={busy === 'export-excel' || busy === 'export-csv'}
              >
                <FileSpreadsheet className="h-4 w-4" strokeWidth={2} />
                <span className="text-sm">{busy === 'export-excel' ? '导出中…' : '导出 Excel'}</span>
              </button>
              <button
                type="button"
                className="btn-secondary inline-flex items-center gap-1.5"
                onClick={() => exportProjects('csv')}
                disabled={busy === 'export-excel' || busy === 'export-csv'}
              >
                <FileText className="h-4 w-4" strokeWidth={2} />
                <span className="text-sm">{busy === 'export-csv' ? '导出中…' : '导出 CSV'}</span>
              </button>
            </div>
            <span className="mt-auto text-[11px] text-ink-faint">
              导出全部项目 · 后端支持 label / sector / stage / 最低分筛选参数
            </span>
          </article>
          <article className="ops-card ops-io-card">
            <span className="text-xs text-ink-muted">上传 xlsx / csv，自动校验并评分</span>
            <input
              ref={fileInputRef}
              type="file"
              accept=".xlsx,.csv"
              className="hidden"
              onChange={(e) => {
                const f = e.target.files?.[0];
                if (f) importProjects(f);
              }}
            />
            <div
              className="ops-upload"
              role="button"
              tabIndex={0}
              aria-label="上传导入文件"
              aria-busy={busy === 'import'}
              onClick={() => fileInputRef.current?.click()}
              onKeyDown={(e) => {
                if (e.key === 'Enter' || e.key === ' ') {
                  e.preventDefault();
                  fileInputRef.current?.click();
                }
              }}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                const f = e.dataTransfer.files?.[0];
                if (f) importProjects(f);
              }}
            >
              <UploadCloud className="h-5 w-5 text-ink-muted" strokeWidth={2} />
              <span className="ops-upload-title">
                {busy === 'import' ? '导入中…' : '拖拽文件到此处'}
              </span>
              <span className="ops-upload-link">或点击选择</span>
              <span className="text-[11px] text-ink-faint">≤10MB · ≤100 项</span>
            </div>
            <div className="ops-io-bottom">
              <button
                type="button"
                className="btn-secondary inline-flex items-center gap-1.5 !px-2.5 !py-1 !text-xs"
                onClick={downloadTemplate}
                disabled={busy === 'template'}
              >
                <Download className="h-3.5 w-3.5" strokeWidth={2} />
                <span>{busy === 'template' ? '下载中…' : '下载模板'}</span>
              </button>
              {/* 只显示本次会话真实发生过的导入。此处此前写死「08-02 · 24 项成功 /
                  2 项失败」—— 后端没有导入历史接口，那串数字纯属编造。
                  没导入过就说没有，不假造历史。 */}
              <span className="text-[11px] text-ink-faint">
                {importResult
                  ? `最近导入：${relativeTime(importResult.at)} · ${importResult.filename} · ${importResult.projectCount} 项${
                      importResult.errors.length ? ` · ${importResult.errors.length} 行有问题` : ''
                    }`
                  : '本次会话尚未导入（后端无导入历史接口）'}
              </span>
            </div>
            {importResult && importResult.errors.length > 0 ? (
              <details className="mt-2 text-[11px] text-ink-muted">
                <summary className="cursor-pointer">
                  展开 {importResult.errors.length} 条校验问题
                </summary>
                <ul className="mt-1.5 list-disc space-y-0.5 pl-4">
                  {importResult.errors.slice(0, 20).map((e, i) => (
                    <li key={i}>{e}</li>
                  ))}
                </ul>
                {importResult.errors.length > 20 ? (
                  <p className="mt-1 text-ink-faint">
                    仅显示前 20 条，共 {importResult.errors.length} 条
                  </p>
                ) : null}
              </details>
            ) : null}
          </article>
          <article className="ops-card ops-io-card">
            <span className="text-xs text-ink-muted">进程内双调度模型</span>
            <ul className="ops-sched-list">
              <li>
                <span className="ops-sched-key">采集调度</span>
                <span className="font-mono text-[11.5px] text-ink-muted">按源 cron</span>
              </li>
              <li>
                <span className="ops-sched-key">分析调度</span>
                {/* 真实值，不再写死 —— 下面「调度配置」表里也是这一项 */}
                <span className="font-mono text-[11.5px] text-ink-muted">
                  {automation?.CRON_EXPRESSION ?? '—'}
                </span>
              </li>
              <li>
                <span className="ops-sched-key">在飞守卫</span>
                <span className="font-mono text-[11.5px] text-ink-muted">队列排空全局单次</span>
              </li>
            </ul>
            <span className="mt-auto text-[11px] text-ink-faint">重入返回 409 · misfire 自动补跑</span>
          </article>
        </div>
      </section>

      {/* 调度器任务表（GET /api/v1/scheduler/jobs）。
          此前整个运维台看不到"哪些定时任务真的注册上了"，而归档功能从上线到
          2026-08-24 一次都没被触发过 —— 靠翻数据库才发现。
          这里刻意把「应当注册却没注册」单独列出来：缺失才是那次事故的形态。 */}
      <section className="mt-4 ops-card">
        <div className="flex flex-wrap items-baseline justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <h2 className="text-sm font-semibold text-ink">调度器任务表</h2>
          <span className="text-xs text-ink-muted">只读 · 时区 {schedJobs?.timezone ?? '—'}</span>
        </div>

        {(() => {
          const state = schedulerStateLabel(schedJobs);
          const missing = schedJobs?.missing_jobs ?? null;
          return (
            <>
              <div className="flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line px-4 py-3 text-[13px] sm:px-5">
                <span className="text-ink-muted">
                  状态{' '}
                  <span
                    className={
                      state.tone === 'farm'
                        ? 'font-medium text-farm'
                        : state.tone === 'watch'
                          ? 'font-medium text-watch'
                          : 'font-medium text-ink'
                    }
                  >
                    {state.text}
                  </span>
                </span>
                <span className="text-ink-muted">
                  已注册{' '}
                  <span className="font-mono font-medium tabular-nums text-ink">
                    {schedJobs?.job_count ?? '—'}
                  </span>
                  {' / 应有 '}
                  <span className="font-mono font-medium tabular-nums text-ink">
                    {schedJobs?.expected_job_count ?? '—'}
                  </span>
                </span>
                {missing && missing.length > 0 && (
                  <span className="font-medium text-watch">缺失 {missing.length} 个</span>
                )}
              </div>

              {state.detail && (
                <div className="border-b border-line px-4 py-2.5 text-xs text-ink-muted sm:px-5">
                  {state.detail}
                </div>
              )}

              {missing && missing.length > 0 && (
                <div className="border-b border-line bg-watch/5 px-4 py-2.5 text-xs sm:px-5">
                  <span className="font-medium text-watch">开关开着却没注册：</span>{' '}
                  <span className="font-mono text-ink">{missing.join('、')}</span>
                  <span className="text-ink-muted"> —— 请查启动日志</span>
                </div>
              )}

              {schedJobs && schedJobs.jobs.length > 0 ? (
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[520px] text-left text-sm">
                    <thead className="border-b border-line bg-surface-2/80">
                      <tr className="font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-muted">
                        <th className="px-4 py-2.5 font-semibold sm:px-5">任务</th>
                        <th className="px-3 py-2.5 font-semibold">下次运行</th>
                        <th className="px-4 py-2.5 font-semibold sm:px-5">受控开关</th>
                      </tr>
                    </thead>
                    <tbody>
                      {schedJobs.jobs.map((job) => (
                        <tr key={job.id} className="border-b border-line last:border-b-0">
                          <td className="px-4 py-3 sm:px-5">
                            <span className="font-mono text-[12px] text-ink">{job.id}</span>
                            <span className="ml-2 text-xs text-ink-muted">{job.name}</span>
                          </td>
                          <td className="whitespace-nowrap px-3 py-3 font-mono text-xs text-ink-muted">
                            {formatNextRun(job.next_run_time)}
                          </td>
                          <td className="px-4 py-3 font-mono text-[11px] text-ink-faint sm:px-5">
                            {job.owner_switch}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              ) : (
                <div className="px-4 py-4 text-sm text-ink-muted sm:px-5">
                  {loading ? '加载中…' : '任务表为空 —— 原因见上方状态说明'}
                </div>
              )}
            </>
          );
        })()}
      </section>

      {/* 调度配置（真实值来自 /settings/config 的 automation 块）。
          「运行历史 / 手动触发单个 job」后端仍没有接口，所以这里只展示配置事实，
          不编造 lastResult，也不放点了没反应的开关和按钮。
          （「下次运行时间」已经有了 —— 见上面那张任务表。） */}
      <section className="mt-4 ops-card">
        <div className="flex items-baseline justify-between gap-3 border-b border-line px-4 py-3 sm:px-5">
          <h2 className="text-sm font-semibold text-ink">调度配置</h2>
          <span className="text-xs text-ink-muted">只读 · 改动需编辑 .env 并重启</span>
        </div>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[520px] text-left text-sm">
            <thead className="border-b border-line bg-surface-2/80">
              <tr className="font-mono text-[10px] font-semibold uppercase tracking-[0.06em] text-ink-muted">
                <th className="px-4 py-2.5 font-semibold sm:px-5">配置项</th>
                <th className="px-3 py-2.5 font-semibold">环境变量</th>
                <th className="px-4 py-2.5 font-semibold sm:px-5">当前值</th>
              </tr>
            </thead>
            <tbody>
              {[
                { name: '分析调度器', env: 'SCHEDULER_ENABLED', value: boolZh(automation?.SCHEDULER_ENABLED) },
                { name: '采集调度器', env: 'COLLECTION_SCHEDULER_ENABLED', value: boolZh(automation?.COLLECTION_SCHEDULER_ENABLED) },
                { name: '采集后自动分析', env: 'COLLECTION_AUTO_RUN_ENABLED', value: boolZh(automation?.COLLECTION_AUTO_RUN_ENABLED) },
                { name: '分析 cron', env: 'CRON_EXPRESSION', value: automation?.CRON_EXPRESSION ?? '—' },
                { name: '单次分析上限', env: 'ANALYSIS_RUN_LIMIT', value: numOr(automation?.ANALYSIS_RUN_LIMIT) },
                { name: 'misfire 补跑窗口', env: 'SCHEDULER_MISFIRE_GRACE_SECONDS', value: numOr(automation?.SCHEDULER_MISFIRE_GRACE_SECONDS, ' 秒') },
                // 归档子系统的配置此前整个运维台都没展示。它是真实在跑的
                // 定时任务（03:00），运维台不列出来，看这一页的人不会知道
                // 每天凌晨有个作业在删数据。
                { name: '归档调度器', env: 'ARCHIVE_SCHEDULER_ENABLED', value: boolZh(automation?.ARCHIVE_SCHEDULER_ENABLED) },
                { name: '归档 cron', env: 'ARCHIVE_CRON', value: automation?.ARCHIVE_CRON ?? '—' },
              ].map((row) => (
                <tr key={row.env} className="border-b border-line last:border-b-0">
                  <td className="px-4 py-3 font-medium text-ink sm:px-5">{row.name}</td>
                  <td className="px-3 py-3 font-mono text-[11px] text-ink-faint">{row.env}</td>
                  <td className="px-4 py-3 font-mono text-xs text-ink-muted sm:px-5">{row.value}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <p className="ops-section-foot">
          由 analysis_scheduler + 采集调度器驱动 · 错过触发自动补跑 · 重入返回 409
        </p>
      </section>
    </div>
    </>
  );
}
