"use client";

import { Brain, Mic, Radio, Volume2 } from "lucide-react";
import type React from "react";

import { VoiceBars } from "@/components/playground/voice-bars";
import type { VoicePhase } from "@/hooks/use-voice-session";
import { cn } from "@/lib/utils";

type LiveVisualizationProps = {
  phase: VoicePhase;
  status: string;
  duration: string;
  messages: number;
  latency: string;
};

const phaseCopy: Record<VoicePhase, string> = {
  idle: "Idle",
  listening: "Listening",
  thinking: "Thinking",
  speaking: "Speaking",
};

export function LiveVisualization({
  phase,
  status,
  duration,
  messages,
  latency,
}: LiveVisualizationProps) {
  return (
    <aside className="console-panel flex min-h-[540px] w-full flex-col rounded-2xl p-4 max-[850px]:min-h-[460px] max-[850px]:p-3 lg:min-h-0 lg:overflow-y-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold text-slate-900">Live Visualization</h2>
        <div
          className={cn(
            "inline-flex items-center gap-2 rounded-full border px-2.5 py-1 text-xs font-medium",
            status === "connected"
              ? "border-emerald-200 bg-[var(--success-soft)] text-[var(--success)]"
              : "border-[var(--border)] bg-[var(--surface-muted)] text-slate-500",
          )}
        >
          <span className="size-1.5 rounded-full bg-current" />
          {status === "connected" ? "Live" : "Offline"}
        </div>
      </div>

      <div className="wave-field relative mt-5 h-48 overflow-hidden rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] max-[850px]:mt-3 max-[850px]:h-28">
        <div className="absolute inset-x-0 top-1/2 h-24 -translate-y-1/2 opacity-90">
          <div className="h-full w-[180%] -translate-x-1/4 animate-[pulse_4s_ease-in-out_infinite] rounded-[50%] border-t border-[var(--accent)]/70 bg-[radial-gradient(ellipse_at_center,rgba(79,70,229,0.16),transparent_62%)]" />
        </div>
        <div className="absolute inset-x-0 top-[45%] h-20 -translate-y-1/2 opacity-80">
          <div className="h-full w-[170%] -translate-x-1/3 animate-[pulse_3.2s_ease-in-out_infinite] rounded-[50%] border-t border-sky-400/60 bg-[radial-gradient(ellipse_at_center,rgba(14,116,233,0.12),transparent_64%)]" />
        </div>
      </div>

      <div className="flex flex-1 items-center justify-center py-12 max-[850px]:py-6">
        <div
          className={cn(
            "voice-orb flex size-44 items-center justify-center rounded-full border transition max-[850px]:size-32",
            phase === "speaking"
              ? "border-[var(--accent)]/50 bg-[var(--accent-soft)] shadow-[0_18px_50px_-16px_rgba(79,70,229,0.5)]"
              : "border-[var(--border-strong)] bg-white shadow-[var(--shadow-md)]",
          )}
        >
          <div className="flex size-32 items-center justify-center rounded-full border border-[var(--border)] bg-[radial-gradient(circle,rgba(79,70,229,0.1),#ffffff_70%)] max-[850px]:size-24">
            <VoiceBars active={phase !== "idle"} compact />
          </div>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-3 max-[850px]:gap-2">
        <StateTile icon={Mic} label="Listening" active={phase === "listening"} />
        <StateTile icon={Brain} label="Thinking" active={phase === "thinking"} />
        <StateTile icon={Volume2} label="Speaking" active={phase === "speaking"} />
      </div>

      <div className="mt-4 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-4 max-[850px]:mt-3 max-[850px]:p-3">
        <div className="mb-3 flex items-center gap-2 text-xs font-semibold text-slate-600">
          <Radio className="size-4 text-[var(--accent)]" />
          Session Info
        </div>
        <div className="grid grid-cols-4 gap-2 text-xs">
          <InfoCell label="Duration" value={duration} />
          <InfoCell label="Messages" value={String(messages)} />
          <InfoCell label="Latency" value={latency} />
          <InfoCell label="Status" value={phaseCopy[phase]} accent />
        </div>
      </div>
    </aside>
  );
}

function StateTile({
  icon: Icon,
  label,
  active,
}: {
  icon: React.ElementType;
  label: string;
  active: boolean;
}) {
  return (
    <div
      className={cn(
        "rounded-xl border border-[var(--border)] bg-white p-3 text-center text-xs font-medium text-slate-500 transition max-[850px]:p-2",
        active && "border-[var(--accent)]/40 bg-[var(--accent-soft)] text-[var(--accent-hover)] shadow-[var(--shadow-xs)]",
      )}
    >
      <Icon className="mx-auto mb-2 size-4" />
      <div>{label}</div>
    </div>
  );
}

function InfoCell({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return (
    <div className="min-w-0 rounded-lg border border-[var(--border)] bg-white p-2">
      <div className="truncate text-[10px] font-medium text-slate-400">{label}</div>
      <div className={cn("mono mt-1 truncate text-sm text-slate-900", accent && "text-[var(--accent)]")}>{value}</div>
    </div>
  );
}
