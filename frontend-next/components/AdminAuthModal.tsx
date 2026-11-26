'use client';

import { useEffect, useState } from 'react';
import type { FormEvent } from 'react';
import { KeyRound, LogIn, LogOut, ShieldCheck, UserPlus, X } from 'lucide-react';
import { Modal } from '@/components/Modal';
import {
  API_BASE,
  apiFetchEnvelope,
  clearStoredCredentials,
  getStoredAuthSummary,
  getStoredRefreshToken,
  saveAdminApiKey,
  saveJwtSession,
} from '@/lib/api';
import type { StoredAuthSummary } from '@/lib/api';

interface AdminAuthModalProps {
  isOpen: boolean;
  onClose: () => void;
}

interface LoginPayload {
  access_token?: string;
  refresh_token?: string;
  user?: {
    id: string;
    email: string;
    display_name?: string | null;
    role: string;
  };
}

export function AdminAuthModal({ isOpen, onClose }: AdminAuthModalProps) {
  const [tab, setTab] = useState<'api_key' | 'login' | 'register'>('api_key');
  const [summary, setSummary] = useState<StoredAuthSummary>({ mode: 'none', label: '管理员鉴权' });
  const [apiKeyInput, setApiKeyInput] = useState('');
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [bootstrapToken, setBootstrapToken] = useState('');
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');

  useEffect(() => {
    if (!isOpen) return;
    const current = getStoredAuthSummary();
    setSummary(current);
    setTab(current.mode === 'jwt' ? 'login' : 'api_key');
    setError('');
    setNotice('');
  }, [isOpen]);

  if (!isOpen) return null;

  const handleSaveApiKey = async (event: FormEvent) => {
    event.preventDefault();
    const trimmed = apiKeyInput.trim();
    if (!trimmed) {
      setError('请输入管理员 API Key（或以 ak_ 开头的动态密钥）');
      return;
    }

    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await fetch(`${API_BASE}/settings/config`, {
        headers: {
          Accept: 'application/json',
          'X-API-Key': trimmed,
        },
      });
      if (res.status === 401) {
        setError('密钥无效或已过期（HTTP 401），请核对后端 API_KEY 配置');
        return;
      }
      if (res.status === 403) {
        // 动态 ak_ 密钥可能是 analyst/viewer 角色，验签已通过但不具 settings 管理员权限
        saveAdminApiKey(trimmed, remember);
        setApiKeyInput('');
        onClose();
        window.location.reload();
        return;
      }
      if (!res.ok) {
        setError(`后端校验返回异常状态（HTTP ${res.status}）`);
        return;
      }
      saveAdminApiKey(trimmed, remember);
      setApiKeyInput('');
      onClose();
      window.location.reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '无法连接后端校验密钥');
    } finally {
      setBusy(false);
    }
  };

  const handleLogin = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError('请输入邮箱与密码');
      return;
    }

    setBusy(true);
    setError('');
    setNotice('');
    try {
      const res = await apiFetchEnvelope<LoginPayload>('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ email: email.trim(), password }),
      });
      if (!res.access_token || !res.user) {
        setError('登录响应缺少访问令牌');
        return;
      }
      saveJwtSession(
        res.access_token,
        res.refresh_token ?? null,
        res.user.email,
        res.user.role,
        remember,
      );
      setPassword('');
      onClose();
      window.location.reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '登录失败，请检查邮箱或密码');
    } finally {
      setBusy(false);
    }
  };

  const handleRegister = async (event: FormEvent) => {
    event.preventDefault();
    if (!email.trim() || !password) {
      setError('请输入注册邮箱与密码');
      return;
    }
    if (password.length < 8) {
      setError('密码长度至少 8 位，且需包含大小写字母与数字');
      return;
    }

    setBusy(true);
    setError('');
    setNotice('');
    try {
      const payload: Record<string, string> = {
        email: email.trim(),
        password,
      };
      if (displayName.trim()) {
        payload.display_name = displayName.trim();
      }
      if (bootstrapToken.trim()) {
        payload.bootstrap_token = bootstrapToken.trim();
      }

      const res = await apiFetchEnvelope<LoginPayload>('/auth/register', {
        method: 'POST',
        body: JSON.stringify(payload),
      });
      if (!res.access_token || !res.user) {
        setError('注册响应缺少访问令牌');
        return;
      }
      saveJwtSession(
        res.access_token,
        res.refresh_token ?? null,
        res.user.email,
        res.user.role,
        remember,
      );
      setPassword('');
      setBootstrapToken('');
      onClose();
      window.location.reload();
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : '注册失败，请检查输入信息');
    } finally {
      setBusy(false);
    }
  };

  const handleLogout = async () => {
    setBusy(true);
    setError('');
    try {
      const refreshToken = getStoredRefreshToken();
      if (summary.mode === 'jwt') {
        await apiFetchEnvelope<{ ok?: boolean }>('/auth/logout', {
          method: 'POST',
          body: JSON.stringify(refreshToken ? { refresh_token: refreshToken } : {}),
        }).catch(() => null);
      }
      clearStoredCredentials();
      setSummary(getStoredAuthSummary());
      setNotice('已清除本地凭据，已切换回独立访客模式');
      window.location.reload();
    } finally {
      setBusy(false);
    }
  };

  return (
    <Modal
      title="管理员密钥与账号登录"
      onClose={onClose}
      backdropClassName="bg-slate-950/70 backdrop-blur-sm"
    >
      <div className="w-full max-w-md rounded-2xl border border-line bg-surface-1 p-5 text-ink shadow-2xl">
        <div className="flex items-start justify-between gap-3 border-b border-line pb-3.5">
          <div className="flex items-center gap-2.5">
            <span className="flex h-9 w-9 items-center justify-center rounded-xl bg-emerald-500/15 text-farm">
              <ShieldCheck className="h-5 w-5" />
            </span>
            <div>
              <h2 className="text-base font-semibold text-ink">管理员密钥与账号登录</h2>
              <p className="text-xs text-ink-muted">
                用于访问运维台、系统设置、归档、导入导出与手动触发任务
              </p>
            </div>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭鉴权弹窗"
            className="rounded-lg p-1.5 text-ink-muted transition hover:bg-surface-2 hover:text-ink"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        {summary.mode !== 'none' && (
          <div className="mt-3.5 flex items-center justify-between gap-2 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3.5 py-2.5 text-xs">
            <div className="min-w-0">
              <div className="font-medium text-farm">当前已激活凭据：{summary.label}</div>
              {summary.role && (
                <div className="mt-0.5 font-mono text-[11px] text-ink-muted">
                  角色：{summary.role}
                </div>
              )}
            </div>
            <button
              type="button"
              disabled={busy}
              onClick={handleLogout}
              className="inline-flex shrink-0 items-center gap-1 rounded-lg border border-line bg-surface-1 px-2.5 py-1.5 text-xs font-medium text-ink transition hover:bg-surface-2 disabled:opacity-50"
            >
              <LogOut className="h-3.5 w-3.5" />
              清除凭据
            </button>
          </div>
        )}

        <div className="mt-4 grid grid-cols-3 gap-1 rounded-xl bg-surface-2 p-1 text-xs font-medium">
          <button
            type="button"
            onClick={() => {
              setTab('api_key');
              setError('');
            }}
            className={`inline-flex items-center justify-center gap-1 rounded-lg py-2 transition ${
              tab === 'api_key'
                ? 'bg-surface-1 text-ink shadow-sm'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            <KeyRound className="h-3.5 w-3.5" />
            API Key
          </button>
          <button
            type="button"
            onClick={() => {
              setTab('login');
              setError('');
            }}
            className={`inline-flex items-center justify-center gap-1 rounded-lg py-2 transition ${
              tab === 'login'
                ? 'bg-surface-1 text-ink shadow-sm'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            <LogIn className="h-3.5 w-3.5" />
            账号登录
          </button>
          <button
            type="button"
            onClick={() => {
              setTab('register');
              setError('');
            }}
            className={`inline-flex items-center justify-center gap-1 rounded-lg py-2 transition ${
              tab === 'register'
                ? 'bg-surface-1 text-ink shadow-sm'
                : 'text-ink-muted hover:text-ink'
            }`}
          >
            <UserPlus className="h-3.5 w-3.5" />
            注册账号
          </button>
        </div>

        {error && (
          <div className="mt-3 rounded-xl border border-red-500/30 bg-red-500/10 px-3 py-2 text-xs text-red-400">
            {error}
          </div>
        )}
        {notice && (
          <div className="mt-3 rounded-xl border border-emerald-500/30 bg-emerald-500/10 px-3 py-2 text-xs text-farm">
            {notice}
          </div>
        )}

        {tab === 'api_key' ? (
          <form onSubmit={handleSaveApiKey} className="mt-4 space-y-3.5">
            <div>
              <label htmlFor="admin-api-key-input" className="block text-xs font-medium text-ink-muted">
                管理员 API Key（服务端 `API_KEY` 或 `ak_` 动态密钥）
              </label>
              <input
                id="admin-api-key-input"
                type="password"
                autoComplete="off"
                value={apiKeyInput}
                onChange={(e) => setApiKeyInput(e.target.value)}
                placeholder="输入密钥后自动校验权限…"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-ink placeholder:text-ink-faint focus:border-emerald-500 focus:outline-none"
              />
            </div>

            <label className="flex items-center gap-2 text-xs text-ink-muted select-none">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="rounded border-line"
              />
              在本浏览器持久记住凭据（取消则仅当前标签页会话有效）
            </label>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={onClose} className="btn-secondary text-xs">
                取消
              </button>
              <button
                type="submit"
                disabled={busy}
                className="btn-primary inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
              >
                <KeyRound className="h-3.5 w-3.5" />
                {busy ? '正在校验…' : '验证并启用'}
              </button>
            </div>
          </form>
        ) : tab === 'login' ? (
          <form onSubmit={handleLogin} className="mt-4 space-y-3.5">
            <div>
              <label htmlFor="admin-login-email" className="block text-xs font-medium text-ink-muted">
                邮箱
              </label>
              <input
                id="admin-login-email"
                type="email"
                autoComplete="username"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="admin@example.com"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-emerald-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="admin-login-password" className="block text-xs font-medium text-ink-muted">
                密码
              </label>
              <input
                id="admin-login-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="输入登录密码…"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-emerald-500 focus:outline-none"
              />
            </div>

            <label className="flex items-center gap-2 text-xs text-ink-muted select-none">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="rounded border-line"
              />
              在本浏览器持久保持登录态
            </label>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={onClose} className="btn-secondary text-xs">
                取消
              </button>
              <button
                type="submit"
                disabled={busy}
                className="btn-primary inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
              >
                <LogIn className="h-3.5 w-3.5" />
                {busy ? '正在登录…' : '登录'}
              </button>
            </div>
          </form>
        ) : null}

        {tab === 'register' && (
          <form onSubmit={handleRegister} className="mt-4 space-y-3.5">
            <div>
              <label htmlFor="admin-register-email" className="block text-xs font-medium text-ink-muted">
                注册邮箱
              </label>
              <input
                id="admin-register-email"
                type="email"
                autoComplete="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                placeholder="you@example.com"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-emerald-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="admin-register-password" className="block text-xs font-medium text-ink-muted">
                设置密码（至少 8 位，含大小写字母与数字）
              </label>
              <input
                id="admin-register-password"
                type="password"
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="输入符合强度要求的密码…"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-emerald-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="admin-register-name" className="block text-xs font-medium text-ink-muted">
                显示昵称（可选）
              </label>
              <input
                id="admin-register-name"
                type="text"
                autoComplete="nickname"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                placeholder="例如：Alpha 研究员"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface-2 px-3 py-2 text-xs text-ink placeholder:text-ink-faint focus:border-emerald-500 focus:outline-none"
              />
            </div>

            <div>
              <label htmlFor="admin-register-bootstrap" className="block text-xs font-medium text-ink-muted">
                管理员自举令牌（可选，仅首位管理员且配置了 `REGISTRATION_BOOTSTRAP_TOKEN` 时需填）
              </label>
              <input
                id="admin-register-bootstrap"
                type="password"
                autoComplete="off"
                value={bootstrapToken}
                onChange={(e) => setBootstrapToken(e.target.value)}
                placeholder="普通用户注册请留空"
                className="mt-1.5 w-full rounded-xl border border-line bg-surface-2 px-3 py-2 font-mono text-xs text-ink placeholder:text-ink-faint focus:border-emerald-500 focus:outline-none"
              />
            </div>

            <label className="flex items-center gap-2 text-xs text-ink-muted select-none">
              <input
                type="checkbox"
                checked={remember}
                onChange={(e) => setRemember(e.target.checked)}
                className="rounded border-line"
              />
              在本浏览器持久保持登录态
            </label>

            <div className="flex justify-end gap-2 pt-1">
              <button type="button" onClick={onClose} className="btn-secondary text-xs">
                取消
              </button>
              <button
                type="submit"
                disabled={busy}
                className="btn-primary inline-flex items-center gap-1.5 text-xs disabled:opacity-50"
              >
                <UserPlus className="h-3.5 w-3.5" />
                {busy ? '正在注册…' : '创建账号并登录'}
              </button>
            </div>
          </form>
        )}
      </div>
    </Modal>
  );
}
