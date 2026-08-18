'use client';

import { TopBar } from '@/components/TopBar';
import Link from 'next/link';
import { useState } from 'react';
import { Plus, Star, Upload } from 'lucide-react';

type GroupKey = 'all' | 'farm' | 'window' | 'funding' | 'quest';

interface CollectionItem {
  id: string;
  name: string;
  sub: string;
  group: Exclude<GroupKey, 'all'>;
  score: number;
  nextStep: string;
  deadline: string;
  collectedAt: string;
  note: string;
  starred: boolean;
  labels: string[];
}

const COLLECTIONS: CollectionItem[] = [
  { id: 'nova-protocol', name: 'Nova Protocol', sub: 'nova-protocol::DePIN', group: 'farm', score: 0.88, nextStep: '推特互动', deadline: '2025-08-30', collectedAt: '2025-06-12', note: '官方确认 Q3 代币空投资格与节点绑定；评分决策引擎 v2.0 给出 0.88。', starred: true, labels: ['重点参与', 'DePIN'] },
  { id: 'poly-oracle', name: 'Poly Oracle', sub: 'poly-oracle::功能反馈', group: 'window', score: 0.84, nextStep: 'Galxe 任务', deadline: '2025-07-28', collectedAt: '2025-05-08', note: '参与 3 周；官方暗示快照临近，社区热度持续上升。', starred: true, labels: ['空投窗口', '预言机'] },
  { id: 'kite-network', name: 'Kite Network', sub: 'kite-network::DePIN', group: 'funding', score: 0.76, nextStep: '节点试运行', deadline: '2025-09-15', collectedAt: '2025-06-01', note: '节点试运行稳定；等待官方激励细则释放。', starred: false, labels: ['融资观察', 'DePIN'] },
  { id: 'aether-fi', name: 'Aether Fi', sub: 'aether-fi::Restaking', group: 'farm', score: 0.82, nextStep: '主网交互', deadline: '2025-08-20', collectedAt: '2025-05-22', note: 'Restaking 赛道头部项目；TVL 增速健康，融资背景强。', starred: true, labels: ['重点参与', 'Restaking'] },
  { id: 'quantum-pad', name: 'Quantum Pad', sub: 'quantum-pad::Launchpad', group: 'quest', score: 0.68, nextStep: '每日签到', deadline: '2025-08-10', collectedAt: '2025-07-01', note: '轻量任务平台；每日签到 5 分钟，积分可换空投。', starred: false, labels: ['轻量任务'] },
  { id: 'lumen-dex', name: 'Lumen DEX', sub: 'lumen-dex::DEX', group: 'window', score: 0.79, nextStep: '测试网交互', deadline: '2025-08-05', collectedAt: '2025-06-18', note: '测试网活跃度高；快照预计 8 月初，建议持续交互。', starred: true, labels: ['空投窗口', 'DEX'] },
  { id: 'vertex-lend', name: 'Vertex Lend', sub: 'vertex-lend::Lending', group: 'funding', score: 0.74, nextStep: '存款交互', deadline: '2025-09-30', collectedAt: '2025-06-10', note: '借贷协议新融资 500 万美元；主网上线后可存款积分。', starred: false, labels: ['融资观察', '借贷'] },
  { id: 'orbit-bridge', name: 'Orbit Bridge', sub: 'orbit-bridge::Bridge', group: 'farm', score: 0.85, nextStep: '跨链交互', deadline: '2025-08-25', collectedAt: '2025-05-15', note: '跨链桥头部项目；多链交互积分已确认，空投概率高。', starred: true, labels: ['重点参与', '跨链桥'] },
  { id: 'echo-social', name: 'Echo Social', sub: 'echo-social::SocialFi', group: 'quest', score: 0.65, nextStep: '社交任务', deadline: '2025-08-12', collectedAt: '2025-07-05', note: 'SocialFi 项目；每日发帖 + 点赞即可积分，轻量参与。', starred: false, labels: ['轻量任务', 'SocialFi'] },
];

interface GroupStat {
  key: Exclude<GroupKey, 'all'>;
  name: string;
  count: number;
  meta: string;
  updated: string;
  dot: string;
}

const GROUP_STATS: GroupStat[] = [
  { key: 'farm', name: '重点追踪', count: 18, meta: '高分且近期有动作的项目集合', updated: '今天 09:12', dot: 'rgb(var(--farm))' },
  { key: 'window', name: '近期空投窗口', count: 12, meta: '预计 30 天内主网 / TGE 的项目', updated: '昨天 18:40', dot: '#6f77e6' },
  { key: 'funding', name: '融资观察', count: 21, meta: '近 90 天内有新融资或领投方变化', updated: '2 天前', dot: '#4d56dd' },
  { key: 'quest', name: '轻量任务', count: 9, meta: '每日 5 分钟内可完成的签到/社交任务', updated: '3 天前', dot: 'rgb(var(--watch))' },
];

const CHIP_COUNTS: { key: GroupKey; label: string; count: number }[] = [
  { key: 'all', label: '全部', count: 60 },
  { key: 'farm', label: '重点追踪', count: 18 },
  { key: 'window', label: '近期空投窗口', count: 12 },
  { key: 'funding', label: '融资观察', count: 21 },
  { key: 'quest', label: '轻量任务', count: 9 },
];

export default function CollectionsPage() {
  const [group, setGroup] = useState<GroupKey>('all');
  const [search, setSearch] = useState('');
  const [stars, setStars] = useState<Record<string, boolean>>({});

  const isStarred = (item: CollectionItem) => stars[item.id] ?? item.starred;

  const toggleStar = (id: string) => {
    setStars((prev) => {
      const current = prev[id] ?? COLLECTIONS.find((c) => c.id === id)?.starred ?? false;
      return { ...prev, [id]: !current };
    });
  };

  const filtered = COLLECTIONS.filter((item) => {
    if (group !== 'all' && item.group !== group) return false;
    const q = search.trim().toLowerCase();
    if (!q) return true;
    return (
      item.name.toLowerCase().includes(q) ||
      item.sub.toLowerCase().includes(q) ||
      item.note.toLowerCase().includes(q)
    );
  });

  return (
    <>
      <TopBar title="收藏关注" subtitle="重点追踪 · 空投窗口 · 融资观察 · 轻量任务">
        <button type="button" className="btn-secondary inline-flex items-center gap-1.5">
          <Upload className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">导入清单</span>
        </button>
        <button type="button" className="btn-primary inline-flex items-center gap-1.5">
          <Plus className="h-4 w-4" strokeWidth={2} />
          <span className="hidden sm:inline">新建分组</span>
        </button>
      </TopBar>

      <div className="app-content space-y-4 animate-fade-in">
        {/* 分组概览卡片 */}
        <div className="col-stats">
          {GROUP_STATS.map((g) => (
            <div className="col-group-card" key={g.key}>
              <div className="col-group-head">
                <span className="col-group-name">
                  <span className="col-group-dot" style={{ background: g.dot }} />
                  {g.name}
                </span>
                <span className="col-group-count">{g.count}</span>
              </div>
              <p className="col-group-meta">{g.meta}</p>
              <div className="col-group-foot">
                <span className="col-group-meta">更新于 {g.updated}</span>
                <button
                  type="button"
                  className="col-group-link"
                  onClick={() => setGroup(g.key)}
                >
                  查看项目
                </button>
              </div>
            </div>
          ))}
        </div>

        {/* 筛选条 */}
        <div className="col-chips">
          {CHIP_COUNTS.map((c) => (
            <button
              key={c.key}
              className="col-chip"
              data-active={group === c.key}
              onClick={() => setGroup(c.key)}
            >
              {c.label} <span className="col-chip-count">{c.count}</span>
            </button>
          ))}
          <input
            type="search"
            placeholder="搜索收藏项目…"
            className="select ml-auto w-48"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* 收藏卡片网格 */}
        <div className="col-grid">
          {filtered.length === 0 ? (
            <div className="col-card col-span-full p-8 text-center text-sm text-ink-faint">
              无匹配的收藏项目
            </div>
          ) : (
            filtered.map((item) => {
              const starred = isStarred(item);
              return (
                <article className="col-card" key={item.id}>
                  <div className="col-card-head">
                    <div className="col-card-title-wrap">
                      <div className="col-card-name">{item.name}</div>
                      <div className="col-card-sub">{item.sub}</div>
                    </div>
                    <button
                      type="button"
                      className="col-card-fav"
                      data-on={starred}
                      aria-label={starred ? '取消收藏' : '加入收藏'}
                      onClick={() => toggleStar(item.id)}
                    >
                      <Star className="h-3.5 w-3.5" fill={starred ? 'currentColor' : 'none'} strokeWidth={2} />
                    </button>
                  </div>
                  <div className="col-card-labels">
                    {item.labels.map((l) => (
                      <span key={l} className="badge bg-surface-3 text-ink-muted">{l}</span>
                    ))}
                  </div>
                  <p className="col-card-note">{item.note}</p>
                  <div className="col-card-meta">
                    <div className="col-meta-item">
                      <span className="col-meta-k">大模型评分</span>
                      <span className="col-meta-v" style={{ color: 'rgb(var(--farm))' }}>{item.score.toFixed(2)}</span>
                    </div>
                    <div className="col-meta-item">
                      <span className="col-meta-k">下一步</span>
                      <span className="col-meta-v" style={{ color: 'rgb(var(--watch))' }}>{item.nextStep}</span>
                    </div>
                    <div className="col-meta-item">
                      <span className="col-meta-k">截止</span>
                      <span className="col-meta-v">{item.deadline}</span>
                    </div>
                    <div className="col-meta-item">
                      <span className="col-meta-k">收藏时间</span>
                      <span className="col-meta-v">{item.collectedAt}</span>
                    </div>
                  </div>
                  <div className="col-card-actions">
                    <Link href={`/project/${item.id}`} className="text-xs font-medium text-farm hover:underline">
                      查看详情 →
                    </Link>
                    <button type="button" className="text-xs text-ink-muted hover:text-ink ml-auto">
                      编辑备注
                    </button>
                  </div>
                </article>
              );
            })
          )}
        </div>
      </div>
    </>
  );
}
