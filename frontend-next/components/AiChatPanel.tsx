'use client';

import { apiFetch } from '@/lib/api';
import { useCallback, useEffect, useRef, useState } from 'react';

/**
 * 项目详情页「AI 追问」：针对当前项目的多轮对话分析。
 *
 * 定位是「智能解读」（AiBriefPanel，一次性独白）的追问延伸 —— 用户追问
 * 「为什么是这个分」「参与的主要风险」这类静态面板答不了的问题。
 *
 * 会话历史由前端持有、随请求全量传给后端（服务端无状态），刷新即清空。
 * 只发送最近 HISTORY_LIMIT 条：成本随轮数线性涨，而更早的上下文对
 * 「针对当前项目追问」几乎没有增量（后端还会再兜底截断一次）。
 */

interface ChatMsg {
  role: 'user' | 'assistant';
  content: string;
}

interface AiChatData {
  project_id: string;
  project_name?: string;
  reply?: string | null;
  /** llm_disabled / budget_exceeded / llm_error；reply 非 null 时为 null */
  degraded_reason?: string | null;
  llm_available?: boolean;
}

const HISTORY_LIMIT = 12;
const MAX_INPUT_CHARS = 500;

const PRESET_QUESTIONS = [
  '为什么是这个评分？',
  '参与的主要风险是什么？',
  '怎么规划交互路径？',
  '融资情况说明什么？',
] as const;

/** 把降级原因翻成一句「该怎么办」，口径与后端 docs/API_SPEC.md §43a 对齐。 */
function degradedNotice(reason: string | null | undefined): string {
  switch (reason) {
    case 'budget_exceeded':
      return '今日大模型预算已用完，暂时无法回答（UTC 零点自动恢复；要立即恢复请调大 LLM_DAILY_BUDGET_USD 并重启）。';
    case 'llm_disabled':
      return '当前未配置大模型密钥（OPENAI_API_KEY），追问对话不可用。';
    case 'llm_error':
      return '大模型接口暂时不可用，请稍后重试。';
    default:
      return '暂时无法回答，请稍后重试。';
  }
}

export function AiChatPanel({ projectId }: { projectId: string }) {
  const [messages, setMessages] = useState<ChatMsg[]>([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState('');
  const [degraded, setDegraded] = useState<string | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  const send = useCallback(
    async (raw: string) => {
      const content = raw.trim();
      if (!content || loading || !projectId) return;

      setInput('');
      setError('');
      setDegraded(null);
      const next = [...messages, { role: 'user' as const, content }];
      setMessages(next);
      setLoading(true);
      try {
        const res = await apiFetch<AiChatData>(`/projects/${projectId}/ai-chat`, {
          method: 'POST',
          body: JSON.stringify({ messages: next.slice(-HISTORY_LIMIT) }),
        });
        if (res.reply) {
          setMessages((prev) => [...prev, { role: 'assistant', content: res.reply as string }]);
        } else {
          setDegraded(res.degraded_reason || 'llm_error');
        }
      } catch (err: unknown) {
        setError(err instanceof Error ? err.message : '发送失败');
        // 撤回乐观插入、把话还给输入框 —— 重发不重复，改一下再发也行
        setMessages(messages);
        setInput(content);
      } finally {
        setLoading(false);
      }
    },
    [projectId, loading, messages],
  );

  // 新消息 / 加载态 / 提示出现时滚到底部
  useEffect(() => {
    listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' });
  }, [messages, loading, degraded, error]);

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault();
      void send(input);
    }
  };

  return (
    <div className="overflow-hidden border border-line bg-surface">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-4 py-3 sm:px-5">
        <p className="text-xs text-ink-muted">多轮追问 · 回答基于本项目的系统评分数据，不构成投资建议</p>
        {messages.length > 0 ? (
          <button
            type="button"
            className="btn-secondary !py-1 text-xs"
            onClick={() => {
              setMessages([]);
              setError('');
              setDegraded(null);
            }}
            disabled={loading}
          >
            清空对话
          </button>
        ) : null}
      </div>

      <div ref={listRef} className="max-h-96 space-y-3 overflow-y-auto px-4 py-4 sm:px-5">
        {messages.length === 0 && !loading ? (
          <div className="py-2">
            <p className="text-sm text-ink-muted">试着问：</p>
            <div className="mt-3 flex flex-wrap gap-2">
              {PRESET_QUESTIONS.map((q) => (
                <button
                  key={q}
                  type="button"
                  className="rounded-full border border-line bg-surface-2 px-3 py-1.5 text-xs text-ink-muted transition-colors hover:border-farm/60 hover:text-ink"
                  onClick={() => void send(q)}
                >
                  {q}
                </button>
              ))}
            </div>
          </div>
        ) : null}

        {messages.map((m, i) => (
          <div key={i} className={`flex ${m.role === 'user' ? 'justify-end' : 'justify-start'}`}>
            <div
              className={`max-w-[85%] whitespace-pre-wrap rounded-2xl px-3.5 py-2 text-sm leading-6 ${
                m.role === 'user'
                  ? 'bg-farm-soft text-ink dark:bg-farm/20'
                  : 'border border-line bg-surface-2 text-ink/90'
              }`}
            >
              {m.content}
            </div>
          </div>
        ))}

        {loading ? (
          <div className="flex justify-start">
            <div className="flex gap-1.5 rounded-2xl border border-line bg-surface-2 px-4 py-3">
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-faint" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-faint [animation-delay:150ms]" />
              <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-ink-faint [animation-delay:300ms]" />
            </div>
          </div>
        ) : null}

        {degraded ? (
          <div className="rounded-xl border border-amber-300 bg-amber-50 px-3.5 py-2.5 text-sm text-amber-800 dark:border-amber-500/30 dark:bg-amber-500/10 dark:text-amber-300">
            {degradedNotice(degraded)}
          </div>
        ) : null}

        {error ? (
          <div className="rounded-xl border border-red-200 bg-red-50 px-3.5 py-2.5 text-sm text-red-700 dark:border-red-500/30 dark:bg-red-500/10 dark:text-red-300">
            {error}
          </div>
        ) : null}
      </div>

      <div className="border-t border-line px-4 py-3 sm:px-5">
        <div className="flex items-end gap-2">
          <textarea
            value={input}
            onChange={(e) => setInput(e.target.value.slice(0, MAX_INPUT_CHARS))}
            onKeyDown={onKeyDown}
            rows={2}
            placeholder="追问这个项目…（Enter 发送，Shift+Enter 换行）"
            className="min-h-0 flex-1 resize-none rounded-xl border border-line bg-surface-2 px-3 py-2 text-sm text-ink placeholder:text-ink-faint focus:border-farm/60 focus:outline-none"
            disabled={loading}
          />
          <button
            type="button"
            className="btn-primary !py-2"
            onClick={() => void send(input)}
            disabled={loading || !input.trim()}
          >
            {loading ? '发送中…' : '发送'}
          </button>
        </div>
        <p className="mt-1.5 text-right text-[11px] text-ink-faint">
          {input.length}/{MAX_INPUT_CHARS}
        </p>
      </div>
    </div>
  );
}
