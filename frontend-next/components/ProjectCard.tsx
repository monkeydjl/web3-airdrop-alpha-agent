'use client';

import Link from 'next/link';
import { Star } from 'lucide-react';
import { useCallback, useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';
import type { Project } from '@/lib/types';
import { ConfidenceBar, LabelBadge, ScoreRing } from './ui';
import { formatPct, reasonTone, reasonZh, sourceZh, stageZh, tierZh } from '@/lib/format';
import { ScriptForgeModal } from './ScriptForgeModal';
import { SecuritySentinelModal } from './SecuritySentinelModal';

export function ProjectCard({
  project,
  rank,
  onUpdate,
}: {
  project: Project;
  rank?: number;
  onUpdate?: (updated: { id: string; label: 'FARM' | 'WATCH' | 'IGNORE'; veto: string | null; reason?: string[] }) => void;
}) {
  const [currentLabel, setCurrentLabel] = useState(project.label);
  const [currentVeto, setCurrentVeto] = useState(project.veto);
  const [currentReason, setCurrentReason] = useState(project.reason);
  const [verdict, setVerdict] = useState<'FARM' | 'WATCH' | null>(null);
  const [sending, setSending] = useState(false);
  const [verifyErr, setVerifyErr] = useState('');
  const [isWatchlisted, setIsWatchlisted] = useState(Boolean(project.watchlisted));
  const [watchlistBusy, setWatchlistBusy] = useState(false);
  const [showScriptModal, setShowScriptModal] = useState(false);
  const [showSecurityModal, setShowSecurityModal] = useState(false);

  useEffect(() => {
    setCurrentLabel(project.label);
    setCurrentVeto(project.veto);
    setCurrentReason(project.reason);
    setIsWatchlisted(Boolean(project.watchlisted));
  }, [project.label, project.veto, project.reason, project.watchlisted]);

  const toggleWatchlist = async (e: React.MouseEvent) => {
    e.preventDefault();
    e.stopPropagation();
    if (watchlistBusy) return;
    setWatchlistBusy(true);
    const nextState = !isWatchlisted;
    setIsWatchlisted(nextState);
    try {
      if (nextState) {
        await apiFetch(`/watchlist/${encodeURIComponent(project.id)}`, {
          method: 'POST',
          body: JSON.stringify({ note: '' }),
        });
      } else {
        await apiFetch(`/watchlist/${encodeURIComponent(project.id)}`, {
          method: 'DELETE',
        });
      }
    } catch {
      setIsWatchlisted(!nextState);
    } finally {
      setWatchlistBusy(false);
    }
  };

  const needsVerify = currentVeto === 'no_participation_path';

  // 人工核验 → 反馈样本。校准门禁只认 wrong_label + note(正确标签)两类
  // 样本（见 calibration.extract_samples），按钮直接产出这种样本。
  // 「没路径」记 WATCH：系统原本就给了 WATCH，核验与它一致 —— 这也是有效样本
  // （agreement），不是只有分歧才算数。
  const mark = useCallback(
    async (v: 'FARM' | 'WATCH') => {
      if (sending) return;
      setSending(true);
      setVerifyErr('');
      try {
        await apiFetch('/feedback', {
          method: 'POST',
          body: JSON.stringify({ project_id: project.id, signal: 'wrong_label', note: v }),
        });
        setVerdict(v);
        if (v === 'FARM') {
          const newReason = [
            '人工核验确认：已发现参与路径，升为重点参与',
            ...(currentReason || []).filter(
              (r) => !r.includes('no verified participation path') && !r.includes('人工核验确认'),
            ),
          ];
          setCurrentLabel('FARM');
          setCurrentVeto(null);
          setCurrentReason(newReason);
          onUpdate?.({ id: project.id, label: 'FARM', veto: null, reason: newReason });
        } else {
          const newReason = [
            '人工核验确认：目前无明确参与路径，维持观察',
            ...(currentReason || []).filter(
              (r) => !r.includes('no verified participation path') && !r.includes('人工核验确认'),
            ),
          ];
          setCurrentLabel('WATCH');
          setCurrentVeto('verified_no_path');
          setCurrentReason(newReason);
          onUpdate?.({ id: project.id, label: 'WATCH', veto: 'verified_no_path', reason: newReason });
        }
      } catch (e) {
        setVerifyErr(e instanceof Error ? e.message : '提交失败');
      } finally {
        setSending(false);
      }
    },
    [project.id, sending, currentReason, onUpdate],
  );

  return (
    <div className="card-hover group relative overflow-hidden rounded-2xl p-4 sm:p-5 border transition-all duration-200 animate-fade-in">
      <Link href={`/project/${project.id}`} className="block">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1">
            <div className="mb-2 flex flex-wrap items-center gap-1.5">
              {rank != null ? (
                <span className="font-mono text-[10px] font-bold px-1.5 py-0.5 rounded bg-surface-2 text-ink-faint border border-line">
                  #{rank.toString().padStart(2, '0')}
                </span>
              ) : null}
              <LabelBadge label={currentLabel} />
              {project.stage ? (
                <span className="badge bg-surface-2 text-ink-muted border border-line font-mono text-[10px]">
                  {stageZh(project.stage)}
                </span>
              ) : null}
              {project.funding?.funding_tier && project.funding.funding_tier !== 'none' ? (
                <span className="badge bg-farm-soft/80 text-farm border border-farm/30 text-[10px] font-medium">
                  💰 {tierZh(project.funding.funding_tier)}
                </span>
              ) : null}
              {currentVeto === 'no_participation_path' ? (
                <span
                  className="badge bg-watch-soft/90 text-watch border border-watch/40 text-[10px] font-semibold"
                  title="分数已达 FARM 线，但未发现测试网/积分/任务入口 —— 需要你到官网或 Twitter 人工验证一次"
                >
                  待验证路径
                </span>
              ) : currentVeto === 'verified_no_path' ? (
                <span
                  className="badge bg-surface-2 text-ink-muted border border-line text-[10px]"
                  title="已人工核验确认：目前无明确参与路径，维持观察"
                >
                  已核验观察
                </span>
              ) : null}
              {project.persona_applied && project.persona_applied !== 'balanced' ? (
                <span
                  className="badge bg-brand-500/20 text-brand-300 border border-brand-500/40 text-[10px] font-semibold flex items-center gap-1"
                  title={project.persona_boost_reason || `角色自适应加权: ${project.persona_applied}`}
                >
                  <span>
                    {project.persona_applied === 'zero_cost' ? '🎒 零成本适配' :
                     project.persona_applied === 'whale_restaking' ? '💎 巨鲸优选' :
                     project.persona_applied === 'high_beta' ? '⚡ 叙事爆发' : '🎯 角色适配'}
                  </span>
                  {project.base_score != null && project.score !== project.base_score ? (
                    <span className="font-mono text-[9px] opacity-80">
                      ({project.score > project.base_score ? `+${project.score - project.base_score}` : project.score - project.base_score})
                    </span>
                  ) : null}
                </span>
              ) : null}
              {project.signals?.has_testnet && !project.signals?.has_points_program ? (
                <span
                  className="badge bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-[10px] font-medium"
                  title="纯测试网/零成本交互：无需质押真实本金，保本优先"
                >
                  零资金成本
                </span>
              ) : null}
              {project.reason?.includes('PUA_FATIGUE_WARNING') ? (
                <span
                  className="badge bg-amber-500/20 text-amber-400 border border-amber-500/40 text-[10px] font-semibold"
                  title="PUA疲劳度过高：多季积分稀释、长周期或代币不透明，建议降低投入预期"
                >
                  PUA预警
                </span>
              ) : null}
              {project.reason?.includes('EXIT_RECOMMENDED') ? (
                <span
                  className="badge bg-red-500/20 text-red-400 border border-red-500/40 text-[10px] font-semibold animate-pulse"
                  title="触发撤退预警：流动性流失、开发停摆或官网离线，建议及时止损撤退"
                >
                  建议撤退
                </span>
              ) : null}
              {project.reason?.includes('LOW_RUNWAY_RISK') ? (
                <span
                  className="badge bg-rose-500/20 text-rose-400 border border-rose-500/40 text-[10px] font-semibold"
                  title="存活率预警：项目融资微薄、跑道耗尽或缺乏机构背书，面临极高停服或归零风险"
                >
                  存活预警
                </span>
              ) : null}
              {project.signals?.site_alive === false ? (
                <span
                  className="badge bg-red-500/15 text-red-400 border border-red-500/30 text-[10px]"
                  title="官网连接失败（探测记录里有）—— 这个项目可能已经停服，介入前先看看"
                >
                  官网不可达
                </span>
              ) : null}
              {project.signal_consensus?.consensus_tier === 'high' ? (
                <span
                  className="badge bg-purple-500/20 text-purple-300 border border-purple-500/40 text-[10px] font-semibold"
                  title={`多源高度共识：由 ${project.signal_consensus.sources?.join('、')} 等 ${project.signal_consensus.source_count} 个独立公开源共同验证`}
                >
                  🎯 {project.signal_consensus.source_count}源共识
                </span>
              ) : project.signal_consensus?.consensus_tier === 'medium' ? (
                <span
                  className="badge bg-indigo-500/20 text-indigo-300 border border-indigo-500/40 text-[10px] font-medium"
                  title={`双源交叉印证：由 ${project.signal_consensus.sources?.join(' 与 ')} 共同验证`}
                >
                  🔗 双源印证
                </span>
              ) : null}
              {project.skipped ? (
                <span
                  className="badge bg-surface-3 text-ink-faint line-through border border-line text-[10px]"
                  title="你已标记「不参与」—— 工作台默认隐藏这类项目，详情页可恢复"
                >
                  不参与
                </span>
              ) : null}
            </div>
            <h3 className="truncate text-base font-bold tracking-tight text-ink group-hover:text-farm transition-colors">
              {project.name}
            </h3>
            <p className="mt-1 truncate text-xs text-ink-muted flex items-center gap-1.5">
              <span>{project.sector || '未知赛道'}</span>
              {project.source ? <span className="text-ink-faint">· {sourceZh(project.source)}</span> : ''}
            </p>
          </div>
          <div className="flex flex-col items-end gap-1 shrink-0">
            <button
              type="button"
              onClick={toggleWatchlist}
              disabled={watchlistBusy}
              className={`p-1 -mr-1 -mt-1 rounded-md transition-colors ${
                isWatchlisted
                  ? 'text-amber-400 hover:text-amber-300'
                  : 'text-ink-faint hover:text-amber-400 opacity-60 hover:opacity-100'
              }`}
              title={isWatchlisted ? '已在关注列表中，点击取消' : '点击加入关注列表'}
              aria-label={isWatchlisted ? '取消关注' : '加入关注'}
            >
              <Star className={`h-4 w-4 ${isWatchlisted ? 'fill-amber-400 text-amber-400' : ''}`} />
            </button>
            <ScoreRing score={project.score ?? 0} size={64} label={currentLabel} />
          </div>
        </div>

        <div className="mt-3.5">
          <ConfidenceBar value={project.confidence ?? 0} />
        </div>

        {currentReason?.length ? (
          <div className="mt-3 flex flex-wrap gap-1.5">
            {currentReason.slice(0, 2).map((r, i) => {
              const tone = reasonTone(r);
              const sign = tone === 'pos' ? '+' : tone === 'neg' ? '−' : tone === 'warn' ? '!' : '·';
              return (
                <span key={i} className="reason-chip">
                  <span className={`reason-sign reason-${tone}`}>{sign}</span>
                  <span className="truncate min-w-0">{reasonZh(r)}</span>
                </span>
              );
            })}
          </div>
        ) : (
          <p className="mt-3 text-xs text-ink-faint font-mono">置信度 {formatPct(project.confidence ?? 0)}</p>
        )}
      </Link>

      <div className="mt-2.5 flex items-center justify-between border-t border-line/60 pt-2 text-xs">
        <div className="flex items-center gap-1.5">
          <button
            type="button"
            onClick={() => setShowScriptModal(true)}
            className="px-2 py-0.5 text-[10px] font-medium text-ink-muted hover:text-ink bg-surface-2 hover:bg-surface-3 rounded border border-line transition flex items-center gap-1"
            title="生成 Foundry Cast / Web3.py / Viem 交互脚本模板"
          >
            <span>⚡</span>
            <span>脚本工坊</span>
          </button>
          <button
            type="button"
            onClick={() => setShowSecurityModal(true)}
            className="px-2 py-0.5 text-[10px] font-medium text-ink-muted hover:text-ink bg-surface-2 hover:bg-surface-3 rounded border border-line transition flex items-center gap-1"
            title="检测代币无限授权与钓鱼网址安全体检"
          >
            <span>🛡️</span>
            <span>安全体检</span>
          </button>
        </div>
      </div>

      {needsVerify || verdict ? (
        <div className="mt-2.5 border-t border-line/70 pt-2.5">
          {verdict ? (
            <p className="text-xs font-mono font-medium text-farm flex items-center gap-1" role="status">
              <span>✓</span>
              <span>
                {verdict === 'FARM'
                  ? '已核验：已升级为 FARM · 状态已落盘持久化'
                  : '已核验：维持观察 · 已消除待验证状态'}
              </span>
            </p>
          ) : (
            <div className="flex flex-wrap items-center gap-2">
              <span className="text-[11px] font-mono text-ink-faint">人工核验：</span>
              <button
                type="button"
                disabled={sending}
                onClick={() => void mark('FARM')}
                className="px-2.5 py-1 text-[11px] font-semibold rounded-md bg-farm/15 hover:bg-farm/25 text-farm border border-farm/40 transition"
                title="已确认有测试网/积分/任务入口 —— 升级为重点参与 FARM"
              >
                有路径 → 升 FARM
              </button>
              <button
                type="button"
                disabled={sending}
                onClick={() => void mark('WATCH')}
                className="btn-secondary !min-h-0 px-2 py-1 text-[11px]"
                title="确实没有参与入口 —— 系统维持观察"
              >
                维持观察
              </button>
            </div>
          )}
          {verifyErr ? <p className="mt-1 text-[11px] text-watch">{verifyErr}</p> : null}
        </div>
      ) : null}

      {showScriptModal && (
        <ScriptForgeModal
          initialProjectName={project.name}
          onClose={() => setShowScriptModal(false)}
        />
      )}
      {showSecurityModal && (
        <SecuritySentinelModal
          initialUrl={project.url || ''}
          onClose={() => setShowSecurityModal(false)}
        />
      )}
    </div>
  );
}
