'use client';

import { useEffect, useState } from 'react';
import { apiFetch } from '@/lib/api';

interface PlaybookStep {
  step_no: number;
  action: string;
  title: string;
  target: string;
  contract: string;
  gas_usd: number;
  notes: string;
}

interface PlaybookTemplate {
  id: string;
  title: string;
  project: string;
  category: string;
  difficulty: string;
  estimated_total_gas_usd: number;
  estimated_duration_min: number;
  steps: PlaybookStep[];
}

interface PlaybookStudioModalProps {
  isOpen: boolean;
  onClose: () => void;
  initialPlaybookId?: string;
}

export default function PlaybookStudioModal({
  isOpen,
  onClose,
  initialPlaybookId,
}: PlaybookStudioModalProps) {
  const [templates, setTemplates] = useState<PlaybookTemplate[]>([]);
  const [selectedTemplate, setSelectedTemplate] = useState<PlaybookTemplate | null>(null);
  const [jitterMin, setJitterMin] = useState(30);
  const [jitterMax, setJitterMax] = useState(90);
  const [generatedCode, setGeneratedCode] = useState<string>('');
  const [loading, setLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<'pipeline' | 'code'>('pipeline');

  useEffect(() => {
    if (!isOpen) return;
    setLoading(true);
    apiFetch<{ data: { templates: PlaybookTemplate[] } }>('/playbook/templates')
      .then((res) => {
        if (res?.data?.templates) {
          const list = res.data.templates;
          setTemplates(list);
          const found = initialPlaybookId
            ? list.find((t) => t.id === initialPlaybookId) || list[0]
            : list[0];
          setSelectedTemplate(found);
          generateScript(found?.id, jitterMin, jitterMax);
        }
      })
      .catch((err) => console.error('Failed to load playbook templates', err))
      .finally(() => setLoading(false));
  }, [isOpen, initialPlaybookId]);

  const generateScript = async (pId?: string, jMin = jitterMin, jMax = jitterMax) => {
    if (!pId && !selectedTemplate?.id) return;
    try {
      const res = await apiFetch<{ data: { executable_code: string } }>(
        '/playbook/validate-and-generate',
        {
          method: 'POST',
          body: JSON.stringify({
            playbook_id: pId || selectedTemplate?.id,
            jitter_min: jMin,
            jitter_max: jMax,
          }),
        }
      );
      if (res?.data?.executable_code) {
        setGeneratedCode(res.data.executable_code);
      }
    } catch (e) {
      console.error('Failed to generate script', e);
    }
  };

  const handleSelect = (tpl: PlaybookTemplate) => {
    setSelectedTemplate(tpl);
    generateScript(tpl.id, jitterMin, jitterMax);
  };

  const copyCode = () => {
    navigator.clipboard.writeText(generatedCode);
    setCopied(true);
    setTimeout(() => setCopied(false), 2000);
  };

  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4 backdrop-blur-sm animate-fade-in">
      <div className="relative flex max-h-[92vh] w-full max-w-5xl flex-col rounded-2xl border border-line bg-surface p-6 shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center justify-between border-b border-line pb-4">
          <div className="flex items-center gap-2.5">
            <span className="text-2xl">🧩</span>
            <div>
              <h3 className="text-lg font-bold text-ink">自动化任务执行脚本沙箱与 Playbook 编排器</h3>
              <p className="text-xs text-ink-muted">
                可视化流水线步骤编排、端到端 Gas 预演，内嵌防女巫随机延迟 (Jitter) 的 Python Web3.py 脚本生成
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg p-1.5 text-ink-muted hover:bg-surface-2 hover:text-ink transition"
          >
            ✕
          </button>
        </div>

        {/* Content */}
        <div className="my-4 flex-1 overflow-y-auto pr-1 space-y-4">
          {loading ? (
            <div className="py-16 text-center text-sm text-ink-muted">加载预设 Playbook 库…</div>
          ) : (
            <>
              {/* Template Tabs */}
              <div className="flex flex-wrap gap-2">
                {templates.map((tpl) => {
                  const isCur = selectedTemplate?.id === tpl.id;
                  return (
                    <button
                      key={tpl.id}
                      type="button"
                      onClick={() => handleSelect(tpl)}
                      className={`px-3.5 py-1.5 rounded-lg text-xs font-semibold transition flex items-center gap-1.5 ${
                        isCur
                          ? 'bg-brand-500 text-white shadow-sm'
                          : 'bg-surface-2 text-ink-muted hover:bg-surface-3 hover:text-ink'
                      }`}
                    >
                      <span>{tpl.title}</span>
                      <span className="font-mono text-[10px] opacity-75">(${tpl.estimated_total_gas_usd})</span>
                    </button>
                  );
                })}
              </div>

              {selectedTemplate && (
                <div className="grid grid-cols-1 md:grid-cols-12 gap-4">
                  {/* Left: Pipeline Summary & Jitter Settings */}
                  <div className="md:col-span-4 space-y-3">
                    <div className="p-4 rounded-xl border border-line bg-surface-2/40 space-y-2.5">
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-ink-muted">赛道分类</span>
                        <span className="text-xs font-semibold text-ink">{selectedTemplate.category}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-ink-muted">操作复杂度</span>
                        <span className="text-xs font-semibold text-brand-400">{selectedTemplate.difficulty}</span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-ink-muted">预估总 Gas 损耗</span>
                        <span className="font-mono text-xs font-bold text-emerald-400">
                          ${selectedTemplate.estimated_total_gas_usd.toFixed(2)}
                        </span>
                      </div>
                      <div className="flex items-center justify-between">
                        <span className="text-xs text-ink-muted">预估执行耗时</span>
                        <span className="font-mono text-xs text-ink">
                          ~{selectedTemplate.estimated_duration_min} 分钟
                        </span>
                      </div>
                    </div>

                    {/* Anti-Sybil Jitter Box */}
                    <div className="p-4 rounded-xl border border-line bg-surface-2/40 space-y-2.5">
                      <div className="text-xs font-bold text-ink flex items-center gap-1">
                        <span>🛡️ 防女巫离散度延迟控制</span>
                      </div>
                      <p className="text-[11px] text-ink-muted">
                        步骤间插入随机休眠，彻底打散批处理交易时间指纹。
                      </p>
                      <div className="grid grid-cols-2 gap-2 pt-1">
                        <div>
                          <label className="text-[10px] text-ink-muted">最小等待 (秒)</label>
                          <input
                            type="number"
                            value={jitterMin}
                            min={5}
                            onChange={(e) => {
                              const v = Number(e.target.value);
                              setJitterMin(v);
                              generateScript(selectedTemplate.id, v, jitterMax);
                            }}
                            className="mt-1 w-full rounded border border-line bg-surface p-1.5 text-xs font-mono text-ink"
                          />
                        </div>
                        <div>
                          <label className="text-[10px] text-ink-muted">最大等待 (秒)</label>
                          <input
                            type="number"
                            value={jitterMax}
                            min={10}
                            onChange={(e) => {
                              const v = Number(e.target.value);
                              setJitterMax(v);
                              generateScript(selectedTemplate.id, jitterMin, v);
                            }}
                            className="mt-1 w-full rounded border border-line bg-surface p-1.5 text-xs font-mono text-ink"
                          />
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* Right: Step List & Code View */}
                  <div className="md:col-span-8 space-y-3">
                    <div className="flex items-center justify-between border-b border-line pb-2">
                      <div className="flex gap-2 text-xs">
                        <button
                          type="button"
                          onClick={() => setActiveTab('pipeline')}
                          className={`pb-1 px-1 font-semibold transition ${
                            activeTab === 'pipeline'
                              ? 'border-b-2 border-brand-500 text-brand-500'
                              : 'text-ink-muted hover:text-ink'
                          }`}
                        >
                          流水线步骤 ({selectedTemplate.steps.length})
                        </button>
                        <button
                          type="button"
                          onClick={() => setActiveTab('code')}
                          className={`pb-1 px-1 font-semibold transition ${
                            activeTab === 'code'
                              ? 'border-b-2 border-brand-500 text-brand-500'
                              : 'text-ink-muted hover:text-ink'
                          }`}
                        >
                          生成的 Python 脚本
                        </button>
                      </div>

                      {activeTab === 'code' && (
                        <button
                          type="button"
                          onClick={copyCode}
                          className="btn-secondary !py-0.5 !px-2.5 text-xs flex items-center gap-1 text-brand-400"
                        >
                          {copied ? '✓ 已复制全部代码' : '📋 复制脚本'}
                        </button>
                      )}
                    </div>

                    {activeTab === 'pipeline' ? (
                      <div className="space-y-2.5">
                        {selectedTemplate.steps.map((step) => (
                          <div
                            key={step.step_no}
                            className="flex items-start gap-3 p-3 rounded-xl border border-line bg-surface-2/30 hover:bg-surface-2/60 transition"
                          >
                            <span className="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-brand-500/20 text-brand-400 font-bold text-xs font-mono">
                              {step.step_no}
                            </span>
                            <div className="flex-1 min-w-0">
                              <div className="flex items-center justify-between">
                                <div className="font-semibold text-xs text-ink">{step.title}</div>
                                <span className="font-mono text-[10px] text-emerald-400">
                                  ${step.gas_usd.toFixed(2)} Gas
                                </span>
                              </div>
                              <div className="text-[11px] text-ink-muted mt-0.5">{step.notes}</div>
                              <div className="mt-1.5 flex items-center gap-2 text-[10px] font-mono text-ink-faint">
                                <span className="uppercase px-1 rounded bg-surface-3">{step.action}</span>
                                <span className="truncate">{step.contract}</span>
                              </div>
                            </div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-xl border border-line bg-neutral-950 p-3.5">
                        <pre className="text-xs font-mono text-neutral-300 overflow-x-auto max-h-[340px] leading-relaxed">
                          {generatedCode}
                        </pre>
                      </div>
                    )}
                  </div>
                </div>
              )}
            </>
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-line pt-3 flex items-center justify-between text-xs text-ink-muted">
          <span>安全守则：导出的执行脚本完全在本地运行，私钥绝对不要上传或保存在任何云端服务器中。</span>
          <button type="button" onClick={onClose} className="btn-secondary !py-1 !px-4">
            关闭
          </button>
        </div>
      </div>
    </div>
  );
}
