// Insert "定时跑批" section into ops.html and ops-dark.html.
// Section sits between 系统健康 (ops-health) and 运维提示条 (ops-notice).
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "pages");

const SECTION = `
      <!-- 定时跑批 · analysis_scheduler -->
      <section class="ops-card" aria-label="定时跑批" data-dom-id="ops-scheduler">
        <div class="alpha-card__header">
          <h2 class="alpha-heading" style="font-size:16px;">定时跑批</h2>
          <div class="alpha-card__actions">
            <button type="button" class="ops-btn ops-btn-ghost ops-btn-sm">
              <i data-lucide="history"></i>
              <span>运行历史</span>
            </button>
            <button type="button" class="ops-btn ops-btn-secondary ops-btn-sm">
              <i data-lucide="plus"></i>
              <span>新建任务</span>
            </button>
          </div>
        </div>
        <div class="alpha-card__body">
          <table class="ops-table">
            <thead>
              <tr>
                <th>任务</th>
                <th>cron</th>
                <th>下次执行</th>
                <th>上次结果</th>
                <th>状态</th>
                <th>操作</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td>
                  <div class="ops-proj-name">每日机会评分</div>
                  <div class="ops-proj-key">job_daily_opportunity</div>
                </td>
                <td class="ops-mono">0 8 * * *</td>
                <td>今天 08:00</td>
                <td><span class="ops-state-ok">成功 · 182 条</span></td>
                <td><span class="ops-toggle" data-on="true" role="switch" aria-checked="true" aria-label="启用每日机会评分"></span></td>
                <td><button type="button" class="ops-text-btn">立即执行</button></td>
              </tr>
              <tr>
                <td>
                  <div class="ops-proj-name">发现队列巡检</div>
                  <div class="ops-proj-key">job_discovery_sweep</div>
                </td>
                <td class="ops-mono">*/30 * * * *</td>
                <td>12 分钟后</td>
                <td><span class="ops-state-ok">成功 · 24 条</span></td>
                <td><span class="ops-toggle" data-on="true" role="switch" aria-checked="true" aria-label="启用发现队列巡检"></span></td>
                <td><button type="button" class="ops-text-btn">立即执行</button></td>
              </tr>
              <tr>
                <td>
                  <div class="ops-proj-name">AI 简报生成</div>
                  <div class="ops-proj-key">job_ai_brief_daily</div>
                </td>
                <td class="ops-mono">30 7 * * *</td>
                <td>明天 07:30</td>
                <td><span class="ops-state-warn">超时 · 已重试</span></td>
                <td><span class="ops-toggle" data-on="true" role="switch" aria-checked="true" aria-label="启用 AI 简报生成"></span></td>
                <td><button type="button" class="ops-text-btn">立即执行</button></td>
              </tr>
              <tr>
                <td>
                  <div class="ops-proj-name">链上快照归档</div>
                  <div class="ops-proj-key">job_chain_archive</div>
                </td>
                <td class="ops-mono">0 3 * * 0</td>
                <td>周日 03:00</td>
                <td><span class="ops-state-muted">从未运行</span></td>
                <td><span class="ops-toggle" data-on="false" role="switch" aria-checked="false" aria-label="启用链上快照归档"></span></td>
                <td><button type="button" class="ops-text-btn">立即执行</button></td>
              </tr>
            </tbody>
          </table>
          <p class="ops-section-foot">由 analysis_scheduler 驱动 · 错过触发自动补跑 · 时区 Asia/Shanghai</p>
        </div>
      </section>`;

// CSS to append before last </style>
const CSS = `
  /* ---------- 定时跑批 section ---------- */
  .ops-table {
    width: 100%;
    border-collapse: collapse;
    table-layout: auto;
  }
  .ops-table thead th {
    padding: 10px 14px;
    font-size: 12px;
    font-weight: 500;
    text-align: left;
    color: var(--muted-foreground);
    background: var(--card);
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
  }
  .ops-table tbody td {
    height: 52px;
    padding: 10px 14px;
    font-size: 13px;
    color: var(--foreground);
    border-bottom: 1px solid var(--border);
    vertical-align: middle;
  }
  .ops-table tbody tr:last-child td { border-bottom: 0; }
  .ops-table tbody tr:hover { background: var(--muted); }
  .ops-proj-name { font-size: 13.5px; font-weight: 500; line-height: 1.3; }
  .ops-proj-key {
    margin-top: 2px;
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--muted-foreground);
  }
  .ops-mono { font-family: var(--font-mono); font-variant-numeric: tabular-nums; font-size: 12.5px; }
  .ops-state-ok { color: var(--state-success); font-size: 12.5px; }
  .ops-state-warn { color: var(--state-warning); font-size: 12.5px; }
  .ops-state-muted { color: var(--muted-foreground); font-size: 12.5px; }
  .ops-text-btn {
    border: 0;
    background: transparent;
    color: var(--primary);
    font-size: 12.5px;
    cursor: pointer;
    padding: 4px 6px;
    border-radius: var(--radius-sm);
  }
  .ops-text-btn:hover { text-decoration: underline; }
  .ops-text-btn:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; }
  .ops-toggle {
    display: inline-block;
    width: 32px;
    height: 18px;
    border-radius: var(--radius-full);
    background: var(--muted);
    position: relative;
    vertical-align: middle;
    cursor: pointer;
    transition: background-color 150ms var(--ease-default);
  }
  .ops-toggle::after {
    content: "";
    position: absolute;
    top: 2px;
    left: 2px;
    width: 14px;
    height: 14px;
    border-radius: var(--radius-full);
    background: var(--card);
    box-shadow: var(--shadow-sm);
    transition: transform 150ms var(--ease-default);
  }
  .ops-toggle[data-on="true"] { background: var(--primary); }
  .ops-toggle[data-on="true"]::after { transform: translateX(14px); }
  .ops-section-foot {
    margin: 12px 14px 4px;
    font-size: 12px;
    color: var(--muted-foreground);
  }
`;

const targets = ["ops.html", "ops-dark.html"];
const results = [];

for (const file of targets) {
  const p = path.join(ROOT, file);
  let s = fs.readFileSync(p, "utf8");
  const orig = s;

  // 1. inject CSS once
  if (!s.includes("定时跑批 section")) {
    const styleEnd = s.lastIndexOf("</style>");
    if (styleEnd < 0) { results.push({ file, error: "no </style>" }); continue; }
    s = s.slice(0, styleEnd) + CSS + "\n" + s.slice(styleEnd);
  }

  // 2. insert section between 系统健康 close and 运维提示条
  const anchor = `      <!-- 5. 运维提示条 -->`;
  if (!s.includes('aria-label="定时跑批"')) {
    if (!s.includes(anchor)) { results.push({ file, error: "anchor missing" }); continue; }
    s = s.replace(anchor, SECTION + "\n\n" + anchor);
  }

  // 3. renumber the notice comment from 5 to 6
  s = s.replace("<!-- 5. 运维提示条 -->", "<!-- 6. 运维提示条 -->");

  if (s !== orig) {
    fs.writeFileSync(p, s, "utf8");
    results.push({ file, changed: true, hasSection: s.includes('aria-label="定时跑批"') });
  } else {
    results.push({ file, changed: false });
  }
}

console.log(JSON.stringify(results, null, 2));
