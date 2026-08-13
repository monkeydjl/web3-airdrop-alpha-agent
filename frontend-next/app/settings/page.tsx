'use client';

import {
  BrainCircuit,
  CalendarClock,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  Layers,
  RotateCcw,
  Save,
} from 'lucide-react';
import { useState } from 'react';
import { TopBar } from '@/components/TopBar';
import { Switch, Toast } from '@/components/ui';

// ── 配置数据（只读展示，对齐设计稿默认值） ──

interface WeightRow {
  name: string;
  env: string;
  value: number;
}

const WEIGHTS: WeightRow[] = [
  { name: '空投信号', env: 'WEIGHT_AIRDROP_SIGNAL', value: 0.18 },
  { name: '叙事时机', env: 'WEIGHT_NARRATIVE_TIMING', value: 0.15 },
  { name: '执行力', env: 'WEIGHT_EXECUTION', value: 0.13 },
  { name: '团队声誉', env: 'WEIGHT_TEAM_REPUTATION', value: 0.12 },
  { name: '风险', env: 'WEIGHT_RISK', value: 0.12 },
  { name: '代币经济学', env: 'WEIGHT_TOKENOMICS', value: 0.10 },
  { name: '竞争格局', env: 'WEIGHT_COMPETITION', value: 0.10 },
  { name: '透明度', env: 'WEIGHT_TRANSPARENCY', value: 0.10 },
];

interface SourceConfig {
  name: string;
  tier: string;
  env: string;
  enabled: boolean;
  fields: { label: string; env: string; value: string; mono?: boolean; password?: boolean; placeholder?: string }[];
}

const SOURCES: SourceConfig[] = [
  {
    name: 'DefiLlama', tier: 'P0 · 免费', env: 'DEFILLAMA_ENABLED', enabled: true,
    fields: [
      { label: 'Base URL', env: 'DEFILLAMA_BASE_URL', value: 'https://api.llama.fi', mono: true },
      { label: '超时（秒）', env: 'DEFILLAMA_TIMEOUT', value: '30' },
    ],
  },
  {
    name: 'GitHub', tier: 'P0 · Token 5000 req/h', env: 'GITHUB_ENABLED', enabled: true,
    fields: [
      { label: 'API Token', env: 'GITHUB_TOKEN', value: '', mono: true, password: true, placeholder: 'ghp_…（未设置，限 60 req/h）' },
      { label: 'Base URL', env: 'GITHUB_API_BASE_URL', value: 'https://api.github.com', mono: true },
    ],
  },
  {
    name: 'CoinGecko', tier: 'P0 · 10-30 calls/min', env: 'COINGECKO_ENABLED', enabled: true,
    fields: [
      { label: 'API Key', env: 'COINGECKO_API_KEY', value: '', mono: true, password: true, placeholder: 'CG-…（未设置，走免费额度）' },
      { label: 'Base URL', env: 'COINGECKO_API_BASE_URL', value: 'https://api.coingecko.com/api/v3', mono: true },
    ],
  },
  {
    name: 'Twitter / X', tier: 'P0 · 付费 Basic', env: 'TWITTER_ENABLED', enabled: false,
    fields: [
      { label: 'Bearer Token', env: 'TWITTER_BEARER_TOKEN', value: '', mono: true, password: true, placeholder: '未设置' },
      { label: 'KOL 账号列表', env: 'TWITTER_KOL_ACCOUNTS', value: 'a16z,paradigm,VitalikButerin,…', mono: true },
      { label: '监听关键词', env: 'TWITTER_KEYWORDS', value: '#airdrop,#testnet,#points,…', mono: true },
    ],
  },
  {
    name: 'Etherscan', tier: 'P1 · 链上数据', env: 'ETHERSCAN_ENABLED', enabled: false,
    fields: [
      { label: 'API Key', env: 'ETHERSCAN_API_KEY', value: '', mono: true, password: true, placeholder: '未设置' },
    ],
  },
  {
    name: 'RootData', tier: '可选 · 融资/项目库', env: 'ROOTDATA_ENABLED', enabled: false,
    fields: [
      { label: 'API Key', env: 'ROOTDATA_API_KEY', value: '', mono: true, password: true, placeholder: '未设置' },
      { label: 'Base URL', env: 'ROOTDATA_BASE_URL', value: 'https://api.rootdata.com', mono: true },
    ],
  },
];

interface FlagItem {
  name: string;
  env: string;
  desc: string;
  enabled: boolean;
}

const FLAGS: FlagItem[] = [
  { name: 'LLM 增强', env: 'ENABLE_LLM_ENHANCEMENT', desc: '需先配置 OPENAI_API_KEY', enabled: false },
  { name: '反馈系统', env: 'ENABLE_FEEDBACK_SYSTEM', desc: '样本采集默认开启', enabled: true },
  { name: 'Opportunity 影子评估', env: 'OPPORTUNITY_SHADOW_ENABLED', desc: 'v2.0 非权威对照评分', enabled: true },
  { name: '经济数据快照', env: 'OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED', desc: 'Opportunity v2.0 经济数据层总开关', enabled: true },
  { name: '事件追踪', env: 'ENABLE_EVENTS_TRACKING', desc: '埋点上报', enabled: false },
  { name: '用户系统', env: 'ENABLE_USER_SYSTEM', desc: '多用户与权限', enabled: false },
  { name: '竞争格局缓存', env: 'ENABLE_COMPETITION_CACHE', desc: '减少重复计算', enabled: true },
  { name: 'Prometheus 指标', env: 'METRICS_ENABLED', desc: '/metrics 端点', enabled: true },
];

// ── 子组件 ──

function SettingRow({
  label,
  env,
  desc,
  children,
}: {
  label: string;
  env: string;
  desc?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="set-row">
      <div className="set-row-labels">
        <span className="set-row-label">{label}</span>
        <span className="set-row-env">{env}</span>
        {desc ? <span className="set-row-desc">{desc}</span> : null}
      </div>
      <div className="set-row-control">{children}</div>
    </div>
  );
}

function SecretInput({ placeholder, value }: { placeholder?: string; value?: string }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="set-secret-wrap">
      <input
        type={visible ? 'text' : 'password'}
        className="set-input"
        data-mono="true"
        placeholder={placeholder}
        defaultValue={value}
        aria-label={placeholder || '密钥'}
      />
      <button
        type="button"
        className="set-secret-eye"
        onClick={() => setVisible((v) => !v)}
        aria-label="显示或隐藏密钥"
      >
        {visible ? <EyeOff className="h-3.5 w-3.5" /> : <Eye className="h-3.5 w-3.5" />}
      </button>
    </div>
  );
}

// ── 主页面 ──

export default function SettingsPage() {
  const [activeSection, setActiveSection] = useState('set-access');
  const [flags, setFlags] = useState(FLAGS);
  const [sources, setSources] = useState(SOURCES);
  const [schedulerOn, setSchedulerOn] = useState(true);
  const [collectionSchedOn, setCollectionSchedOn] = useState(true);
  const [autoRunOn, setAutoRunOn] = useState(false);
  const [toast, setToast] = useState<{ message: string; type: 'success' | 'error' | 'info' } | null>(null);

  const enabledFlags = flags.filter((f) => f.enabled).length;
  const weightSum = WEIGHTS.reduce((s, w) => s + w.value, 0);

  const handleSave = () => {
    setToast({ message: '配置已保存（演示模式 — 实际写入需后端 settings API）', type: 'info' });
  };

  const handleReset = () => {
    setToast({ message: '已还原为默认配置', type: 'success' });
  };

  const navItems = [
    { id: 'set-access', label: '接入层', icon: KeyRound },
    { id: 'set-engine', label: '引擎层', icon: BrainCircuit },
    { id: 'set-automation', label: '自动化层', icon: CalendarClock },
    { id: 'set-platform', label: '平台层', icon: Layers },
  ];

  return (
    <>
      {toast && <Toast message={toast.message} type={toast.type} />}
      <TopBar title="系统设置" subtitle="环境变量 · 数据源凭证 · LLM · 权重 · 调度 · 保留 · 功能开关">
        <button type="button" className="btn-secondary inline-flex items-center gap-1.5" onClick={handleReset}>
          <RotateCcw className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">还原默认</span>
        </button>
        <button type="button" className="btn-primary inline-flex items-center gap-1.5" onClick={handleSave}>
          <Save className="h-4 w-4" strokeWidth={2} />
          <span>保存更改</span>
        </button>
      </TopBar>

      <div className="app-content animate-fade-in">
        <div className="set-layout">
          {/* 锚点子导航 */}
          <nav className="set-side" aria-label="设置分组">
            <div className="set-side-title">配置分层</div>
            {navItems.map((item) => {
              const Icon = item.icon;
              return (
                <a
                  key={item.id}
                  href={`#${item.id}`}
                  className="set-side-item"
                  data-active={activeSection === item.id}
                  onClick={() => setActiveSection(item.id)}
                >
                  <Icon className="h-3.5 w-3.5" strokeWidth={2} />
                  <span>{item.label}</span>
                </a>
              );
            })}
          </nav>

          <div className="set-groups">
            {/* 1. 接入层 */}
            <section className="set-group" id="set-access" aria-label="接入层">
              <div className="set-group-head">
                <div className="set-group-titles">
                  <span className="set-group-name">接入层</span>
                  <span className="set-group-desc">对外暴露的 API 鉴权 / CORS / 限流，以及外部数据源的接入凭证——系统如何被访问、如何连外界。</span>
                </div>
                <span className="set-group-badge" data-tone="warn">鉴权未启用</span>
              </div>
              <div className="set-group-body">
                <div className="set-subhead">服务访问</div>
                <SettingRow label="API Key" env="API_KEY" desc="空 = 无鉴权（本地默认）；生产环境必须 ≥ 32 字符">
                  <SecretInput placeholder="未设置（生产环境必须配置）" />
                  <button type="button" className="btn-secondary px-2.5 py-1 text-xs">测试连接</button>
                </SettingRow>
                <SettingRow label="CORS 来源" env="CORS_ORIGINS" desc="逗号分隔；生产环境禁止 * + credentials 组合">
                  <input type="text" className="set-input" data-mono="true" defaultValue="http://localhost:3002,http://localhost:8002" />
                </SettingRow>
                <SettingRow label="限流阈值" env="RATE_LIMIT_REQUESTS" desc="每窗口最大请求数">
                  <input type="text" className="set-input" data-size="sm" defaultValue="100" />
                  <span className="set-unit">次</span>
                </SettingRow>
                <SettingRow label="限流窗口" env="RATE_LIMIT_WINDOW">
                  <input type="text" className="set-input" data-size="sm" defaultValue="60" />
                  <span className="set-unit">秒</span>
                </SettingRow>

                <div className="set-subhead">
                  数据源凭证 <span className="set-subhead-note">留空 API Key = 匿名配额，速率受限</span>
                </div>
                {sources.map((src, idx) => (
                  <div className="set-source" key={src.env}>
                    <div className="set-source-head">
                      <div className="set-source-titles">
                        <span className="set-source-name">{src.name}</span>
                        <span className="set-source-tier">{src.tier}</span>
                      </div>
                      <div className="set-switch-row">
                        <Switch
                          checked={src.enabled}
                          onChange={(v) => setSources((prev) => prev.map((s, i) => i === idx ? { ...s, enabled: v } : s))}
                          label={`启用 ${src.name}`}
                        />
                        <span className="set-switch-state">{src.enabled ? '已启用' : '已停用'}</span>
                      </div>
                    </div>
                    <div className="set-source-env">{src.env}</div>
                    {src.fields.map((field) => (
                      <div className="set-source-field" key={field.env}>
                        <label className="set-source-label">
                          {field.label}
                          <span className="set-source-env">{field.env}</span>
                        </label>
                        {field.password ? (
                          <SecretInput placeholder={field.placeholder} value={field.value} />
                        ) : (
                          <input
                            type="text"
                            className="set-input"
                            data-mono={field.mono ? 'true' : undefined}
                            defaultValue={field.value}
                            placeholder={field.placeholder}
                          />
                        )}
                      </div>
                    ))}
                  </div>
                ))}
              </div>
            </section>

            {/* 2. 引擎层 */}
            <section className="set-group" id="set-engine" aria-label="引擎层">
              <div className="set-group-head">
                <div className="set-group-titles">
                  <span className="set-group-name">引擎层</span>
                  <span className="set-group-desc">评分决策引擎——评分权重、LLM 增强与质量阈值共同决定项目打分；默认规则引擎，LLM 为可选增强层。</span>
                </div>
                <span className="set-group-badge">当前 · 规则引擎</span>
              </div>
              <div className="set-group-body">
                <div className="set-subhead">
                  LLM 增强 <span className="set-subhead-note">填入 API Key 并开启功能开关后自动启用</span>
                </div>
                <SettingRow label="OpenAI API Key" env="OPENAI_API_KEY" desc="设置后自动启用 LLM 增强">
                  <SecretInput placeholder="sk-…（未设置）" />
                  <button type="button" className="btn-secondary px-2.5 py-1 text-xs">测试连接</button>
                </SettingRow>
                <SettingRow label="Base URL" env="OPENAI_BASE_URL" desc="兼容 OpenAI 协议的代理地址">
                  <input type="text" className="set-input" data-mono="true" defaultValue="https://api.openai.com/v1" />
                </SettingRow>
                <SettingRow label="模型" env="LLM_MODEL" desc="评分增强与 AI 简报使用的模型">
                  <input type="text" className="set-input" data-mono="true" data-size="md" defaultValue="gpt-4o-mini" />
                </SettingRow>
                <SettingRow label="Temperature" env="LLM_TEMPERATURE" desc="0-1，越低越稳定">
                  <input type="text" className="set-input" data-size="sm" defaultValue="0.3" />
                </SettingRow>
                <SettingRow label="Max Tokens" env="LLM_MAX_TOKENS" desc="单次调用上限">
                  <input type="text" className="set-input" data-size="sm" defaultValue="512" />
                </SettingRow>
                <SettingRow label="每日预算" env="LLM_DAILY_BUDGET_USD" desc="超出后自动降级回规则引擎">
                  <input type="text" className="set-input" data-size="sm" defaultValue="1.0" />
                  <span className="set-unit">USD / 天</span>
                </SettingRow>
                <SettingRow label="LLM 启用阈值" env="LLM_DISCOVERY_SCORE_THRESHOLD" desc="仅 discovery_score ≥ 此值的项目走 LLM">
                  <input type="text" className="set-input" data-size="sm" defaultValue="0.7" />
                </SettingRow>

                <div className="set-subhead">
                  评分权重 <span className="set-subhead-note">Σ = 1.0 启动断言；修改生成新 weight_version</span>
                </div>
                <div className="set-weight-grid">
                  {WEIGHTS.map((w) => (
                    <div className="set-weight-row" key={w.env}>
                      <div>
                        <span className="set-weight-name">{w.name}</span>
                        <span className="set-weight-env">{w.env}</span>
                      </div>
                      <div className="set-weight-track">
                        <div className="set-weight-fill" style={{ width: `${Math.round(w.value * 400)}%` }} />
                      </div>
                      <span className="set-weight-val">{w.value.toFixed(2)}</span>
                    </div>
                  ))}
                </div>
                <div className="set-weight-sum">
                  <span>权重合计（启动断言 Σ = 1.0）</span>
                  <b>{weightSum.toFixed(2)} ✓</b>
                </div>

                <div className="set-subhead">质量阈值</div>
                <SettingRow label="分析阈值" env="DISCOVERY_SCORE_ANALYSIS_THRESHOLD" desc="discovery_score ≥ 此值才进入分析管道">
                  <input type="text" className="set-input" data-size="sm" defaultValue="0.3" />
                </SettingRow>
                <SettingRow label="置信度阈值" env="CONFIDENCE_THRESHOLD" desc="低于此值的评分标记为低置信">
                  <input type="text" className="set-input" data-size="sm" defaultValue="0.5" />
                </SettingRow>
                <SettingRow label="缺字段降级阈值" env="MISSING_FIELDS_THRESHOLD" desc="缺失字段数超过此值触发降级">
                  <input type="text" className="set-input" data-size="sm" defaultValue="3" />
                  <span className="set-unit">个</span>
                </SettingRow>
              </div>
            </section>

            {/* 3. 自动化层 */}
            <section className="set-group" id="set-automation" aria-label="自动化层">
              <div className="set-group-head">
                <div className="set-group-titles">
                  <span className="set-group-name">自动化层</span>
                  <span className="set-group-desc">调度器跑什么、什么时候跑，以及数据留多久——无人值守的行为边界。</span>
                </div>
                <span className="set-group-badge" data-tone="ok">调度器运行中</span>
              </div>
              <div className="set-group-body">
                <div className="set-subhead">
                  调度任务 <span className="set-subhead-note">ADR-012 双调度模型</span>
                </div>
                <SettingRow label="分析调度器" env="SCHEDULER_ENABLED" desc="空队列自动触发 /run">
                  <div className="set-switch-row">
                    <Switch checked={schedulerOn} onChange={setSchedulerOn} label="分析调度器" />
                    <span className="set-switch-state">{schedulerOn ? '已启用' : '已停用'}</span>
                  </div>
                </SettingRow>
                <SettingRow label="采集调度器" env="COLLECTION_SCHEDULER_ENABLED" desc="v2.0 各源独立调度">
                  <div className="set-switch-row">
                    <Switch checked={collectionSchedOn} onChange={setCollectionSchedOn} label="采集调度器" />
                    <span className="set-switch-state">{collectionSchedOn ? '已启用' : '已停用'}</span>
                  </div>
                </SettingRow>
                <SettingRow label="采集后自动分析" env="COLLECTION_AUTO_RUN_ENABLED" desc="采集成功后立即触发分析队列">
                  <div className="set-switch-row">
                    <Switch checked={autoRunOn} onChange={setAutoRunOn} label="采集后自动分析" />
                    <span className="set-switch-state">{autoRunOn ? '已启用' : '已停用'}</span>
                  </div>
                </SettingRow>
                <SettingRow label="分析 cron" env="CRON_EXPRESSION" desc="每日全量分析时间">
                  <input type="text" className="set-input" data-mono="true" data-size="md" defaultValue="0 8 * * *" />
                </SettingRow>
                <SettingRow label="DefiLlama 采集" env="DEFILLAMA_CRON">
                  <input type="text" className="set-input" data-mono="true" data-size="md" defaultValue="0 8 * * *" />
                </SettingRow>
                <SettingRow label="GitHub 采集" env="GITHUB_CRON">
                  <input type="text" className="set-input" data-mono="true" data-size="md" defaultValue="30 8 * * *" />
                </SettingRow>
                <SettingRow label="CoinGecko 采集" env="COINGECKO_CRON">
                  <input type="text" className="set-input" data-mono="true" data-size="md" defaultValue="0 9 * * *" />
                </SettingRow>
                <SettingRow label="Twitter 关键词" env="TWITTER_KEYWORD_CRON" desc="高频监听">
                  <input type="text" className="set-input" data-mono="true" data-size="md" defaultValue="*/15 * * * *" />
                </SettingRow>
                <SettingRow label="单次分析上限" env="ANALYSIS_RUN_LIMIT" desc="从 raw_projects 取的最大条数">
                  <input type="text" className="set-input" data-size="sm" defaultValue="100" />
                  <span className="set-unit">条 / 次</span>
                </SettingRow>

                <div className="set-subhead">
                  保留策略 <span className="set-subhead-note">到期由归档管道转入冷存储</span>
                </div>
                <SettingRow label="原始项目快照" env="RAW_PROJECTS_RETENTION_DAYS" desc="raw_projects 表">
                  <input type="text" className="set-input" data-size="sm" defaultValue="30" />
                  <span className="set-unit">天</span>
                </SettingRow>
                <SettingRow label="信号与指标" env="PROJECT_SIGNALS_RETENTION_DAYS" desc="project_signals 表">
                  <input type="text" className="set-input" data-size="sm" defaultValue="90" />
                  <span className="set-unit">天</span>
                </SettingRow>
                <SettingRow label="采集日志" env="COLLECTION_LOGS_RETENTION_DAYS" desc="collection_logs 表">
                  <input type="text" className="set-input" data-size="sm" defaultValue="90" />
                  <span className="set-unit">天</span>
                </SettingRow>
              </div>
            </section>

            {/* 4. 平台层 */}
            <section className="set-group" id="set-platform" aria-label="平台层">
              <div className="set-group-head">
                <div className="set-group-titles">
                  <span className="set-group-name">平台层</span>
                  <span className="set-group-desc">功能开关与可观测性——哪些子系统在线、指标从哪暴露。</span>
                </div>
                <span className="set-group-badge" data-tone="ok">{enabledFlags} / {flags.length} 开启</span>
              </div>
              <div className="set-group-body">
                <div className="set-flag-grid">
                  {flags.map((flag, idx) => (
                    <div className="set-flag" key={flag.env}>
                      <div className="set-flag-texts">
                        <span className="set-flag-name">{flag.name}</span>
                        <span className="set-flag-env">{flag.env}</span>
                        <span className="set-flag-desc">{flag.desc}</span>
                      </div>
                      <Switch
                        checked={flag.enabled}
                        onChange={(v) => setFlags((prev) => prev.map((f, i) => i === idx ? { ...f, enabled: v } : f))}
                        label={flag.name}
                      />
                    </div>
                  ))}
                </div>
                <SettingRow label="指标路径" env="METRICS_PATH" desc="Prometheus metrics 端点">
                  <input type="text" className="set-input" data-mono="true" data-size="md" defaultValue="/metrics" />
                </SettingRow>
                <SettingRow label="日志级别" env="LOG_LEVEL" desc="debug / info / warn / error">
                  <input type="text" className="set-input" data-mono="true" data-size="sm" defaultValue="info" />
                </SettingRow>
              </div>
            </section>

            {/* 保存栏 */}
            <div className="set-savebar">
              <span className="set-savebar-hint">
                <Info className="h-3.5 w-3.5" strokeWidth={2} />
                修改将在保存后写入 .env 并热加载；评分权重变更会生成新版本号。
              </span>
              <div className="set-savebar-actions">
                <button type="button" className="btn-secondary inline-flex items-center gap-1.5" onClick={handleReset}>
                  <RotateCcw className="h-4 w-4" strokeWidth={2} />
                  <span>还原默认</span>
                </button>
                <button type="button" className="btn-primary inline-flex items-center gap-1.5" onClick={handleSave}>
                  <Save className="h-4 w-4" strokeWidth={2} />
                  <span>保存更改</span>
                </button>
              </div>
            </div>
          </div>
        </div>
      </div>
    </>
  );
}
