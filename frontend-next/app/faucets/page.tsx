'use client';

import { FaucetTrackerPanel } from '@/components/FaucetTrackerPanel';
import { OnChainVerifierPanel } from '@/components/OnChainVerifierPanel';
import { ShieldCheck, Sparkles, Zap } from 'lucide-react';

export default function FaucetsPage() {
  return (
    <div className="app-content animate-fade-in">
      <div className="mx-auto max-w-[1440px] space-y-6">
        <header className="flex flex-col gap-1">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-bold tracking-tight text-ink">
              测试网水龙头与链上中心 (Faucet & On-Chain Hub)
            </h1>
            <span className="badge bg-emerald-500/15 text-emerald-400 border border-emerald-500/30 text-xs">
              0 本金 · 0 Gas · 0 商业 API
            </span>
          </div>
          <p className="text-xs text-ink-muted">
            全网主流免费测试网领水通道集合与免 Key 公共 RPC 存活性探测。保本零成本交互，从每日领水与链上检验开始。
          </p>
        </header>

        {/* 核心三准则 */}
        <div className="grid gap-3 sm:grid-cols-3">
          <div className="card p-3.5 flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-emerald-500/15 text-emerald-400">
              <ShieldCheck className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-ink">100% 真实免费</h3>
              <p className="text-[11px] text-ink-muted mt-0.5">
                精选无需付费订阅的公共水龙头，杜绝假领水网站与恶意钓鱼。
              </p>
            </div>
          </div>

          <div className="card p-3.5 flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-cyan-500/15 text-cyan-400">
              <Zap className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-ink">冷却倒计时</h3>
              <p className="text-[11px] text-ink-muted mt-0.5">
                打卡后自动开启 24h 冷却追踪，提醒各网络何时可以再次领取。
              </p>
            </div>
          </div>

          <div className="card p-3.5 flex items-start gap-3">
            <div className="flex h-7 w-7 shrink-0 items-center justify-center rounded-lg bg-purple-500/15 text-purple-400">
              <Sparkles className="h-4 w-4" />
            </div>
            <div>
              <h3 className="text-xs font-semibold text-ink">零资金成本</h3>
              <p className="text-[11px] text-ink-muted mt-0.5">
                测试币可直接用于生态交互、合约部署与测试网积分任务。
              </p>
            </div>
          </div>
        </div>

        {/* Faucet Tracker Panel */}
        <FaucetTrackerPanel />

        {/* On-Chain Contract Liveness Verifier */}
        <OnChainVerifierPanel
          title="免 Key 测试网链上存活性探测器 (On-Chain Contract Verifier)"
          subtitle="通过免费公共 RPC 节点一键检验 Sepolia / Arbitrum / Base / Polygon / Berachain 真实合约字节码与交互 Nonce"
        />
      </div>
    </div>
  );
}
