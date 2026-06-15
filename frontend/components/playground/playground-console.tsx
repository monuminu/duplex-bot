"use client";

import { useEffect, useRef, useState } from "react";
import {
  Activity,
  Bot,
  Globe2,
  Mic,
  PhoneOff,
  Play,
  RotateCcw,
  Send,
  ShieldCheck,
  SlidersHorizontal,
  SquarePen,
  Trash2,
  Volume2,
} from "lucide-react";

import { LiveVisualization } from "@/components/playground/live-visualization";
import { VoiceBars } from "@/components/playground/voice-bars";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DEFAULT_MICROPHONE_VALUE, useVoiceSession } from "@/hooks/use-voice-session";
import { listVoiceAgents, type VoiceAgentListItem } from "@/lib/voice-agents";
import { cn } from "@/lib/utils";

export function PlaygroundConsole() {
  const [agents, setAgents] = useState<VoiceAgentListItem[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState("");
  const [agentsLoading, setAgentsLoading] = useState(true);
  const voice = useVoiceSession({ agentId: selectedAgentId });
  const messageCount = voice.messages.filter((message) => message.role !== "system").length;

  useEffect(() => {
    async function loadAgents() {
      try {
        const items = await listVoiceAgents();
        setAgents(items);
        setSelectedAgentId((current) => current || items[0]?.id || "");
      } catch {
        setAgents([]);
      } finally {
        // Gate Connect until this resolves: connecting before the agent list
        // loads sends no agent_id, so the backend falls back to the env config
        // (empty welcome message) and the user hears nothing on connect.
        setAgentsLoading(false);
      }
    }
    void loadAgents();
  }, []);

  return (
    <TooltipProvider delayDuration={200}>
      <section className="flex min-w-0 flex-1 flex-col lg:h-screen lg:min-h-0">
        <TopBar status={voice.status} />

        <div className="flex min-h-0 flex-1 flex-col px-4 py-4 max-[850px]:py-3 md:px-6 lg:overflow-hidden lg:px-7">
          <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
            <div className="flex min-w-0 flex-col lg:min-h-0">
              <div className="console-panel shrink-0 rounded-2xl p-4 max-[850px]:p-3">
                <div className="flex flex-col gap-4 max-[850px]:gap-3 lg:flex-row lg:items-center lg:justify-between">
                  <AgentSelector
                    agents={agents}
                    selectedAgentId={selectedAgentId}
                    onSelectedAgentIdChange={setSelectedAgentId}
                    disabled={voice.status === "connected" || voice.status === "connecting"}
                  />
                  <div className="flex flex-wrap gap-2">
                    <Button variant="secondary" size="sm" onClick={voice.clearChat}>
                      <Trash2 className="size-4" />
                      Clear Chat
                    </Button>
                    <Button variant="secondary" size="sm" onClick={voice.newSession}>
                      <RotateCcw className="size-4" />
                      New Session
                    </Button>
                    {voice.status === "connected" ? (
                      <Button variant="destructive" size="sm" onClick={voice.disconnect}>
                        <PhoneOff className="size-4" />
                        Disconnect
                      </Button>
                    ) : (
                      <Button
                        size="sm"
                        onClick={voice.connect}
                        disabled={agentsLoading || voice.status === "connecting"}
                      >
                        <Play className="size-4" />
                        {agentsLoading
                          ? "Loading"
                          : voice.status === "connecting"
                            ? "Connecting"
                            : "Connect"}
                      </Button>
                    )}
                  </div>
                </div>

                <div className="mt-4 grid gap-3 max-[850px]:mt-3 lg:grid-cols-[minmax(0,1fr)_220px]">
                  <div>
                    <label className="mb-2 block text-xs font-medium text-slate-600">Microphone</label>
                    <Select
                      value={voice.selectedDeviceId || DEFAULT_MICROPHONE_VALUE}
                      onValueChange={(value) => {
                        voice.setSelectedDeviceId(
                          value === DEFAULT_MICROPHONE_VALUE ? "" : value,
                        );
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Select microphone" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value={DEFAULT_MICROPHONE_VALUE}>Default microphone</SelectItem>
                        {voice.devices.map((device) => (
                          <SelectItem key={device.deviceId} value={device.deviceId}>
                            {device.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <div className="flex items-end">
                    <Button variant="secondary" className="w-full" onClick={voice.refreshDevicesWithPermission}>
                      <SlidersHorizontal className="size-4" />
                      Refresh Devices
                    </Button>
                  </div>
                </div>
              </div>

              <ChatPanel
                messages={voice.messages}
                phase={voice.phase}
                status={voice.status}
                error={voice.error}
                onConnect={voice.connect}
                agentsLoading={agentsLoading}
              />
            </div>

            <LiveVisualization
              phase={voice.phase}
              status={voice.status}
              duration={formatDuration(voice.durationSeconds)}
              messages={messageCount}
              latency={voice.latencyMs === null ? "N/A" : `${voice.latencyMs}ms`}
            />
          </div>
        </div>
      </section>
    </TooltipProvider>
  );
}

function TopBar({ status }: { status: string }) {
  return (
    <header className="flex h-16 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-[var(--border)] bg-white/85 px-4 backdrop-blur max-[850px]:h-14 md:px-6 lg:px-7">
      <div className="flex items-center gap-3">
        <div className="display text-base text-slate-900">Playground</div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div className="inline-flex items-center rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-xs font-medium text-slate-600">
          <span
            className={cn(
              "mr-2 inline-block size-2 rounded-full",
              status === "connected" ? "bg-[var(--success)]" : "bg-slate-300",
            )}
          />
          System Status: {status === "connected" ? "Voice Session Live" : "Ready"}
        </div>
        <div className="mono hidden rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2 text-xs text-slate-600 sm:flex sm:items-center sm:gap-2">
          <Globe2 className="size-4 text-[var(--accent)]" />
          16 kHz PCM
        </div>
      </div>
    </header>
  );
}

function AgentSelector({
  agents,
  selectedAgentId,
  onSelectedAgentIdChange,
  disabled,
}: {
  agents: VoiceAgentListItem[];
  selectedAgentId: string;
  onSelectedAgentIdChange: (agentId: string) => void;
  disabled: boolean;
}) {
  const selectedAgent = agents.find((agent) => agent.id === selectedAgentId);

  return (
    <div className="min-w-0 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3 max-[850px]:p-2.5 lg:min-w-80">
      <div className="mb-2 text-xs font-medium text-slate-500">Select Voice Agent</div>
      <div className="flex w-full items-center gap-3 text-left">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)] max-[850px]:size-9">
          <Bot className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <Select
            value={selectedAgentId || "environment"}
            onValueChange={(value) => onSelectedAgentIdChange(value === "environment" ? "" : value)}
            disabled={disabled}
          >
            <SelectTrigger className="h-8 border-0 bg-transparent px-0 py-0 font-semibold text-slate-900 shadow-none hover:border-0 focus:ring-0">
              <SelectValue placeholder="Environment default" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="environment">Environment default</SelectItem>
              {agents.map((agent) => (
                <SelectItem key={agent.id} value={agent.id}>
                  {agent.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <div className="mt-1 flex items-center gap-2 text-xs font-medium text-[var(--success)]">
            <span className="size-1.5 rounded-full bg-current" />
            {selectedAgent ? "Saved agent" : "Environment config"}
          </div>
        </div>
      </div>
    </div>
  );
}

function ChatPanel({
  messages,
  phase,
  status,
  error,
  onConnect,
  agentsLoading,
}: {
  messages: ReturnType<typeof useVoiceSession>["messages"];
  phase: ReturnType<typeof useVoiceSession>["phase"];
  status: ReturnType<typeof useVoiceSession>["status"];
  error: string;
  onConnect: () => void;
  agentsLoading: boolean;
}) {
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;

    transcript.scrollTop = transcript.scrollHeight;
  }, [messages.length, phase]);

  return (
    <section className="console-panel mt-4 flex min-h-[520px] flex-1 flex-col rounded-2xl max-[850px]:mt-3 max-[850px]:min-h-[420px] lg:min-h-0 lg:overflow-hidden">
      <div ref={transcriptRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 md:p-6">
        {messages.length === 0 ? (
          <div className="flex h-full min-h-[360px] flex-col items-center justify-center text-center max-[850px]:min-h-[260px] lg:min-h-0">
            <div className="mb-6 flex size-20 items-center justify-center rounded-2xl bg-[var(--accent-soft)] text-[var(--accent)] shadow-[0_16px_40px_-16px_rgba(79,70,229,0.45)] max-[850px]:mb-4 max-[850px]:size-16">
              <Mic className="size-8" />
            </div>
            <h2 className="text-lg font-semibold text-slate-900">Start a live voice session</h2>
            <p className="mt-2.5 max-w-md text-sm leading-6 text-slate-500">
              Connect your microphone to stream audio to the backend and see live transcripts here.
            </p>
            <Button
              className="mt-6"
              onClick={onConnect}
              disabled={agentsLoading || status === "connecting" || status === "connected"}
            >
              <Play className="size-4" />
              {agentsLoading
                ? "Loading agents"
                : status === "connecting"
                  ? "Connecting"
                  : "Connect"}
            </Button>
            {error ? <p className="mt-4 max-w-md text-sm text-[var(--danger)]">{error}</p> : null}
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-5">
            <div className="self-center rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-xs font-medium text-slate-500">
              Today
            </div>
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {phase === "thinking" ? (
              <div className="inline-flex w-fit items-center gap-3 rounded-lg border border-[var(--accent)]/20 bg-[var(--accent-soft)] px-3 py-2 text-xs font-medium text-[var(--accent-hover)]">
                <Activity className="size-4" />
                Agent is thinking
                <span className="flex gap-1">
                  <span className="size-1.5 animate-pulse rounded-full bg-current" />
                  <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:120ms]" />
                  <span className="size-1.5 animate-pulse rounded-full bg-current [animation-delay:240ms]" />
                </span>
              </div>
            ) : null}
          </div>
        )}
      </div>

      <div className="border-t border-[var(--border)] p-4 max-[850px]:p-3">
        <div className="flex items-center gap-3 rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
          <input
            disabled
            className="min-w-0 flex-1 bg-transparent text-sm text-slate-600 outline-none placeholder:text-slate-400"
            placeholder="Text input is reserved for a later release."
          />
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant={status === "connected" ? "default" : "secondary"} size="icon" aria-label="Voice input">
                <Mic className="size-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent>Voice input</TooltipContent>
          </Tooltip>
          <Button variant="ghost" size="icon" disabled aria-label="Send text">
            <Send className="size-4" />
          </Button>
        </div>
        <div className="mt-3 flex flex-wrap items-center justify-center gap-5 text-xs font-medium text-slate-500">
          <span className="inline-flex items-center gap-2">
            <ShieldCheck className="size-4 text-[var(--success)]" />
            {status === "connected" ? "Voice is ready" : "Voice is disconnected"}
          </span>
          <VoiceBars compact active={status === "connected"} />
          <span className="inline-flex items-center gap-2">
            <Volume2 className="size-4 text-[var(--accent)]" />
            16 kHz PCM
          </span>
        </div>
      </div>
    </section>
  );
}

function MessageBubble({ message }: { message: ReturnType<typeof useVoiceSession>["messages"][number] }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system";

  if (isSystem) {
    return (
      <div className="self-center rounded-full border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-1 text-xs font-medium text-slate-500">
        {message.text}
      </div>
    );
  }

  return (
    <div className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser ? (
        <div className="mt-6 flex size-10 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
          <Bot className="size-5" />
        </div>
      ) : null}
      <div className={cn("max-w-[78%]", isUser && "items-end")}>
        <div className={cn("mb-1 flex items-center gap-2 text-xs text-slate-400", isUser && "justify-end")}>
          <span className="font-medium text-slate-500">{isUser ? "You" : "Customer Support Agent"}</span>
          <span className="mono">
            {message.timestamp.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
        <div
          className={cn(
            "rounded-2xl px-4 py-3 text-sm leading-6 break-words [overflow-wrap:anywhere] shadow-[var(--shadow-xs)]",
            isUser
              ? "rounded-tr-sm bg-[var(--accent)] text-white"
              : "rounded-tl-sm border border-[var(--border)] bg-white text-slate-800",
          )}
        >
          {message.text}
        </div>
      </div>
      {isUser ? (
        <div className="mt-6 flex size-10 shrink-0 items-center justify-center rounded-xl border border-[var(--border-strong)] bg-white text-slate-500 shadow-[var(--shadow-xs)]">
          <SquarePen className="size-4" />
        </div>
      ) : null}
    </div>
  );
}

function formatDuration(totalSeconds: number) {
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  return `${minutes}:${String(seconds).padStart(2, "0")}`;
}
