'use client';

import { useState } from 'react';
import { apiFetch } from '@/lib/api';

export function BotNotificationPanel() {
  const [command, setCommand] = useState('/alpha');
  const [reply, setReply] = useState<string | null>(null);
  const [cmdLoading, setCmdLoading] = useState(false);

  // 发送测试配置
  const [channel, setChannel] = useState<'discord' | 'telegram'>('discord');
  const [webhookUrl, setWebhookUrl] = useState('');
  const [botToken, setBotToken] = useState('');
  const [chatId, setChatId] = useState('');
  const [sendResult, setSendResult] = useState<{ ok: boolean; message: string } | null>(null);
  const [sendLoading, setSendLoading] = useState(false);

  const handleRunCommand = async (customCmd?: string) => {
    const cmdToRun = customCmd || command;
    setCmdLoading(true);
    setReply(null);
    try {
      const res = await apiFetch<{ ok: boolean; reply: string }>('/bot/command', {
        method: 'POST',
        body: JSON.stringify({ command: cmdToRun }),
      });
      if (res?.reply) {
        setReply(res.reply);
      }
    } catch (e: any) {
      setReply(`执行出错: ${e?.message || '网络连接失败'}`);
    } finally {
      setCmdLoading(false);
    }
  };

  const handleTestSend = async () => {
    setSendLoading(true);
    setSendResult(null);
    try {
      const res = await apiFetch<{ ok: boolean; status: string }>('/bot/test-send', {
        method: 'POST',
        body: JSON.stringify({
          channel,
          webhook_url: webhookUrl,
          bot_token: botToken,
          chat_id: chatId,
          title: '🎯 [Web3 Alpha Agent] 实时通道测试通知',
          message: '恭喜！您的机器人通道配置成功，Agent 将在发现顶级 FARM 机会时第一时间向您推送。',
        }),
      });
      if (res?.ok) {
        setSendResult({ ok: true, message: '测试消息已成功推送！请在对应群组或私聊中查收。' });
      } else {
        setSendResult({ ok: false, message: '发送失败，请检查 Webhook 或 Token 是否有效。' });
      }
    } catch (e: any) {
      setSendResult({ ok: false, message: `请求出错: ${e?.message || '配置无效'}` });
    } finally {
      setSendLoading(false);
    }
  };

  return (
    <div className="dash-card p-5 space-y-6">
      <div className="flex items-center justify-between border-b border-line pb-3">
        <div>
          <h2 className="text-sm font-bold text-ink flex items-center gap-2">
            <span>🤖</span>
            <span>Telegram / Discord 实时 Alpha 机器人与交互助手</span>
          </h2>
          <p className="text-xs text-ink-muted mt-0.5">
            实时捕获全网 ≥80 分高确定性项目与测试网水龙头，支持手机端指令交互
          </p>
        </div>
        <span className="text-[10px] font-mono px-2 py-0.5 rounded-full bg-emerald-500/10 text-emerald-400 border border-emerald-500/30">
          ● 双向交互就绪
        </span>
      </div>

      {/* 模拟指令交互终端 */}
      <div className="space-y-3">
        <span className="text-xs font-semibold text-ink flex items-center gap-1.5">
          <span>⚡</span>
          <span>交互式指令即时调试 (Interactive Command Terminal)</span>
        </span>

        <div className="flex flex-wrap items-center gap-1.5">
          {['/alpha', '/gas', '/faucets', '/calendar', '/help'].map((c) => (
            <button
              key={c}
              type="button"
              onClick={() => {
                setCommand(c);
                handleRunCommand(c);
              }}
              className={`px-2.5 py-1 rounded-lg font-mono text-xs transition border ${
                command === c
                  ? 'bg-brand-500 text-white border-brand-400 shadow-sm'
                  : 'bg-surface-2 text-ink-muted border-line hover:text-ink'
              }`}
            >
              {c}
            </button>
          ))}
        </div>

        <div className="flex items-center gap-2">
          <input
            type="text"
            value={command}
            onChange={(e) => setCommand(e.target.value)}
            placeholder="输入指令，如 /alpha 或 /gas"
            className="input font-mono text-xs flex-1"
          />
          <button
            type="button"
            onClick={() => handleRunCommand()}
            disabled={cmdLoading || !command.trim()}
            className="btn-primary !py-1.5 text-xs shrink-0"
          >
            {cmdLoading ? '执行中...' : '发送指令 ↵'}
          </button>
        </div>

        {/* 回复终端显示 */}
        {reply && (
          <div className="rounded-xl border border-line bg-surface-2/90 p-3.5 font-mono text-xs text-ink leading-relaxed whitespace-pre-wrap animate-fade-in">
            {reply}
          </div>
        )}
      </div>

      {/* 外部通道配置与连通性测试 */}
      <div className="space-y-3 pt-4 border-t border-line/60">
        <span className="text-xs font-semibold text-ink flex items-center gap-1.5">
          <span>📢</span>
          <span>外部通道连通性测试 (Discord Webhook / Telegram Bot)</span>
        </span>

        <div className="flex items-center gap-4 text-xs">
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="channel"
              value="discord"
              checked={channel === 'discord'}
              onChange={() => setChannel('discord')}
            />
            <span className="font-semibold text-ink">Discord Webhook</span>
          </label>
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input
              type="radio"
              name="channel"
              value="telegram"
              checked={channel === 'telegram'}
              onChange={() => setChannel('telegram')}
            />
            <span className="font-semibold text-ink">Telegram Bot</span>
          </label>
        </div>

        {channel === 'discord' ? (
          <div className="space-y-1.5">
            <label className="text-[11px] text-ink-muted">Discord 频道 Webhook URL</label>
            <input
              type="text"
              value={webhookUrl}
              onChange={(e) => setWebhookUrl(e.target.value)}
              placeholder="https://discord.com/api/webhooks/..."
              className="input font-mono text-xs w-full"
            />
          </div>
        ) : (
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
            <div className="space-y-1.5">
              <label className="text-[11px] text-ink-muted">Telegram Bot Token</label>
              <input
                type="text"
                value={botToken}
                onChange={(e) => setBotToken(e.target.value)}
                placeholder="123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
                className="input font-mono text-xs w-full"
              />
            </div>
            <div className="space-y-1.5">
              <label className="text-[11px] text-ink-muted">Chat ID (群组或私聊 ID)</label>
              <input
                type="text"
                value={chatId}
                onChange={(e) => setChatId(e.target.value)}
                placeholder="-1001234567890 或 987654321"
                className="input font-mono text-xs w-full"
              />
            </div>
          </div>
        )}

        <button
          type="button"
          onClick={handleTestSend}
          disabled={sendLoading}
          className="btn-secondary !py-1.5 text-xs flex items-center gap-1.5"
        >
          <span>{sendLoading ? '测试发送中...' : '发送测试通知卡片 ✉️'}</span>
        </button>

        {sendResult && (
          <div
            className={`p-2.5 rounded-lg text-xs border ${
              sendResult.ok
                ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
            }`}
          >
            {sendResult.message}
          </div>
        )}
      </div>
    </div>
  );
}
