// Build notifications.html + notifications-dark.html + archive.html + archive-dark.html
// from the collections.html / collections-dark.html shell (which itself derives from discoveries).
// Each page: replace pageTitle/pageSubtitle/pageActions, swap SLOT: content, add its own nav item, inject page CSS.
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
function addNavItem(html, { key, label, icon, self }) {
  if (html.includes(`data-nav-key="${key}"`)) return html;
  const anchorRe = /(\s*<a href="#" class="app-nav-item" data-nav-key="ops"(?:\s+data-active="true")?(?:\s+data-dom-id="[^"]+")?>\s*<i data-lucide="server-cog"><\/i>\s*<span class="app-nav-label">运维台<\/span>\s*<\/a>)/;
  const item = `
      <a href="#" class="app-nav-item" data-nav-key="${key}"${self ? ' data-active="true"' : ` data-dom-id="nav-${key}"`}>
        <i data-lucide="${icon}"></i>
        <span class="app-nav-label">${label}</span>
      </a>`;
  return html.replace(anchorRe, `$1${item}`);
}
function clearCollectionsActive(html) {
  return html.replace(
    /<a href="#" class="app-nav-item" data-nav-key="collections" data-active="true">/,
    `<a href="#" class="app-nav-item" data-nav-key="collections" data-dom-id="nav-collections">`
  );
}
function setTitle(html, text) {
  return html.replace(/<title>[^<]+<\/title>/, `<title>${text}</title>`);
}

// ============================================================
// Notifications page
// ============================================================
const notifCSS = `
  /* ===== page-notifications ===== */
  .ntf-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 16px;
  }
  .ntf-stat {
    padding: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    display: flex; flex-direction: column; gap: 6px;
  }
  .ntf-stat-k { font-size: 12px; color: var(--muted-foreground); }
  .ntf-stat-v {
    font-family: var(--font-mono);
    font-size: 24px; font-weight: 600; line-height: 1;
    color: var(--foreground);
    font-variant-numeric: tabular-nums;
  }
  .ntf-stat-v[data-tone="brand"] { color: var(--primary); }
  .ntf-stat-v[data-tone="warn"]  { color: var(--state-warning); }
  .ntf-stat-v[data-tone="err"]   { color: var(--state-error); }
  .ntf-stat-s { font-size: 12px; color: var(--muted-foreground); }

  .ntf-layout {
    display: grid;
    grid-template-columns: 220px 1fr;
    gap: 16px;
  }
  .ntf-side {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    padding: 12px;
    display: flex; flex-direction: column; gap: 4px;
    align-self: start;
  }
  .ntf-side-title {
    padding: 8px 10px 6px;
    font-size: 11.5px; letter-spacing: 0.04em; text-transform: uppercase;
    color: var(--muted-foreground);
  }
  .ntf-side-item {
    display: flex; align-items: center; gap: 8px;
    padding: 8px 10px;
    border-radius: var(--radius-md);
    font-size: 13px; color: var(--foreground);
    cursor: pointer;
    border: 1px solid transparent;
    background: transparent;
    text-align: left; width: 100%;
  }
  .ntf-side-item:hover { background: var(--muted); }
  .ntf-side-item[data-active="true"] {
    background: var(--alpha-brand-subtle);
    border-color: var(--alpha-brand-border);
    color: var(--primary);
  }
  .ntf-side-count {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 0 6px;
    border-radius: var(--radius-full);
    background: var(--muted);
    color: var(--muted-foreground);
    line-height: 16px;
  }
  .ntf-side-item[data-active="true"] .ntf-side-count { background: var(--alpha-brand-border); color: var(--primary); }

  .ntf-list {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }
  .ntf-list-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid var(--border);
  }
  .ntf-list-title { font-size: 14px; font-weight: 600; color: var(--foreground); }
  .ntf-list-actions { display: flex; gap: 8px; }

  .ntf-item {
    display: grid;
    grid-template-columns: 8px 1fr auto;
    gap: 12px;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
    transition: background-color 120ms var(--ease-default);
  }
  .ntf-item:last-child { border-bottom: 0; }
  .ntf-item:hover { background: var(--muted); }
  .ntf-dot { width: 8px; height: 8px; border-radius: var(--radius-full); margin-top: 6px; }
  .ntf-dot-info    { background: var(--state-info); }
  .ntf-dot-success { background: var(--state-success); }
  .ntf-dot-warning { background: var(--state-warning); }
  .ntf-dot-error   { background: var(--state-error); }
  .ntf-dot-brand   { background: var(--primary); }
  .ntf-body { min-width: 0; display: flex; flex-direction: column; gap: 4px; }
  .ntf-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .ntf-title { font-size: 13.5px; font-weight: 600; color: var(--foreground); }
  .ntf-item[data-read="false"] .ntf-title { color: var(--primary); }
  .ntf-tag {
    display: inline-flex; align-items: center; height: 18px;
    padding: 0 6px;
    font-size: 10.5px;
    border-radius: var(--radius-full);
    background: var(--muted);
    color: var(--muted-foreground);
  }
  .ntf-text { font-size: 12.5px; color: var(--muted-foreground); line-height: 1.55; }
  .ntf-meta { display: flex; gap: 12px; font-size: 11.5px; color: var(--muted-foreground); }
  .ntf-side-actions { display: flex; flex-direction: column; gap: 4px; align-items: flex-end; }
  .ntf-time { font-size: 11.5px; color: var(--muted-foreground); white-space: nowrap; }
  .ntf-item[data-read="true"] { opacity: 0.72; }
  .ntf-link {
    border: 0; background: transparent; padding: 0;
    font-size: 12px; color: var(--primary); cursor: pointer;
  }
  .ntf-link:hover { text-decoration: underline; }

  @media (max-width: 1279px) {
    .ntf-stats { grid-template-columns: repeat(2, 1fr); }
    .ntf-layout { grid-template-columns: 1fr; }
  }
`;

const notifContent = `
      <!-- 1. 概览统计 -->
      <section class="ntf-stats" aria-label="通知概览">
        <div class="ntf-stat">
          <span class="ntf-stat-k">未读</span>
          <span class="ntf-stat-v" data-tone="brand">6</span>
          <span class="ntf-stat-s">过去 24 小时</span>
        </div>
        <div class="ntf-stat">
          <span class="ntf-stat-k">评分上升</span>
          <span class="ntf-stat-v">14</span>
          <span class="ntf-stat-s">本周累计</span>
        </div>
        <div class="ntf-stat">
          <span class="ntf-stat-k">截止时间临近</span>
          <span class="ntf-stat-v" data-tone="warn">3</span>
          <span class="ntf-stat-s">72 小时内</span>
        </div>
        <div class="ntf-stat">
          <span class="ntf-stat-k">采集器告警</span>
          <span class="ntf-stat-v" data-tone="err">1</span>
          <span class="ntf-stat-s">需要处理</span>
        </div>
      </section>

      <!-- 2. 侧栏筛选 + 通知列表 -->
      <div class="ntf-layout">
        <nav class="ntf-side" aria-label="通知分组">
          <div class="ntf-side-title">通知类型</div>
          <button type="button" class="ntf-side-item" data-active="true">
            <i data-lucide="inbox"></i>
            <span>全部</span>
            <span class="ntf-side-count">24</span>
          </button>
          <button type="button" class="ntf-side-item">
            <i data-lucide="trending-up"></i>
            <span>评分变化</span>
            <span class="ntf-side-count">14</span>
          </button>
          <button type="button" class="ntf-side-item">
            <i data-lucide="alarm-clock"></i>
            <span>截止提醒</span>
            <span class="ntf-side-count">3</span>
          </button>
          <button type="button" class="ntf-side-item">
            <i data-lucide="radio"></i>
            <span>采集器</span>
            <span class="ntf-side-count">2</span>
          </button>
          <button type="button" class="ntf-side-item">
            <i data-lucide="wallet"></i>
            <span>资金与融资</span>
            <span class="ntf-side-count">3</span>
          </button>
          <button type="button" class="ntf-side-item">
            <i data-lucide="sparkles"></i>
            <span>AI 摘要</span>
            <span class="ntf-side-count">2</span>
          </button>
        </nav>

        <section class="ntf-list" aria-label="通知列表">
          <div class="ntf-list-head">
            <div class="ntf-list-title alpha-heading">最新动态</div>
            <div class="ntf-list-actions">
              <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
                <i data-lucide="check-check"></i>
                <span>全部已读</span>
              </button>
              <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
                <i data-lucide="settings"></i>
                <span>通知设置</span>
              </button>
            </div>
          </div>

          <div class="ntf-item" data-read="false" data-dom-id="ntf-item-1">
            <span class="ntf-dot ntf-dot-success"></span>
            <div class="ntf-body">
              <div class="ntf-head">
                <span class="ntf-title">Nova Protocol 评分上升 0.12</span>
                <span class="ntf-tag">评分变化</span>
              </div>
              <p class="ntf-text">大模型 v2.0 重新评估后，从 0.76 上调至 0.88。新增生态合作公告 + 测试网交互激励上线。</p>
              <div class="ntf-meta">
                <span>触发源 · opportunity_engine</span>
                <span>项目 · nova-protocol</span>
              </div>
            </div>
            <div class="ntf-side-actions">
              <span class="ntf-time">12 分钟前</span>
              <button type="button" class="ntf-link">查看项目</button>
            </div>
          </div>

          <div class="ntf-item" data-read="false" data-dom-id="ntf-item-2">
            <span class="ntf-dot ntf-dot-warning"></span>
            <div class="ntf-body">
              <div class="ntf-head">
                <span class="ntf-title">Poly Oracle 快照还有 36 小时</span>
                <span class="ntf-tag">截止提醒</span>
              </div>
              <p class="ntf-text">Galxe 任务仍需 2 项才能完成资格；建议在明天 18:00 前补齐。</p>
              <div class="ntf-meta">
                <span>触发源 · analysis_scheduler</span>
                <span>项目 · poly-oracle</span>
              </div>
            </div>
            <div class="ntf-side-actions">
              <span class="ntf-time">1 小时前</span>
              <button type="button" class="ntf-link">前往参与</button>
            </div>
          </div>

          <div class="ntf-item" data-read="false" data-dom-id="ntf-item-3">
            <span class="ntf-dot ntf-dot-error"></span>
            <div class="ntf-body">
              <div class="ntf-head">
                <span class="ntf-title">twitter 采集器连续 3 次失败</span>
                <span class="ntf-tag">采集器告警</span>
              </div>
              <p class="ntf-text">最近 1 小时失败率 100%（401 未授权）。可能是 token 过期，请前往运维台处理。</p>
              <div class="ntf-meta">
                <span>触发源 · collectors</span>
                <span>来源 · twitter</span>
              </div>
            </div>
            <div class="ntf-side-actions">
              <span class="ntf-time">2 小时前</span>
              <button type="button" class="ntf-link">运维台</button>
            </div>
          </div>

          <div class="ntf-item" data-read="true">
            <span class="ntf-dot ntf-dot-brand"></span>
            <div class="ntf-body">
              <div class="ntf-head">
                <span class="ntf-title">Meridian Chain 完成 1,200 万美元 A 轮</span>
                <span class="ntf-tag">资金与融资</span>
              </div>
              <p class="ntf-text">领投方为 Paradigm；项目 FDV 上调至 4.5 亿美元，空投预期由「观察」上调至「关注」。</p>
              <div class="ntf-meta">
                <span>触发源 · funding_tracker</span>
                <span>项目 · meridian-chain</span>
              </div>
            </div>
            <div class="ntf-side-actions">
              <span class="ntf-time">昨天 22:14</span>
              <button type="button" class="ntf-link">查看项目</button>
            </div>
          </div>

          <div class="ntf-item" data-read="true">
            <span class="ntf-dot ntf-dot-info"></span>
            <div class="ntf-body">
              <div class="ntf-head">
                <span class="ntf-title">今日 AI 简报已生成</span>
                <span class="ntf-tag">AI 摘要</span>
              </div>
              <p class="ntf-text">本期聚焦 DePIN 板块异动；新增 3 个高分机会，1 个项目被下调。</p>
              <div class="ntf-meta">
                <span>触发源 · ai_brief</span>
                <span>共 1 节 · 6 条要点</span>
              </div>
            </div>
            <div class="ntf-side-actions">
              <span class="ntf-time">今天 07:30</span>
              <button type="button" class="ntf-link">查看简报</button>
            </div>
          </div>

          <div class="ntf-item" data-read="true">
            <span class="ntf-dot ntf-dot-success"></span>
            <div class="ntf-body">
              <div class="ntf-head">
                <span class="ntf-title">已将 3 个项目加入「重点追踪」</span>
                <span class="ntf-tag">收藏同步</span>
              </div>
              <p class="ntf-text">来自发现队列：Nova Protocol、Tempo、Stable 已加入收藏，并默认进入每日简报。</p>
              <div class="ntf-meta">
                <span>触发源 · collections</span>
              </div>
            </div>
            <div class="ntf-side-actions">
              <span class="ntf-time">2 天前</span>
              <button type="button" class="ntf-link">查看收藏</button>
            </div>
          </div>
        </section>
      </div>`;

const notifActions = `
        <button type="button" class="disc-btn disc-btn-secondary">
          <i data-lucide="check-check"></i>
          <span>全部已读</span>
        </button>
        <button type="button" class="disc-btn disc-btn-primary">
          <i data-lucide="settings"></i>
          <span>通知设置</span>
        </button>`;

// ============================================================
// Archive page
// ============================================================
const archCSS = `
  /* ===== page-archive ===== */
  .arc-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 16px;
  }
  .arc-stat {
    padding: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    display: flex; flex-direction: column; gap: 6px;
  }
  .arc-stat-k { font-size: 12px; color: var(--muted-foreground); }
  .arc-stat-v {
    font-family: var(--font-mono);
    font-size: 22px; font-weight: 600; line-height: 1;
    color: var(--foreground);
    font-variant-numeric: tabular-nums;
  }
  .arc-stat-s { font-size: 12px; color: var(--muted-foreground); }

  .arc-policy {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
    margin-bottom: 16px;
  }
  .arc-policy-card {
    padding: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    display: flex; flex-direction: column; gap: 10px;
  }
  .arc-policy-head {
    display: flex; align-items: center; justify-content: space-between; gap: 8px;
  }
  .arc-policy-name { font-size: 13.5px; font-weight: 600; color: var(--foreground); }
  .arc-policy-body { display: flex; flex-direction: column; gap: 6px; }
  .arc-policy-row { display: flex; justify-content: space-between; font-size: 12.5px; }
  .arc-policy-k { color: var(--muted-foreground); }
  .arc-policy-v { color: var(--foreground); font-variant-numeric: tabular-nums; }
  .arc-policy-foot { display: flex; align-items: center; justify-content: space-between; margin-top: auto; }
  .arc-policy-link {
    font-size: 12.5px; color: var(--primary); text-decoration: none;
  }
  .arc-policy-link:hover { text-decoration: underline; }

  .arc-table-card {
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }
  .arc-table-head {
    display: flex; align-items: center; justify-content: space-between;
    padding: 14px 16px;
    border-bottom: 1px solid var(--border);
  }
  .arc-table-title { font-size: 14px; font-weight: 600; color: var(--foreground); }
  .arc-table-actions { display: flex; gap: 8px; }
  .arc-table {
    width: 100%;
    border-collapse: collapse;
  }
  .arc-table thead th {
    padding: 10px 14px;
    font-size: 12px; font-weight: 500; text-align: left;
    color: var(--muted-foreground);
    background: var(--card);
    border-bottom: 1px solid var(--border);
  }
  .arc-table tbody td {
    height: 52px;
    padding: 10px 14px;
    font-size: 13px;
    color: var(--foreground);
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }
  .arc-table tbody tr:last-child td { border-bottom: 0; }
  .arc-table tbody tr:hover { background: var(--muted); }
  .arc-id { font-family: var(--font-mono); font-size: 12px; color: var(--muted-foreground); }
  .arc-name { font-size: 13.5px; font-weight: 500; line-height: 1.3; }
  .arc-scope { font-size: 12px; color: var(--muted-foreground); margin-top: 2px; }
  .arc-pill {
    display: inline-flex; align-items: center; gap: 6px; height: 22px;
    padding: 0 8px;
    border-radius: var(--radius-full);
    font-size: 11.5px;
    border: 1px solid var(--border);
    background: var(--muted);
    color: var(--muted-foreground);
  }
  .arc-pill[data-tone="ok"]    { background: var(--state-success-subtle, var(--alpha-brand-subtle)); color: var(--state-success); border-color: transparent; }
  .arc-pill[data-tone="info"]  { background: var(--state-info-subtle, var(--alpha-brand-subtle));    color: var(--state-info);    border-color: transparent; }
  .arc-pill[data-tone="warn"]  { background: var(--state-warning-subtle, var(--alpha-brand-subtle)); color: var(--state-warning); border-color: transparent; }
  .arc-size { font-family: var(--font-mono); font-size: 12.5px; font-variant-numeric: tabular-nums; }
  .arc-text-btn {
    border: 0; background: transparent; padding: 4px 6px;
    color: var(--primary); font-size: 12.5px; cursor: pointer;
    border-radius: var(--radius-sm);
  }
  .arc-text-btn:hover { text-decoration: underline; }
  .arc-text-btn:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }

  @media (max-width: 1279px) {
    .arc-stats { grid-template-columns: repeat(2, 1fr); }
    .arc-policy { grid-template-columns: 1fr; }
  }
`;

const archContent = `
      <!-- 1. 归档概览 -->
      <section class="arc-stats" aria-label="归档概览">
        <div class="arc-stat">
          <span class="arc-stat-k">本月已归档</span>
          <span class="arc-stat-v">4,821</span>
          <span class="arc-stat-s">raw_projects + signals</span>
        </div>
        <div class="arc-stat">
          <span class="arc-stat-k">归档体积</span>
          <span class="arc-stat-v">38.6 GB</span>
          <span class="arc-stat-s">较上月 +12%</span>
        </div>
        <div class="arc-stat">
          <span class="arc-stat-k">保留策略</span>
          <span class="arc-stat-v">90 天</span>
          <span class="arc-stat-s">原始数据默认</span>
        </div>
        <div class="arc-stat">
          <span class="arc-stat-k">待清理任务</span>
          <span class="arc-stat-v" style="color: var(--state-warning);">2</span>
          <span class="arc-stat-s">待人工确认</span>
        </div>
      </section>

      <!-- 2. 归档策略 -->
      <section class="arc-policy" aria-label="归档策略">
        <div class="arc-policy-card">
          <div class="arc-policy-head">
            <span class="arc-policy-name">原始项目快照</span>
            <span class="ops-toggle" data-on="true" role="switch" aria-checked="true" aria-label="启用原始项目快照归档"></span>
          </div>
          <div class="arc-policy-body">
            <div class="arc-policy-row"><span class="arc-policy-k">数据源</span><span class="arc-policy-v">raw_projects</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">保留</span><span class="arc-policy-v">90 天</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">归档目的地</span><span class="arc-policy-v">archive/raw_projects</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">上次执行</span><span class="arc-policy-v">今天 03:00</span></div>
          </div>
          <div class="arc-policy-foot">
            <span class="arc-policy-k">命中率 99.2%</span>
            <a href="#" class="arc-policy-link">编辑策略</a>
          </div>
        </div>

        <div class="arc-policy-card">
          <div class="arc-policy-head">
            <span class="arc-policy-name">信号与指标</span>
            <span class="ops-toggle" data-on="true" role="switch" aria-checked="true" aria-label="启用信号与指标归档"></span>
          </div>
          <div class="arc-policy-body">
            <div class="arc-policy-row"><span class="arc-policy-k">数据源</span><span class="arc-policy-v">project_signals</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">保留</span><span class="arc-policy-v">180 天</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">归档目的地</span><span class="arc-policy-v">archive/signals</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">上次执行</span><span class="arc-policy-v">今天 03:00</span></div>
          </div>
          <div class="arc-policy-foot">
            <span class="arc-policy-k">命中率 100%</span>
            <a href="#" class="arc-policy-link">编辑策略</a>
          </div>
        </div>

        <div class="arc-policy-card">
          <div class="arc-policy-head">
            <span class="arc-policy-name">采集日志</span>
            <span class="ops-toggle" data-on="false" role="switch" aria-checked="false" aria-label="启用采集日志归档"></span>
          </div>
          <div class="arc-policy-body">
            <div class="arc-policy-row"><span class="arc-policy-k">数据源</span><span class="arc-policy-v">collection_logs</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">保留</span><span class="arc-policy-v">30 天</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">归档目的地</span><span class="arc-policy-v">archive/logs</span></div>
            <div class="arc-policy-row"><span class="arc-policy-k">上次执行</span><span class="arc-policy-v">从未运行</span></div>
          </div>
          <div class="arc-policy-foot">
            <span class="arc-policy-k">未启用</span>
            <a href="#" class="arc-policy-link">编辑策略</a>
          </div>
        </div>
      </section>

      <!-- 3. 归档记录 -->
      <section class="arc-table-card" aria-label="归档记录">
        <div class="arc-table-head">
          <div class="arc-table-title alpha-heading">归档记录</div>
          <div class="arc-table-actions">
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
              <i data-lucide="download"></i>
              <span>导出清单</span>
            </button>
            <button type="button" class="disc-btn disc-btn-primary disc-btn-sm">
              <i data-lucide="play"></i>
              <span>立即归档</span>
            </button>
          </div>
        </div>
        <table class="arc-table">
          <thead>
            <tr>
              <th>归档任务</th>
              <th>范围</th>
              <th>状态</th>
              <th>记录数</th>
              <th>大小</th>
              <th>开始时间</th>
              <th>耗时</th>
              <th>操作</th>
            </tr>
          </thead>
          <tbody>
            <tr>
              <td>
                <div class="arc-name">arc-20250811-raw</div>
                <div class="arc-id">#4821</div>
              </td>
              <td>
                <div class="arc-scope">raw_projects · 90 天前</div>
              </td>
              <td><span class="arc-pill" data-tone="ok">已完成</span></td>
              <td>2,314</td>
              <td class="arc-size">6.2 GB</td>
              <td>2025-08-11 03:00</td>
              <td>4 分 12 秒</td>
              <td><button type="button" class="arc-text-btn">下载</button></td>
            </tr>
            <tr>
              <td>
                <div class="arc-name">arc-20250811-signals</div>
                <div class="arc-id">#4822</div>
              </td>
              <td>
                <div class="arc-scope">project_signals · 180 天前</div>
              </td>
              <td><span class="arc-pill" data-tone="ok">已完成</span></td>
              <td>1,812</td>
              <td class="arc-size">3.8 GB</td>
              <td>2025-08-11 03:04</td>
              <td>2 分 40 秒</td>
              <td><button type="button" class="arc-text-btn">下载</button></td>
            </tr>
            <tr>
              <td>
                <div class="arc-name">arc-20250810-raw</div>
                <div class="arc-id">#4819</div>
              </td>
              <td>
                <div class="arc-scope">raw_projects · 90 天前</div>
              </td>
              <td><span class="arc-pill" data-tone="info">进行中</span></td>
              <td>—</td>
              <td class="arc-size">—</td>
              <td>2025-08-10 03:00</td>
              <td>—</td>
              <td><button type="button" class="arc-text-btn">查看日志</button></td>
            </tr>
            <tr>
              <td>
                <div class="arc-name">arc-20250809-logs</div>
                <div class="arc-id">#4817</div>
              </td>
              <td>
                <div class="arc-scope">collection_logs · 30 天前</div>
              </td>
              <td><span class="arc-pill" data-tone="warn">部分成功</span></td>
              <td>438</td>
              <td class="arc-size">812 MB</td>
              <td>2025-08-09 03:00</td>
              <td>1 分 03 秒</td>
              <td><button type="button" class="arc-text-btn">重试</button></td>
            </tr>
          </tbody>
        </table>
      </section>`;

const archActions = `
        <button type="button" class="disc-btn disc-btn-secondary">
          <i data-lucide="download"></i>
          <span>导出清单</span>
        </button>
        <button type="button" class="disc-btn disc-btn-primary">
          <i data-lucide="play"></i>
          <span>立即归档</span>
        </button>`;

// ============================================================
// Build each page
// ============================================================
function build(shellPath, outName, opts) {
  let s = fs.readFileSync(shellPath, "utf8");
  s = setTitle(s, opts.title);
  s = swapSlot(s, "pageTitle", `<h1 class="app-page-title alpha-heading">${opts.title}</h1>`);
  s = swapSlot(s, "pageSubtitle", `<p class="app-page-subtitle">${opts.subtitle}</p>`);
  s = swapSlot(s, "pageActions", opts.actions);
  s = swapSlot(s, "content", opts.content);
  s = clearCollectionsActive(s);
  s = addNavItem(s, { key: opts.navKey, label: opts.navLabel, icon: opts.navIcon, self: true });
  s = injectCss(s, opts.css, opts.cssMarker);
  fs.writeFileSync(path.join(PAGES, outName), s, "utf8");
  return fs.statSync(path.join(PAGES, outName)).size;
}

const results = [];

results.push(["notifications.html", build(LIGHT_SHELL, "notifications.html", {
  title: "通知中心",
  subtitle: "interactions · 评分 · 截止 · 采集器告警",
  actions: notifActions,
  content: notifContent,
  css: notifCSS,
  cssMarker: "page-notifications",
  navKey: "notifications",
  navLabel: "通知中心",
  navIcon: "bell",
})]);

results.push(["notifications-dark.html", build(DARK_SHELL, "notifications-dark.html", {
  title: "通知中心 — 暗色",
  subtitle: "interactions · 评分 · 截止 · 采集器告警",
  actions: notifActions,
  content: notifContent,
  css: notifCSS,
  cssMarker: "page-notifications",
  navKey: "notifications",
  navLabel: "通知中心",
  navIcon: "bell",
})]);

results.push(["archive.html", build(LIGHT_SHELL, "archive.html", {
  title: "归档历史",
  subtitle: "raw_projects · signals · 保留策略 · 执行记录",
  actions: archActions,
  content: archContent,
  css: archCSS,
  cssMarker: "page-archive",
  navKey: "archive",
  navLabel: "归档历史",
  navIcon: "archive",
})]);

results.push(["archive-dark.html", build(DARK_SHELL, "archive-dark.html", {
  title: "归档历史 — 暗色",
  subtitle: "raw_projects · signals · 保留策略 · 执行记录",
  actions: archActions,
  content: archContent,
  css: archCSS,
  cssMarker: "page-archive",
  navKey: "archive",
  navLabel: "归档历史",
  navIcon: "archive",
})]);

console.log(JSON.stringify(results.map(([f, b]) => ({ f, bytes: b })), null, 2));
