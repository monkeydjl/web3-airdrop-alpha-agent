// Replace the content slot of collections.html / collections-dark.html with the real collections body.
const fs = require("fs");
const path = require("path");

const ROOT = path.join(__dirname, "..", "pages");

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

const targets = ["collections.html", "collections-dark.html"];
const out = [];
for (const f of targets) {
  const p = path.join(ROOT, f);
  let s = fs.readFileSync(p, "utf8");
  const start = s.indexOf("<!-- SLOT: content -->");
  const end = s.indexOf("<!-- /SLOT: content -->");
  if (start < 0 || end < 0 || end <= start) {
    out.push({ f, error: "slot markers missing" });
    continue;
  }
  const before = s.slice(0, start + "<!-- SLOT: content -->".length);
  const after = s.slice(end);
  s = before + pageContent + "\n      " + after;
  fs.writeFileSync(p, s, "utf8");
  out.push({ f, ok: true, hasCards: /data-dom-id="col-card-(nova|poly|kite)"/.test(s), bytes: fs.statSync(p).size });
}
console.log(JSON.stringify(out, null, 2));
