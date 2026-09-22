'use client';

import { Suspense } from 'react';
import { TopBar } from '@/components/TopBar';
import { AirdropCalendarPanel } from '@/components/AirdropCalendarPanel';
import TokenUnlockRadarPanel from '@/components/TokenUnlockRadarPanel';

export default function CalendarPage() {
  return (
    <Suspense>
      <TopBar
        title="空投日历与倒计时"
        subtitle="全网关键快照 · TGE 发币 · 认领窗口 · 48h 紧急倒计时提醒 · 支持导入手机日历"
      />
      <div className="app-content space-y-6">
        <AirdropCalendarPanel />
        <TokenUnlockRadarPanel />
      </div>
    </Suspense>
  );
}
