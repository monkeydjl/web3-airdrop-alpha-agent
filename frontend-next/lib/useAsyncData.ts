'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { isAbortError } from './api';

export interface AsyncDataState<T> {
  data: T | null;
  error: string;
  loading: boolean;
  /** 手动重新拉取；会取消仍在飞行中的上一次请求 */
  reload: () => void;
}

/**
 * 带取消与代次守卫的数据获取。
 *
 * 解决原先每个页面手写 load() 的两类问题：
 * 1. 无 AbortController —— 组件卸载或参数变化后，旧请求仍会 setState；
 * 2. 无代次守卫 —— 慢的旧响应后到会覆盖新响应（连点刷新即可复现）。
 *
 * loader 收到 AbortSignal，应透传给 fetch/apiFetch。
 */
export function useAsyncData<T>(
  loader: (signal: AbortSignal) => Promise<T>,
  deps: unknown[],
  options?: { immediate?: boolean },
): AsyncDataState<T> {
  const immediate = options?.immediate ?? true;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(immediate);

  const generation = useRef(0);
  const controller = useRef<AbortController | null>(null);
  const mounted = useRef(true);
  const loaderRef = useRef(loader);
  loaderRef.current = loader;

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      controller.current?.abort();
    };
  }, []);

  const run = useCallback(() => {
    controller.current?.abort();
    const ac = new AbortController();
    controller.current = ac;
    const myGeneration = ++generation.current;

    setLoading(true);
    setError('');

    loaderRef
      .current(ac.signal)
      .then((result) => {
        // 只有最新一次请求的结果才允许落地
        if (!mounted.current || myGeneration !== generation.current) return;
        setData(result);
      })
      .catch((err: unknown) => {
        if (isAbortError(err)) return;
        if (!mounted.current || myGeneration !== generation.current) return;
        setError(err instanceof Error ? err.message : '加载失败');
      })
      .finally(() => {
        if (!mounted.current || myGeneration !== generation.current) return;
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    if (!immediate) return;
    run();
    // deps 由调用方声明，run 本身稳定
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps);

  return { data, error, loading, reload: run };
}
