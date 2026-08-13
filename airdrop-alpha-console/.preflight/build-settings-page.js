// Build settings.html + settings-dark.html from the collections shell.
// Settings page: left anchor sub-nav + grouped env-driven forms
// (data sources / API keys / LLM / scoring weights / scheduler / retention / feature flags).
const fs = require("fs");
const path = require("path");

const PAGES = path.join(__dirname, "..", "pages");
const LIGHT_SHELL = path.join(PAGES, "collections.html");
const DARK_SHELL = path.join(PAGES, "collections-dark.html");

// ---------- helpers ----------
function swapSlot(html, name, value) {
  const re = new RegExp(`(<!--\\s*SLOT:\\s*${name}\\s*-->)([\\s\\S]*?)(<!--\\s*/SLOT:\\s*${name}\\s*-->)`);
  return html.replace(re, `$1${value}$3`);
}
function injectCss(html, css, marker) {
  if (html.includes(marker)) return html;
  const end = html.lastIndexOf("</style>");
  return html.slice(0, end) + css + "\n" + html.slice(end);
}
function clearCollectionsActive(html) {
  return html.replace(
    /<a href="#" class="app-nav-item" data-nav-key="collections" data-active="true">/,
    `<a href="#" class="app-nav-item" data-nav-key="collections" data-dom-id="nav-collections">`
  );
}
function addNavItem(html, { key, label, icon }) {
  if (html.includes(`data-nav-key="${key}"`)) return html;
  // Insert after collections (last nav item), before </nav>
  const item = `      <a href="#" class="app-nav-item" data-nav-key="${key}" data-active="true">
        <i data-lucide="${icon}"></i>
        <span class="app-nav-label">${label}</span>
      </a>
    </nav>`;
  return html.replace(/\s*<\/nav>/, "\n" + item);
}
function setTitle(html, text) {
  return html.replace(/<title>[^<]+<\/title>/, `<title>${text}</title>`);
}

// ============================================================
// CSS
// ============================================================
const settingsCSS = `
  /* ===== page-settings ===== */
  .set-layout {
    display: grid;
    grid-template-columns: 220px 1fr;
    gap: 16px;
    align-items: start;
  }
  .set-side {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 12px;
    display: flex; flex-direction: column; gap: 2px;
    position: sticky; top: 88px;
  }
  .set-side-title {
    padding: 8px 10px 6px;
    font-size: 11.5px; letter-spacing: 0.04em; text-transform: uppercase;
    color: var(--muted-foreground);
  }
  .set-side-item {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px;
    border-radius: var(--radius-md);
    font-size: 13px; color: var(--foreground);
    cursor: pointer; text-decoration: none;
    border: 1px solid transparent;
    background: transparent; text-align: left; width: 100%;
  }
  .set-side-item:hover { background: var(--muted); }
  .set-side-item[data-active="true"] {
    background: var(--alpha-brand-subtle);
    border-color: var(--alpha-brand-border);
    color: var(--primary);
  }
  .set-side-item [data-lucide] { width: 15px; height: 15px; }

  .set-groups { display: flex; flex-direction: column; gap: 16px; min-width: 0; }
  .set-group {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }
  .set-group-head {
    display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
    padding: 16px 18px 14px;
    border-bottom: 1px solid var(--border);
  }
  .set-group-titles { display: flex; flex-direction: column; gap: 3px; }
  .set-group-name { font-size: 14.5px; font-weight: 600; color: var(--foreground); }
  .set-group-desc { font-size: 12.5px; color: var(--muted-foreground); line-height: 1.5; }
  .set-group-badge {
    flex-shrink: 0;
    display: inline-flex; align-items: center; gap: 5px;
    height: 22px; padding: 0 8px;
    border-radius: var(--radius-full);
    font-size: 11.5px;
    background: var(--muted); color: var(--muted-foreground);
  }
  .set-group-badge[data-tone="ok"] { background: var(--alpha-brand-subtle); color: var(--primary); }
  .set-group-badge[data-tone="warn"] { color: var(--state-warning); }
  .set-group-badge[data-tone="err"] { color: var(--state-error); }
  .set-group-body { padding: 6px 18px 16px; }

  .set-subhead {
    display: flex; align-items: baseline; gap: 8px;
    margin: 16px 0 2px;
    padding-bottom: 6px;
    font-size: 12.5px; font-weight: 600; color: var(--foreground);
    border-bottom: 1px dashed var(--border);
  }
  .set-group-body > .set-subhead:first-child { margin-top: 6px; }
  .set-subhead-note { font-size: 11px; font-weight: 400; color: var(--muted-foreground); }

  .set-row {
    display: grid;
    grid-template-columns: 200px 1fr;
    gap: 16px;
    padding: 12px 0;
    border-bottom: 1px solid var(--border);
    align-items: center;
  }
  .set-row:last-child { border-bottom: 0; }
  .set-row-labels { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .set-row-label { font-size: 13px; font-weight: 500; color: var(--foreground); }
  .set-row-env {
    font-family: var(--font-mono); font-size: 10.5px;
    color: var(--muted-foreground);
    letter-spacing: 0.02em;
  }
  .set-row-desc { font-size: 11.5px; color: var(--muted-foreground); line-height: 1.45; }
  .set-row-control { display: flex; align-items: center; gap: 8px; min-width: 0; }

  .set-input, .set-select {
    flex: 1; min-width: 0;
    height: 32px; padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    background: var(--background);
    color: var(--foreground);
    font-size: 12.5px;
    font-family: inherit;
    transition: border-color 120ms var(--ease-default);
  }
  .set-input:focus, .set-select:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 2px var(--alpha-brand-subtle);
  }
  .set-input[data-mono="true"] { font-family: var(--font-mono); font-size: 12px; }
  .set-input[data-size="sm"] { max-width: 120px; flex: 0 0 auto; }
  .set-input[data-size="md"] { max-width: 200px; flex: 0 0 auto; }
  .set-input::placeholder { color: var(--muted-foreground); }

  .set-secret-wrap { position: relative; flex: 1; min-width: 0; display: flex; }
  .set-secret-wrap .set-input { padding-right: 34px; }
  .set-secret-eye {
    position: absolute; right: 6px; top: 50%; transform: translateY(-50%);
    border: 0; background: transparent; padding: 4px; cursor: pointer;
    color: var(--muted-foreground); border-radius: var(--radius-sm);
  }
  .set-secret-eye:hover { color: var(--foreground); }
  .set-secret-eye [data-lucide] { width: 14px; height: 14px; }

  .set-unit { font-size: 12px; color: var(--muted-foreground); white-space: nowrap; }
  .set-cron {
    font-family: var(--font-mono); font-size: 12px;
    padding: 0 10px; height: 32px;
    display: inline-flex; align-items: center;
    border: 1px solid var(--border); border-radius: var(--radius-md);
    background: var(--muted); color: var(--muted-foreground);
  }

  .set-switch-row { display: flex; align-items: center; gap: 10px; }
  .set-switch-state { font-size: 12px; color: var(--muted-foreground); }

  .set-weight-grid { display: flex; flex-direction: column; gap: 10px; padding: 6px 0; }
  .set-weight-row {
    display: grid; grid-template-columns: 160px 1fr 56px; gap: 12px; align-items: center;
  }
  .set-weight-name { font-size: 12.5px; color: var(--foreground); }
  .set-weight-env { font-family: var(--font-mono); font-size: 10px; color: var(--muted-foreground); display: block; }
  .set-weight-track {
    height: 6px; border-radius: var(--radius-full);
    background: var(--muted); overflow: hidden;
  }
  .set-weight-fill { height: 100%; background: var(--primary); border-radius: var(--radius-full); }
  .set-weight-val {
    font-family: var(--font-mono); font-size: 12px;
    color: var(--foreground); text-align: right;
    font-variant-numeric: tabular-nums;
  }
  .set-weight-sum {
    display: flex; align-items: center; justify-content: space-between;
    margin-top: 8px; padding: 10px 12px;
    border-radius: var(--radius-md);
    background: var(--alpha-brand-subtle);
    font-size: 12.5px;
  }
  .set-weight-sum b { font-family: var(--font-mono); color: var(--primary); }

  .set-flag-grid {
    display: grid; grid-template-columns: repeat(2, 1fr); gap: 0 24px;
  }
  .set-flag {
    display: flex; align-items: flex-start; justify-content: space-between; gap: 12px;
    padding: 12px 0; border-bottom: 1px solid var(--border);
  }
  .set-flag:nth-last-child(-n+2) { border-bottom: 0; }
  .set-flag-texts { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .set-flag-name { font-size: 13px; font-weight: 500; color: var(--foreground); }
  .set-flag-env { font-family: var(--font-mono); font-size: 10.5px; color: var(--muted-foreground); }
  .set-flag-desc { font-size: 11.5px; color: var(--muted-foreground); line-height: 1.45; }

  .set-savebar {
    position: sticky; bottom: 16px;
    display: flex; align-items: center; justify-content: space-between; gap: 12px;
    padding: 12px 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-md);
  }
  .set-savebar-hint { font-size: 12px; color: var(--muted-foreground); display: flex; align-items: center; gap: 6px; }
  .set-savebar-hint [data-lucide] { width: 14px; height: 14px; }
  .set-savebar-actions { display: flex; gap: 8px; }

  @media (max-width: 1279px) {
    .set-layout { grid-template-columns: 1fr; }
    .set-side { position: static; flex-direction: row; flex-wrap: wrap; }
    .set-flag-grid { grid-template-columns: 1fr; }
    .set-row { grid-template-columns: 1fr; gap: 8px; }
  }
`;

// ============================================================
// Content builders
// ============================================================
function secretRow(envKey, label, desc, placeholder, masked) {
  return `
        <div class="set-row">
          <div class="set-row-labels">
            <span class="set-row-label">${label}</span>
            <span class="set-row-env">${envKey}</span>
            <span class="set-row-desc">${desc}</span>
          </div>
          <div class="set-row-control">
            <div class="set-secret-wrap">
              <input type="password" class="set-input" data-mono="true" placeholder="${placeholder}" value="${masked ? "••••••••••••••••" : ""}" aria-label="${label}">
              <button type="button" class="set-secret-eye" aria-label="显示或隐藏密钥"><i data-lucide="eye"></i></button>
            </div>
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">测试连接</button>
          </div>
        </div>`;
}
function inputRow(envKey, label, desc, value, opts = {}) {
  const size = opts.size ? ` data-size="${opts.size}"` : "";
  const mono = opts.mono ? ' data-mono="true"' : "";
  const unit = opts.unit ? `<span class="set-unit">${opts.unit}</span>` : "";
  return `
        <div class="set-row">
          <div class="set-row-labels">
            <span class="set-row-label">${label}</span>
            <span class="set-row-env">${envKey}</span>
            <span class="set-row-desc">${desc}</span>
          </div>
          <div class="set-row-control">
            <input type="text" class="set-input"${mono}${size} value="${value}" aria-label="${label}">
            ${unit}
          </div>
        </div>`;
}
function toggleRow(envKey, label, desc, on) {
  return `
        <div class="set-row">
          <div class="set-row-labels">
            <span class="set-row-label">${label}</span>
            <span class="set-row-env">${envKey}</span>
            <span class="set-row-desc">${desc}</span>
          </div>
          <div class="set-row-control">
            <div class="set-switch-row">
              <span class="ops-toggle" data-on="${on}" role="switch" aria-checked="${on}" aria-label="${label}"></span>
              <span class="set-switch-state">${on === "true" ? "已启用" : "已停用"}</span>
            </div>
          </div>
        </div>`;
}
function flagItem(envKey, name, desc, on) {
  return `
          <div class="set-flag">
            <div class="set-flag-texts">
              <span class="set-flag-name">${name}</span>
              <span class="set-flag-env">${envKey}</span>
              <span class="set-flag-desc">${desc}</span>
            </div>
            <span class="ops-toggle" data-on="${on}" role="switch" aria-checked="${on}" aria-label="${name}"></span>
          </div>`;
}
function sourceCard(name, envPrefix, tier, on, fields) {
  return `
        <div class="set-source">
          <div class="set-source-head">
            <div class="set-source-titles">
              <span class="set-source-name">${name}</span>
              <span class="set-source-tier">${tier}</span>
            </div>
            <div class="set-switch-row">
              <span class="ops-toggle" data-on="${on}" role="switch" aria-checked="${on}" aria-label="启用 ${name}"></span>
              <span class="set-switch-state">${on === "true" ? "已启用" : "已停用"}</span>
            </div>
          </div>
          <div class="set-source-env">${envPrefix}_ENABLED</div>
          ${fields}
        </div>`;
}
function sourceField(envKey, label, value, opts = {}) {
  const mono = opts.mono !== false ? ' data-mono="true"' : "";
  const ph = opts.placeholder || "";
  const type = opts.secret ? "password" : "text";
  return `
          <div class="set-source-field">
            <label class="set-source-label">${label}<span class="set-source-env">${envKey}</span></label>
            <input type="${type}" class="set-input"${mono} value="${value}" placeholder="${ph}" aria-label="${label}">
          </div>`;
}

const settingsContent = `
      <div class="set-layout">
        <!-- 锚点子导航 -->
        <nav class="set-side" aria-label="设置分组">
          <div class="set-side-title">配置分层</div>
          <a href="#set-access" class="set-side-item" data-active="true"><i data-lucide="key-round"></i><span>接入层</span></a>
          <a href="#set-engine" class="set-side-item"><i data-lucide="brain-circuit"></i><span>引擎层</span></a>
          <a href="#set-automation" class="set-side-item"><i data-lucide="calendar-clock"></i><span>自动化层</span></a>
          <a href="#set-platform" class="set-side-item"><i data-lucide="layers"></i><span>平台层</span></a>
        </nav>

        <div class="set-groups">

          <!-- 1. 接入层：API 鉴权 + 数据源凭证 -->
          <section class="set-group" id="set-access" aria-label="接入层">
            <div class="set-group-head">
              <div class="set-group-titles">
                <span class="set-group-name">接入层</span>
                <span class="set-group-desc">对外暴露的 API 鉴权 / CORS / 限流，以及外部数据源的接入凭证——系统如何被访问、如何连外界。</span>
              </div>
              <span class="set-group-badge" data-tone="warn">鉴权未启用</span>
            </div>
            <div class="set-group-body">
              <div class="set-subhead">服务访问</div>
              ${secretRow("API_KEY", "API Key", "空 = 无鉴权（本地默认）；生产环境必须 ≥ 32 字符", "未设置（生产环境必须配置）", false)}
              ${inputRow("CORS_ORIGINS", "CORS 来源", "逗号分隔；生产环境禁止 * + credentials 组合", "http://localhost:3002,http://localhost:8002", { mono: true })}
              ${inputRow("RATE_LIMIT_REQUESTS", "限流阈值", "每窗口最大请求数", "100", { size: "sm", unit: "次" })}
              ${inputRow("RATE_LIMIT_WINDOW", "限流窗口", "", "60", { size: "sm", unit: "秒" })}
              <div class="set-subhead">数据源凭证 <span class="set-subhead-note">留空 API Key = 匿名配额，速率受限</span></div>
              ${sourceCard("DefiLlama", "DEFILLAMA", "P0 · 免费", "true",
                sourceField("DEFILLAMA_BASE_URL", "Base URL", "https://api.llama.fi") +
                sourceField("DEFILLAMA_TIMEOUT", "超时（秒）", "30", { mono: false }))}
              ${sourceCard("GitHub", "GITHUB", "P0 · Token 5000 req/h", "true",
                sourceField("GITHUB_TOKEN", "API Token", "", { secret: true, placeholder: "ghp_…（未设置，限 60 req/h）" }) +
                sourceField("GITHUB_API_BASE_URL", "Base URL", "https://api.github.com"))}
              ${sourceCard("CoinGecko", "COINGECKO", "P0 · 10-30 calls/min", "true",
                sourceField("COINGECKO_API_KEY", "API Key", "", { secret: true, placeholder: "CG-…（未设置，走免费额度）" }) +
                sourceField("COINGECKO_API_BASE_URL", "Base URL", "https://api.coingecko.com/api/v3"))}
              ${sourceCard("Twitter / X", "TWITTER", "P0 · 付费 Basic $100/月", "false",
                sourceField("TWITTER_BEARER_TOKEN", "Bearer Token", "", { secret: true, placeholder: "未设置" }) +
                sourceField("TWITTER_KOL_ACCOUNTS", "KOL 账号列表", "a16z,paradigm,VitalikButerin,…") +
                sourceField("TWITTER_KEYWORDS", "监听关键词", "#airdrop,#testnet,#points,…"))}
              ${sourceCard("Etherscan", "ETHERSCAN", "P1 · 链上数据", "false",
                sourceField("ETHERSCAN_API_KEY", "API Key", "", { secret: true, placeholder: "未设置" }))}
              ${sourceCard("RootData", "ROOTDATA", "可选 · 融资/项目库", "false",
                sourceField("ROOTDATA_API_KEY", "API Key", "", { secret: true, placeholder: "未设置" }) +
                sourceField("ROOTDATA_BASE_URL", "Base URL", "https://api.rootdata.com"))}
            </div>
          </section>

          <!-- 2. 引擎层：LLM + 权重 + 阈值 -->
          <section class="set-group" id="set-engine" aria-label="引擎层">
            <div class="set-group-head">
              <div class="set-group-titles">
                <span class="set-group-name">引擎层</span>
                <span class="set-group-desc">评分决策引擎（Scoring Decision Engine）——评分权重、LLM 增强与质量阈值共同决定项目打分；默认规则引擎，LLM 为可选增强层（GLOSSARY §2 / ADR-001 / ADR-006）。</span>
              </div>
              <span class="set-group-badge">当前 · 规则引擎</span>
            </div>
            <div class="set-group-body">
              <div class="set-subhead">LLM 增强 <span class="set-subhead-note">填入 API Key 并开启功能开关后自动启用</span></div>
              ${secretRow("OPENAI_API_KEY", "OpenAI API Key", "设置后自动启用 LLM 增强", "sk-…（未设置）", false)}
              ${inputRow("OPENAI_BASE_URL", "Base URL", "兼容 OpenAI 协议的代理地址", "https://api.openai.com/v1", { mono: true })}
              ${inputRow("LLM_MODEL", "模型", "评分增强与 AI 简报使用的模型", "gpt-4o-mini", { mono: true, size: "md" })}
              ${inputRow("LLM_TEMPERATURE", "Temperature", "0-1，越低越稳定", "0.3", { size: "sm" })}
              ${inputRow("LLM_MAX_TOKENS", "Max Tokens", "单次调用上限", "512", { size: "sm" })}
              ${inputRow("LLM_DAILY_BUDGET_USD", "每日预算", "超出后自动降级回规则引擎", "1.0", { size: "sm", unit: "USD / 天" })}
              ${inputRow("LLM_DISCOVERY_SCORE_THRESHOLD", "LLM 启用阈值", "仅 discovery_score ≥ 此值的项目走 LLM", "0.7", { size: "sm" })}
              <div class="set-subhead">评分权重 <span class="set-subhead-note">Σ = 1.0 启动断言；修改生成新 weight_version</span></div>
              <div class="set-weight-grid">
                <div class="set-weight-row"><div><span class="set-weight-name">空投信号</span><span class="set-weight-env">WEIGHT_AIRDROP_SIGNAL</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 72%"></div></div><span class="set-weight-val">0.18</span></div>
                <div class="set-weight-row"><div><span class="set-weight-name">叙事时机</span><span class="set-weight-env">WEIGHT_NARRATIVE_TIMING</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 60%"></div></div><span class="set-weight-val">0.15</span></div>
                <div class="set-weight-row"><div><span class="set-weight-name">执行力</span><span class="set-weight-env">WEIGHT_EXECUTION</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 52%"></div></div><span class="set-weight-val">0.13</span></div>
                <div class="set-weight-row"><div><span class="set-weight-name">团队声誉</span><span class="set-weight-env">WEIGHT_TEAM_REPUTATION</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 48%"></div></div><span class="set-weight-val">0.12</span></div>
                <div class="set-weight-row"><div><span class="set-weight-name">风险</span><span class="set-weight-env">WEIGHT_RISK</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 48%"></div></div><span class="set-weight-val">0.12</span></div>
                <div class="set-weight-row"><div><span class="set-weight-name">代币经济学</span><span class="set-weight-env">WEIGHT_TOKENOMICS</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 40%"></div></div><span class="set-weight-val">0.10</span></div>
                <div class="set-weight-row"><div><span class="set-weight-name">竞争格局</span><span class="set-weight-env">WEIGHT_COMPETITION</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 40%"></div></div><span class="set-weight-val">0.10</span></div>
                <div class="set-weight-row"><div><span class="set-weight-name">透明度</span><span class="set-weight-env">WEIGHT_TRANSPARENCY</span></div><div class="set-weight-track"><div class="set-weight-fill" style="width: 40%"></div></div><span class="set-weight-val">0.10</span></div>
              </div>
              <div class="set-weight-sum">
                <span>权重合计（启动断言 Σ = 1.0）</span>
                <b>1.00 ✓</b>
              </div>
              <div class="set-subhead">质量阈值</div>
              ${inputRow("DISCOVERY_SCORE_ANALYSIS_THRESHOLD", "分析阈值", "discovery_score ≥ 此值才进入分析管道", "0.3", { size: "sm" })}
              ${inputRow("CONFIDENCE_THRESHOLD", "置信度阈值", "低于此值的评分标记为低置信", "0.5", { size: "sm" })}
              ${inputRow("MISSING_FIELDS_THRESHOLD", "缺字段降级阈值", "缺失字段数超过此值触发降级", "3", { size: "sm", unit: "个" })}
            </div>
          </section>

          <!-- 3. 自动化层：调度 + 保留 -->
          <section class="set-group" id="set-automation" aria-label="自动化层">
            <div class="set-group-head">
              <div class="set-group-titles">
                <span class="set-group-name">自动化层</span>
                <span class="set-group-desc">调度器跑什么、什么时候跑，以及数据留多久——无人值守的行为边界。</span>
              </div>
              <span class="set-group-badge" data-tone="ok">调度器运行中</span>
            </div>
            <div class="set-group-body">
              <div class="set-subhead">调度任务 <span class="set-subhead-note">ADR-012 双调度模型</span></div>
              ${toggleRow("SCHEDULER_ENABLED", "分析调度器", "空队列自动触发 /run", "true")}
              ${toggleRow("COLLECTION_SCHEDULER_ENABLED", "采集调度器", "v2.0 各源独立调度", "true")}
              ${toggleRow("COLLECTION_AUTO_RUN_ENABLED", "采集后自动分析", "采集成功后立即触发分析队列", "false")}
              ${inputRow("CRON_EXPRESSION", "分析 cron", "每日全量分析时间", "0 8 * * *", { mono: true, size: "md" })}
              ${inputRow("DEFILLAMA_CRON", "DefiLlama 采集", "", "0 8 * * *", { mono: true, size: "md" })}
              ${inputRow("GITHUB_CRON", "GitHub 采集", "", "30 8 * * *", { mono: true, size: "md" })}
              ${inputRow("COINGECKO_CRON", "CoinGecko 采集", "", "0 9 * * *", { mono: true, size: "md" })}
              ${inputRow("TWITTER_KEYWORD_CRON", "Twitter 关键词", "高频监听", "*/15 * * * *", { mono: true, size: "md" })}
              ${inputRow("ANALYSIS_RUN_LIMIT", "单次分析上限", "从 raw_projects 取的最大条数", "100", { size: "sm", unit: "条 / 次" })}
              <div class="set-subhead">保留策略 <span class="set-subhead-note">到期由归档管道转入冷存储（见归档历史页）</span></div>
              ${inputRow("RAW_PROJECTS_RETENTION_DAYS", "原始项目快照", "raw_projects 表", "30", { size: "sm", unit: "天" })}
              ${inputRow("PROJECT_SIGNALS_RETENTION_DAYS", "信号与指标", "project_signals 表", "90", { size: "sm", unit: "天" })}
              ${inputRow("COLLECTION_LOGS_RETENTION_DAYS", "采集日志", "collection_logs 表", "90", { size: "sm", unit: "天" })}
            </div>
          </section>

          <!-- 4. 平台层：Feature Flags + 监控 -->
          <section class="set-group" id="set-platform" aria-label="平台层">
            <div class="set-group-head">
              <div class="set-group-titles">
                <span class="set-group-name">平台层</span>
                <span class="set-group-desc">功能开关与可观测性——哪些子系统在线、指标从哪暴露。</span>
              </div>
              <span class="set-group-badge" data-tone="ok">4 / 8 开启</span>
            </div>
            <div class="set-group-body">
              <div class="set-flag-grid">
                ${flagItem("ENABLE_LLM_ENHANCEMENT", "LLM 增强", "需先配置 OPENAI_API_KEY", "false")}
                ${flagItem("ENABLE_FEEDBACK_SYSTEM", "反馈系统", "样本采集默认开启", "true")}
                ${flagItem("OPPORTUNITY_SHADOW_ENABLED", "Opportunity 影子评估", "v2.0 非权威对照评分", "true")}
                ${flagItem("OPPORTUNITY_ECONOMIC_SNAPSHOT_ENABLED", "经济数据快照", "Opportunity v2.0 经济数据层总开关", "true")}
                ${flagItem("ENABLE_EVENTS_TRACKING", "事件追踪", "埋点上报", "false")}
                ${flagItem("ENABLE_USER_SYSTEM", "用户系统", "多用户与权限", "false")}
                ${flagItem("ENABLE_COMPETITION_CACHE", "竞争格局缓存", "减少重复计算", "true")}
                ${flagItem("METRICS_ENABLED", "Prometheus 指标", "/metrics 端点", "true")}
              </div>
              ${inputRow("METRICS_PATH", "指标路径", "Prometheus metrics 端点", "/metrics", { mono: true, size: "md" })}
              ${inputRow("LOG_LEVEL", "日志级别", "debug / info / warn / error", "info", { mono: true, size: "sm" })}
            </div>
          </section>

          <!-- 保存栏 -->
          <div class="set-savebar">
            <span class="set-savebar-hint">
              <i data-lucide="info"></i>
              修改将在保存后写入 .env 并热加载；评分权重变更会生成新版本号。
            </span>
            <div class="set-savebar-actions">
              <button type="button" class="disc-btn disc-btn-secondary"><i data-lucide="rotate-ccw"></i><span>还原默认</span></button>
              <button type="button" class="disc-btn disc-btn-primary" data-dom-id="settings-save"><i data-lucide="save"></i><span>保存更改</span></button>
            </div>
          </div>

        </div>
      </div>`;

// Extra CSS for source cards inside datasources group
const sourceCSS = `
  .set-source {
    border: 1px solid var(--border);
    border-radius: var(--radius-md);
    padding: 12px 14px;
    margin: 10px 0;
    display: flex; flex-direction: column; gap: 8px;
  }
  .set-source-head { display: flex; align-items: center; justify-content: space-between; gap: 10px; }
  .set-source-titles { display: flex; align-items: baseline; gap: 8px; }
  .set-source-name { font-size: 13.5px; font-weight: 600; color: var(--foreground); }
  .set-source-tier { font-size: 11px; color: var(--muted-foreground); }
  .set-source-env { font-family: var(--font-mono); font-size: 10px; color: var(--muted-foreground); letter-spacing: 0.02em; }
  .set-source-field { display: grid; grid-template-columns: 180px 1fr; gap: 12px; align-items: center; }
  .set-source-label { font-size: 12px; color: var(--foreground); display: flex; flex-direction: column; gap: 1px; }
  .set-source-env { font-family: var(--font-mono); font-size: 10px; color: var(--muted-foreground); }
  @media (max-width: 1279px) {
    .set-source-field { grid-template-columns: 1fr; gap: 6px; }
  }
`;

const settingsActions = `
        <button type="button" class="disc-btn disc-btn-secondary">
          <i data-lucide="rotate-ccw"></i>
          <span>还原默认</span>
        </button>
        <button type="button" class="disc-btn disc-btn-primary">
          <i data-lucide="save"></i>
          <span>保存更改</span>
        </button>`;

// ============================================================
// Build
// ============================================================
function build(shellPath, outName, title) {
  let s = fs.readFileSync(shellPath, "utf8");
  s = setTitle(s, title);
  s = swapSlot(s, "pageTitle", `<h1 class="app-page-title alpha-heading">系统设置</h1>`);
  s = swapSlot(s, "pageSubtitle", `<p class="app-page-subtitle">环境变量 · 数据源凭证 · LLM · 权重 · 调度 · 保留 · 功能开关</p>`);
  s = swapSlot(s, "pageActions", settingsActions);
  s = swapSlot(s, "content", settingsContent);
  s = clearCollectionsActive(s);
  s = addNavItem(s, { key: "settings", label: "系统设置", icon: "settings" });
  s = injectCss(s, settingsCSS + sourceCSS, "page-settings");
  fs.writeFileSync(path.join(PAGES, outName), s, "utf8");
  return fs.statSync(path.join(PAGES, outName)).size;
}

const results = [];
results.push(["settings.html", build(LIGHT_SHELL, "settings.html", "系统设置")]);
results.push(["settings-dark.html", build(DARK_SHELL, "settings-dark.html", "系统设置 — 暗色")]);
console.log(JSON.stringify(results.map(([f, b]) => ({ f, bytes: b })), null, 2));
