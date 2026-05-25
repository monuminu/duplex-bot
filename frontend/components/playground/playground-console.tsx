"use client";

import { useEffect, useRef } from "react";
import {
  Activity,
  BarChart3,
  Bell,
  BookOpen,
  Bot,
  ChevronDown,
  Globe2,
  HelpCircle,
  Home,
  Link2,
  Megaphone,
  Mic,
  Phone,
  PhoneOff,
  Play,
  RotateCcw,
  Send,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  SquarePen,
  TestTube2,
  Trash2,
  Users,
  Volume2,
} from "lucide-react";

import { LiveVisualization } from "@/components/playground/live-visualization";
import { VoiceBars } from "@/components/playground/voice-bars";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";
import { DEFAULT_MICROPHONE_VALUE, useVoiceSession } from "@/hooks/use-voice-session";
import { cn } from "@/lib/utils";

const navItems = [
  { label: "Dashboard", icon: Home },
  { label: "Voice Agents", icon: Bot },
  { label: "Playground", icon: Sparkles, active: true },
  { label: "Calls", icon: Phone },
  { label: "Campaigns", icon: Megaphone },
  { label: "Knowledge Base", icon: BookOpen },
  { label: "Evaluations", icon: TestTube2 },
  { label: "Analytics", icon: BarChart3 },
  { label: "Integrations", icon: Link2 },
  { label: "Phone Numbers", icon: Users },
  { label: "Settings", icon: Settings },
];

export function PlaygroundConsole() {
  const voice = useVoiceSession();
  const messageCount = voice.messages.filter((message) => message.role !== "system").length;

  return (
    <TooltipProvider delayDuration={200}>
      <main className="min-h-screen w-full text-slate-100 lg:h-screen lg:overflow-hidden">
        <div className="flex min-h-screen w-full lg:h-screen">
          <Sidebar />
          <section className="flex min-w-0 flex-1 flex-col lg:h-screen lg:min-h-0">
            <TopBar status={voice.status} />

            <div className="flex min-h-0 flex-1 flex-col px-4 py-4 max-[850px]:py-3 md:px-6 lg:overflow-hidden lg:px-7">
              <div className="mb-4 shrink-0 max-[850px]:mb-3">
                <h1 className="text-2xl font-semibold text-white neon-cyan max-[850px]:text-xl md:text-[2rem]">
                  Playground
                </h1>
                <p className="mt-2 max-w-5xl text-sm leading-6 text-slate-400 max-[850px]:mt-1 max-[850px]:text-xs max-[850px]:leading-5">
                  Test your voice agent in real time. Start a conversation and inspect how it listens,
                  thinks, and responds.
                </p>
              </div>

              <div className="grid min-h-0 flex-1 gap-4 xl:grid-cols-[minmax(0,1fr)_420px] 2xl:grid-cols-[minmax(0,1fr)_460px]">
                <div className="flex min-w-0 flex-col lg:min-h-0">
                  <div className="console-panel shrink-0 rounded-lg p-4 max-[850px]:p-3">
                    <div className="flex flex-col gap-4 max-[850px]:gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <AgentSelector />
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
                          <Button size="sm" onClick={voice.connect} disabled={voice.status === "connecting"}>
                            <Play className="size-4" />
                            {voice.status === "connecting" ? "Connecting" : "Connect"}
                          </Button>
                        )}
                      </div>
                    </div>

                    <div className="mt-4 grid gap-3 max-[850px]:mt-3 lg:grid-cols-[minmax(0,1fr)_220px]">
                      <div>
                        <label className="mb-2 block text-xs text-slate-400">Microphone</label>
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
        </div>
      </main>
    </TooltipProvider>
  );
}

function Sidebar() {
  return (
    <aside className="console-panel sticky top-0 hidden h-screen w-64 shrink-0 flex-col rounded-none border-y-0 border-l-0 p-4 max-[850px]:p-3 lg:flex 2xl:w-72">
      <div className="mb-7 flex items-center gap-3 px-1 py-2 max-[850px]:mb-5">
        <div className="text-base font-semibold text-white neon-cyan">VoiceAgent</div>
        <div className="ml-auto flex size-8 items-center justify-center rounded-md border border-cyan-300/30 bg-cyan-300/10 text-cyan-200 shadow-[0_0_22px_rgba(0,255,255,0.18)]">
          <VoiceBars compact />
        </div>
      </div>

      <nav className="space-y-1.5 max-[850px]:space-y-1">
        {navItems.map((item) => (
          <button
            key={item.label}
            type="button"
            className={cn(
              "flex w-full items-center gap-3 rounded-md px-3 py-2.5 text-left text-sm text-slate-400 transition hover:bg-white/[0.06] hover:text-white max-[850px]:py-2 max-[850px]:text-xs",
              item.active && "bg-cyan-300/12 text-cyan-100 shadow-[inset_2px_0_0_rgba(0,255,255,0.65)]",
            )}
          >
            <item.icon className="size-4 shrink-0" />
            <span className="truncate">{item.label}</span>
          </button>
        ))}
      </nav>

      <div className="mt-auto space-y-3 max-[850px]:space-y-2">
        <div className="rounded-md border border-white/10 bg-white/[0.03] p-3 max-[850px]:p-2.5">
          <div className="mb-2 text-[10px] text-slate-500">Environment</div>
          <button className="flex w-full items-center justify-between text-xs text-white" type="button">
            <span className="inline-flex items-center gap-2">
              <span className="size-2 rounded-full bg-emerald-300" />
              Production
            </span>
            <ChevronDown className="size-3 text-slate-500" />
          </button>
        </div>

        <div className="rounded-md border border-white/10 bg-white/[0.03] p-3 max-[850px]:p-2.5">
          <div className="flex items-center gap-2 text-xs text-white">
            <HelpCircle className="size-4 text-cyan-300" />
            Get help
          </div>
          <p className="mt-2 text-[11px] leading-5 text-slate-500">Docs and contact support links are placeholders.</p>
          <Button className="mt-3 w-full" size="sm" variant="secondary">
            View Docs
          </Button>
        </div>
      </div>
    </aside>
  );
}

function TopBar({ status }: { status: string }) {
  return (
    <header className="flex h-16 shrink-0 flex-wrap items-center justify-between gap-3 border-b border-white/10 bg-slate-950/40 px-4 backdrop-blur max-[850px]:h-14 md:px-6 lg:px-7">
      <div className="flex items-center gap-3 lg:hidden">
        <div className="text-sm font-semibold text-white neon-cyan">VoiceAgent</div>
        <div className="flex size-9 items-center justify-center rounded-md border border-cyan-300/30 bg-cyan-300/10 text-cyan-200">
          <VoiceBars compact />
        </div>
      </div>

      <div className="ml-auto flex items-center gap-2">
        <div className="hidden rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-400 md:block">
          <span className="mr-2 inline-block size-2 rounded-full bg-emerald-300" />
          System Status: {status === "connected" ? "Voice Session Live" : "Ready"}
        </div>
        <div className="hidden rounded-md border border-white/10 bg-white/[0.04] px-3 py-2 text-xs text-slate-300 sm:flex sm:items-center sm:gap-2">
          <Globe2 className="size-4 text-cyan-300" />
          Credits 23,450
        </div>
        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="secondary" size="icon" aria-label="Notifications">
              <Bell className="size-4" />
            </Button>
          </TooltipTrigger>
          <TooltipContent>Notifications</TooltipContent>
        </Tooltip>
        <Avatar className="border border-cyan-300/30">
          <AvatarFallback>VA</AvatarFallback>
        </Avatar>
      </div>
    </header>
  );
}

function AgentSelector() {
  return (
    <div className="min-w-0 rounded-md border border-white/10 bg-slate-950/50 p-3 max-[850px]:p-2.5 lg:min-w-80">
      <div className="mb-2 text-xs text-slate-500">Select Voice Agent</div>
      <button className="flex w-full items-center gap-3 text-left" type="button">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-full border border-fuchsia-400/30 bg-fuchsia-400/10 text-fuchsia-200 max-[850px]:size-9">
          <Bot className="size-5" />
        </div>
        <div className="min-w-0 flex-1">
          <div className="truncate text-sm font-semibold text-white">Customer Support Agent</div>
          <div className="mt-1 flex items-center gap-2 text-xs text-emerald-300">
            <span className="size-1.5 rounded-full bg-current" />
            Online
          </div>
        </div>
        <ChevronDown className="size-4 text-slate-500" />
      </button>
    </div>
  );
}

function ChatPanel({
  messages,
  phase,
  status,
  error,
  onConnect,
}: {
  messages: ReturnType<typeof useVoiceSession>["messages"];
  phase: ReturnType<typeof useVoiceSession>["phase"];
  status: ReturnType<typeof useVoiceSession>["status"];
  error: string;
  onConnect: () => void;
}) {
  const transcriptRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const transcript = transcriptRef.current;
    if (!transcript) return;

    transcript.scrollTop = transcript.scrollHeight;
  }, [messages.length, phase]);

  return (
    <section className="console-panel mt-4 flex min-h-[520px] flex-1 flex-col rounded-lg max-[850px]:mt-3 max-[850px]:min-h-[420px] lg:min-h-0 lg:overflow-hidden">
      <div ref={transcriptRef} className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4 md:p-6">
        {messages.length === 0 ? (
          <div className="flex h-full min-h-[360px] flex-col items-center justify-center text-center max-[850px]:min-h-[260px] lg:min-h-0">
            <div className="mb-6 flex size-20 items-center justify-center rounded-full border border-cyan-300/30 bg-cyan-300/10 text-cyan-200 shadow-[0_0_42px_rgba(0,255,255,0.18)] max-[850px]:mb-4 max-[850px]:size-16">
              <Mic className="size-8" />
            </div>
            <h2 className="text-lg font-semibold text-white">Start a live voice session</h2>
            <p className="mt-3 max-w-md text-sm leading-6 text-slate-400">
              Connect your microphone to stream audio to the backend and see live transcripts here.
            </p>
            <Button className="mt-6" onClick={onConnect} disabled={status === "connecting" || status === "connected"}>
              <Play className="size-4" />
              {status === "connecting" ? "Connecting" : "Connect"}
            </Button>
            {error ? <p className="mt-4 max-w-md text-sm text-rose-300">{error}</p> : null}
          </div>
        ) : (
          <div className="mx-auto flex max-w-4xl flex-col gap-5">
            <div className="self-center rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-500">
              Today
            </div>
            {messages.map((message) => (
              <MessageBubble key={message.id} message={message} />
            ))}
            {phase === "thinking" ? (
              <div className="inline-flex w-fit items-center gap-3 rounded-md border border-fuchsia-400/20 bg-fuchsia-400/10 px-3 py-2 text-xs text-fuchsia-200">
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

      <div className="border-t border-white/10 p-4 max-[850px]:p-3">
        <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-slate-950/70 p-3">
          <input
            disabled
            className="min-w-0 flex-1 bg-transparent text-sm text-slate-400 outline-none placeholder:text-slate-600"
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
        <div className="mt-3 flex flex-wrap items-center justify-center gap-5 text-xs text-slate-500">
          <span className="inline-flex items-center gap-2">
            <ShieldCheck className="size-4 text-emerald-300" />
            {status === "connected" ? "Voice is ready" : "Voice is disconnected"}
          </span>
          <VoiceBars compact active={status === "connected"} />
          <span className="inline-flex items-center gap-2">
            <Volume2 className="size-4 text-cyan-300" />
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
      <div className="self-center rounded-full border border-white/10 bg-white/[0.04] px-3 py-1 text-xs text-slate-500">
        {message.text}
      </div>
    );
  }

  return (
    <div className={cn("flex gap-3", isUser ? "justify-end" : "justify-start")}>
      {!isUser ? (
        <div className="mt-6 flex size-10 shrink-0 items-center justify-center rounded-full border border-fuchsia-400/30 bg-fuchsia-400/10 text-fuchsia-200">
          <Bot className="size-5" />
        </div>
      ) : null}
      <div className={cn("max-w-[78%]", isUser && "items-end")}>
        <div className={cn("mb-1 flex items-center gap-2 text-xs text-slate-500", isUser && "justify-end")}>
          <span>{isUser ? "You" : "Customer Support Agent"}</span>
          <span>
            {message.timestamp.toLocaleTimeString([], {
              hour: "2-digit",
              minute: "2-digit",
            })}
          </span>
        </div>
        <div
          className={cn(
            "rounded-lg border px-4 py-3 text-sm leading-6 break-words [overflow-wrap:anywhere]",
            isUser
              ? "border-cyan-300/20 bg-cyan-300/10 text-cyan-50"
              : "border-white/10 bg-white/[0.06] text-slate-100",
          )}
        >
          {message.text}
        </div>
      </div>
      {isUser ? (
        <div className="mt-6 flex size-10 shrink-0 items-center justify-center rounded-full border border-cyan-300/30 bg-cyan-300/10 text-cyan-200">
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
