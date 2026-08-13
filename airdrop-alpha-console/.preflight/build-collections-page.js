// Build collections.html from discoveries.html shell (light theme).
// - replaces pageTitle/pageSubtitle/pageActions/pageContent
// - keeps shared sidebar/topbar/footer/styles; adds col-* page-level CSS before </style>
// - new nav item '收藏关注' appended to nav list (data-nav-key="collections")
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "pages");
const SRC = path.join(ROOT, "discoveries.html");
const DST = path.join(ROOT, "collections.html");

let s = fs.readFileSync(SRC, "utf8");

// ----- 1. page-level CSS to inject (before final </style>) -----
const colCSS = `
  /* ===== page-collections · 收藏关注（分组 + 项目栅格） ===== */
  .col-stats {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 16px;
    margin-bottom: 16px;
  }
  .col-group-card {
    display: flex;
    flex-direction: column;
    gap: 10px;
    padding: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-sm);
  }
  .col-group-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
  }
  .col-group-name {
    display: inline-flex;
    align-items: center;
    gap: 8px;
    font-size: 13.5px;
    font-weight: 500;
    color: var(--foreground);
  }
  .col-group-dot { width: 8px; height: 8px; border-radius: var(--radius-full); }
  .col-group-count {
    font-family: var(--font-mono);
    font-variant-numeric: tabular-nums;
    font-size: 22px;
    font-weight: 600;
    color: var(--foreground);
    line-height: 1;
  }
  .col-group-foot { display: flex; align-items: center; justify-content: space-between; }
  .col-group-meta { font-size: 12px; color: var(--muted-foreground); }
  .col-group-link {
    font-size: 12.5px;
    color: var(--primary);
    text-decoration: none;
    white-space: nowrap;
  }
  .col-group-link:hover { text-decoration: underline; }
  .col-group-link:focus-visible { outline: 2px solid var(--ring); outline-offset: 2px; border-radius: var(--radius-sm); }

  .col-toolbar {
    display: flex;
    align-items: center;
    gap: 12px;
    padding: 12px 16px;
    margin-bottom: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
  }
  .col-toolbar-group { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .col-toolbar-label { font-size: 12px; color: var(--muted-foreground); }
  .col-chip {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    height: 28px;
    padding: 0 10px;
    border: 1px solid var(--border);
    border-radius: var(--radius-full);
    background: var(--card);
    color: var(--muted-foreground);
    font-size: 12.5px;
    cursor: pointer;
    transition: background-color 150ms var(--ease-default), color 150ms var(--ease-default), border-color 150ms var(--ease-default);
  }
  .col-chip[data-active="true"] {
    background: var(--alpha-brand-subtle);
    color: var(--primary);
    border-color: var(--alpha-brand-border);
  }
  .col-chip:hover { color: var(--foreground); }
  .col-chip-count {
    font-family: var(--font-mono);
    font-size: 11px;
    padding: 0 6px;
    border-radius: var(--radius-full);
    background: var(--muted);
    color: var(--muted-foreground);
    line-height: 16px;
  }
  .col-chip[data-active="true"] .col-chip-count { background: var(--alpha-brand-border); color: var(--primary); }
  .col-toolbar-search {
    margin-left: auto;
    display: flex;
    align-items: center;
    gap: 6px;
    height: 32px;
    padding: 0 10px;
    background: var(--card);
    border: 1px solid var(--input);
    border-radius: var(--radius-sm);
    color: var(--muted-foreground);
  }
  .col-toolbar-search input {
    border: 0; outline: 0; background: transparent; font: inherit; font-size: 12.5px; color: var(--foreground);
    width: 160px;
  }
  .col-toolbar-search input::placeholder { color: var(--muted-foreground); }

  .col-grid {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 16px;
  }
  .col-card {
    display: flex;
    flex-direction: column;
    gap: 12px;
    padding: 16px;
    background: var(--card);
    border: 1px solid var(--border);
    border-radius: var(--radius-lg);
    box-shadow: var(--shadow-sm);
    transition: box-shadow 200ms var(--ease-default), border-color 200ms var(--ease-default), transform 200ms var(--ease-default);
  }
  .col-card:hover {
    border-color: var(--alpha-brand-border);
    box-shadow: var(--shadow-md);
  }
  .col-card:focus-within { border-color: var(--ring); }
  .col-card-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
  .col-card-title-wrap { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .col-card-name { font-size: 14.5px; font-weight: 600; color: var(--foreground); line-height: 1.3; }
  .col-card-sub {
    font-family: var(--font-mono);
    font-size: 11.5px;
    color: var(--muted-foreground);
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
  }
  .col-card-fav {
    display: inline-flex; align-items: center; justify-content: center;
    width: 30px; height: 30px;
    border: 1px solid var(--border);
    border-radius: var(--radius-sm);
    background: var(--card);
    color: var(--muted-foreground);
    cursor: pointer;
    flex-shrink: 0;
    transition: color 150ms var(--ease-default), border-color 150ms var(--ease-default), background-color 150ms var(--ease-default);
  }
  .col-card-fav[data-on="true"] {
    color: var(--primary);
    background: var(--alpha-brand-subtle);
    border-color: var(--alpha-brand-border);
  }
  .col-card-fav:hover { color: var(--primary); border-color: var(--alpha-brand-border); }
  .col-card-fav [data-lucide] { width: 15px; height: 15px; }

  .col-card-labels { display: flex; flex-wrap: wrap; gap: 6px; }
  .col-label {
    display: inline-flex; align-items: center; height: 20px;
    padding: 0 8px;
    border: 1px solid var(--border);
    border-radius: var(--radius-full);
    background: var(--muted);
    color: var(--muted-foreground);
    font-size: 11.5px;
    white-space: nowrap;
  }
  .col-label-farm    { background: var(--label-farm-subtle);    color: var(--label-farm);    border-color: transparent; }
  .col-label-watch   { background: var(--label-watch-subtle);   color: var(--label-watch);   border-color: transparent; }
  .col-label-ignore  { background: var(--label-ignore-subtle);  color: var(--label-ignore);  border-color: transparent; }

  .col-card-note {
    font-size: 12.5px;
    line-height: 1.55;
    color: var(--muted-foreground);
    min-height: 38px;
  }

  .col-card-meta {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 8px 12px;
    padding-top: 4px;
    border-top: 1px dashed var(--border);
  }
  .col-meta-item { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .col-meta-k { font-size: 11px; color: var(--muted-foreground); }
  .col-meta-v { font-size: 12.5px; color: var(--foreground); font-variant-numeric: tabular-nums; }
  .col-meta-v[data-tone="ok"]    { color: var(--state-success); }
  .col-meta-v[data-tone="warn"]  { color: var(--state-warning); }
  .col-meta-v[data-tone="err"]   { color: var(--state-error); }
  .col-meta-v[data-tone="brand"] { color: var(--primary); }

  .col-card-actions { display: flex; align-items: center; gap: 12px; }
  .col-card-actions .disc-text-link { margin-left: auto; }

  @media (max-width: 1279px) {
    .col-stats { grid-template-columns: repeat(2, 1fr); }
    .col-grid { grid-template-columns: repeat(2, 1fr); }
  }
  @media (max-width: 959px) {
    .col-stats,
    .col-grid { grid-template-columns: 1fr; }
    .col-toolbar { flex-direction: column; align-items: stretch; }
    .col-toolbar-search { margin-left: 0; }
    .col-card-meta { grid-template-columns: 1fr; }
  }
`;

// ----- 2. content payload -----
const pageTitle = "收藏关注";
const pageSubtitle = "集合 · 关注 · 评分快照 · collections";
const pageActions = `
        <button type="button" class="disc-btn disc-btn-secondary">
          <i data-lucide="upload"></i>
          <span>导入清单</span>
        </button>
        <button type="button" class="disc-btn disc-btn-primary">
          <i data-lucide="plus"></i>
          <span>新建分组</span>
        </button>`;

const pageContent = `
      <!-- 1. 分组统计条 -->
      <section class="col-stats" aria-label="分组概览">
        <div class="col-group-card">
          <div class="col-group-head">
            <span class="col-group-name"><span class="col-group-dot" style="background: var(--label-farm);"></span>重点追踪</span>
            <span class="col-group-count">18</span>
          </div>
          <p class="col-group-meta">高分且近期有动作的项目集合</p>
          <div class="col-group-foot">
            <span class="col-group-meta">更新于 今天 09:12</span>
            <a href="#group-farm" class="col-group-link">查看项目</a>
          </div>
        </div>
        <div class="col-group-card">
          <div class="col-group-head">
            <span class="col-group-name"><span class="col-group-dot" style="background: var(--alpha-400);"></span>近期空投窗口</span>
            <span class="col-group-count">12</span>
          </div>
          <p class="col-group-meta">预计 30 天内主网 / TGE 的项目</p>
          <div class="col-group-foot">
            <span class="col-group-meta">更新于 昨天 18:40</span>
            <a href="#group-window" class="col-group-link">查看项目</a>
          </div>
        </div>
        <div class="col-group-card">
          <div class="col-group-head">
            <span class="col-group-name"><span class="col-group-dot" style="background: var(--state-info);"></span>融资观察</span>
            <span class="col-group-count">21</span>
          </div>
          <p class="col-group-meta">近 90 天内有新融资或领投方变化</p>
          <div class="col-group-foot">
            <span class="col-group-meta">更新于 2 天前</span>
            <a href="#group-funding" class="col-group-link">查看项目</a>
          </div>
        </div>
        <div class="col-group-card">
          <div class="col-group-head">
            <span class="col-group-name"><span class="col-group-dot" style="background: var(--state-warning);"></span>轻量任务</span>
            <span class="col-group-count">9</span>
          </div>
          <p class="col-group-meta">每日 5 分钟内可完成的签到/社交任务</p>
          <div class="col-group-foot">
            <span class="col-group-meta">更新于 3 天前</span>
            <a href="#group-quest" class="col-group-link">查看项目</a>
          </div>
        </div>
      </section>

      <!-- 2. 筛选工具行 -->
      <div class="col-toolbar" role="region" aria-label="收藏筛选">
        <div class="col-toolbar-group">
          <span class="col-toolbar-label">分组</span>
          <button type="button" class="col-chip" data-active="true">
            全部 <span class="col-chip-count">60</span>
          </button>
          <button type="button" class="col-chip">
            重点追踪 <span class="col-chip-count">18</span>
          </button>
          <button type="button" class="col-chip">
            近期空投窗口 <span class="col-chip-count">12</span>
          </button>
          <button type="button" class="col-chip">
            融资观察 <span class="col-chip-count">21</span>
          </button>
          <button type="button" class="col-chip">
            轻量任务 <span class="col-chip-count">9</span>
          </button>
        </div>
        <label class="col-toolbar-search">
          <i data-lucide="search"></i>
          <input type="search" placeholder="搜索项目 / 赛道 / 标签…" aria-label="搜索收藏">
        </label>
      </div>

      <!-- 3. 收藏项目栅格 -->
      <div class="col-grid" id="group-farm">

        <article class="col-card" data-dom-id="col-card-nova">
          <div class="col-card-head">
            <div class="col-card-title-wrap">
              <div class="col-card-name">Nova Protocol</div>
              <div class="col-card-sub">nova-protocol::DePIN</div>
            </div>
            <button type="button" class="col-card-fav" data-on="true" aria-label="取消收藏">
              <i data-lucide="star"></i>
            </button>
          </div>
          <div class="col-card-labels">
            <span class="col-label col-label-farm">FARM</span>
            <span class="col-label">DePIN</span>
            <span class="col-label">测试网激励</span>
          </div>
          <p class="col-card-note">官方确认 Q3 代币空投资格与节点绑定；评分决策引擎 v2.0 给出 0.88。</p>
          <div class="col-card-meta">
            <div class="col-meta-item">
              <span class="col-meta-k">大模型评分</span>
              <span class="col-meta-v" data-tone="ok">0.88</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">下一步</span>
              <span class="col-meta-v" data-tone="warn">推特互动</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">截止</span>
              <span class="col-meta-v">2025-08-30</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">收藏时间</span>
              <span class="col-meta-v">2025-06-12</span>
            </div>
          </div>
          <div class="col-card-actions">
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
              <i data-lucide="bell"></i>
              <span>开启提醒</span>
            </button>
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
              <i data-lucide="pencil"></i>
              <span>备注</span>
            </button>
            <a href="#" class="disc-text-link">查看项目</a>
          </div>
        </article>

        <article class="col-card" data-dom-id="col-card-poly">
          <div class="col-card-head">
            <div class="col-card-title-wrap">
              <div class="col-card-name">Poly Oracle</div>
              <div class="col-card-sub">poly-oracle::功能反馈</div>
            </div>
            <button type="button" class="col-card-fav" data-on="true" aria-label="取消收藏">
              <i data-lucide="star"></i>
            </button>
          </div>
          <div class="col-card-labels">
            <span class="col-label col-label-farm">FARM</span>
            <span class="col-label">预言机</span>
            <span class="col-label">任务平台</span>
          </div>
          <p class="col-card-note">参与 3 周；官方暗示快照临近，社区热度持续上升。</p>
          <div class="col-card-meta">
            <div class="col-meta-item">
              <span class="col-meta-k">大模型评分</span>
              <span class="col-meta-v" data-tone="ok">0.84</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">下一步</span>
              <span class="col-meta-v" data-tone="warn">Galxe 任务</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">截止</span>
              <span class="col-meta-v">2025-07-28</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">收藏时间</span>
              <span class="col-meta-v">2025-05-08</span>
            </div>
          </div>
          <div class="col-card-actions">
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
              <i data-lucide="bell"></i>
              <span>开启提醒</span>
            </button>
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
              <i data-lucide="pencil"></i>
              <span>备注</span>
            </button>
            <a href="#" class="disc-text-link">查看项目</a>
          </div>
        </article>

        <article class="col-card" data-dom-id="col-card-kite">
          <div class="col-card-head">
            <div class="col-card-title-wrap">
              <div class="col-card-name">Kite Network</div>
              <div class="col-card-sub">kite-network::DePIN</div>
            </div>
            <button type="button" class="col-card-fav" aria-label="加入收藏">
              <i data-lucide="star"></i>
            </button>
          </div>
          <div class="col-card-labels">
            <span class="col-label col-label-watch">WATCH</span>
            <span class="col-label">L2</span>
            <span class="col-label">测试网</span>
          </div>
          <p class="col-card-note">节点试运行稳定；等待官方激励细则释放。</p>
          <div class="col-card-meta">
            <div class="col-meta-item">
              <span class="col-meta-k">大模型评分</span>
              <span class="col-meta-v">0.62</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">下一步</span>
              <span class="col-meta-v">等激励细则</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">截止</span>
              <span class="col-meta-v">—</span>
            </div>
            <div class="col-meta-item">
              <span class="col-meta-k">收藏时间</span>
              <span class="col-meta-v">2025-07-02</span>
            </div>
          </div>
          <div class="col-card-actions">
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
              <i data-lucide="bell-off"></i>
              <span>关闭提醒</span>
            </button>
            <button type="button" class="disc-btn disc-btn-secondary disc-btn-sm">
              <i data-lucide="pencil"></i>
              <span>备注</span>
            </button>
            <a href="#" class="disc-text-link">查看项目</a>
          </div>
        </article>

      </div>

      <!-- 4. 底部操作提示 -->
      <div class="disc-quarantine-note" role="note">
        <span class="disc-note-icon"><i data-lucide="layers"></i></span>
        <div class="disc-note-body">
          <div class="disc-note-text">
            收藏与分组会自动同步到「发现队列」与「工作台」筛选；带 <strong>FARM</strong> 标签的项目默认进入每日简报。可在 <a href="#" class="disc-note-link">设置</a> 中关闭。
          </div>
        </div>
      </div>`;

// ----- 3. swap slots -----
function swapSlot(html, name, value) {
  const re = new RegExp(`(<!--\\s*SLOT:\\s*${name}\\s*-->)([\\s\\S]*?)(<!--\\s*/SLOT:\\s*${name}\\s*-->)`);
  const m = html.match(re);
  if (!m) return { html, hit: false };
  return { html: html.replace(re, `${m[1]}${value}${m[3]}`), hit: true };
}

let r = swapSlot(s, "pageTitle", `<h1 class="app-page-title alpha-heading">${pageTitle}</h1>`);
s = r.html;
r = swapSlot(s, "pageSubtitle", `<p class="app-page-subtitle">${pageSubtitle}</p>`);
s = r.html;
r = swapSlot(s, "pageActions", pageActions);
s = r.html;
r = swapSlot(s, "pageContent", pageContent);
s = r.html;

// ----- 4. document title -----
s = s.replace(/<title>[^<]+<\/title>/, `<title>${pageTitle}</title>`);

// ----- 5. append nav item (before </nav>) -----
const navAdd = `      <a href="#" class="app-nav-item" data-nav-key="collections" data-active="true">
        <i data-lucide="bookmark"></i>
        <span class="app-nav-label">收藏关注</span>
      </a>
    </nav>`;
s = s.replace(/<\/nav>/, navAdd);

// ----- 6. clear data-active from discoveries nav item (this page is collections) -----
s = s.replace(
  /<a href="#" class="app-nav-item" data-nav-key="discoveries" data-active="true">/,
  `<a href="#" class="app-nav-item" data-nav-key="discoveries" data-dom-id="nav-discoveries">`
);

// ----- 7. add data-dom-id to other nav items, matching conventions -----
// existing discoveries shell: nav-index/nav-insights/nav-portfolio/nav-ops already have data-dom-id.
// collections is the new self; keep it active without data-dom-id (per layout contract).

// ----- 8. inject page-level CSS before last </style> -----
const styleEnd = s.lastIndexOf("</style>");
if (styleEnd < 0) throw new Error("No </style> found in template");
s = s.slice(0, styleEnd) + colCSS + "\n" + s.slice(styleEnd);

fs.writeFileSync(DST, s, "utf8");

console.log(JSON.stringify({
  written: path.relative(path.join(__dirname, ".."), DST),
  bytes: fs.statSync(DST).size,
  navAdded: /data-nav-key="collections"/.test(s),
  cssInjected: s.includes("page-collections"),
  contentReplaced: s.includes("col-grid"),
  titleSet: s.includes("<title>收藏关注</title>"),
}, null, 2));
