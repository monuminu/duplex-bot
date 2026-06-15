"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { Bot, Database, FileText, Plus, RefreshCcw, Trash2, Wrench } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  deleteVoiceAgent,
  listVoiceAgents,
  type VoiceAgentListItem,
} from "@/lib/voice-agents";

export function VoiceAgentList() {
  const [agents, setAgents] = useState<VoiceAgentListItem[]>([]);
  const [loading, setLoading] = useState(true);

  async function loadAgents() {
    setLoading(true);
    try {
      setAgents(await listVoiceAgents());
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to load voice agents");
    } finally {
      setLoading(false);
    }
  }

  async function removeAgent(agentId: string) {
    try {
      await deleteVoiceAgent(agentId);
      setAgents((current) => current.filter((agent) => agent.id !== agentId));
      toast.success("Voice agent deleted");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to delete voice agent");
    }
  }

  useEffect(() => {
    const timer = window.setTimeout(() => {
      void loadAgents();
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  return (
    <main className="min-h-screen px-4 py-6 text-slate-900 md:px-7">
      <div className="mx-auto flex max-w-7xl flex-col gap-5 rise-in">
        <header className="flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
          <div>
            <h1 className="display text-[1.7rem] text-slate-900">Voice Agents</h1>
            <p className="mt-1.5 max-w-3xl text-sm leading-6 text-slate-500">
              Create reusable voice agents with their own prompt, providers, turn detection,
              tools, and knowledge files.
            </p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="secondary" onClick={loadAgents} disabled={loading}>
              <RefreshCcw className="size-4" />
              Refresh
            </Button>
            <Button asChild>
              <Link href="/voice-agents/new">
                <Plus className="size-4" />
                New agent
              </Link>
            </Button>
          </div>
        </header>

        <section className="console-panel rounded-2xl p-3 md:p-4">
          {loading ? (
            <div className="p-8 text-sm text-slate-500">Loading voice agents…</div>
          ) : agents.length === 0 ? (
            <div className="flex min-h-80 flex-col items-center justify-center text-center">
              <div className="mb-5 flex size-16 items-center justify-center rounded-2xl bg-[var(--accent-soft)] text-[var(--accent)]">
                <Bot className="size-7" />
              </div>
              <h2 className="text-lg font-semibold text-slate-900">No voice agents yet</h2>
              <p className="mt-2.5 max-w-md text-sm leading-6 text-slate-500">
                Add an agent to save configuration in Postgres and use it from the playground.
              </p>
              <Button asChild className="mt-6">
                <Link href="/voice-agents/new">
                  <Plus className="size-4" />
                  New agent
                </Link>
              </Button>
            </div>
          ) : (
            <div className="grid gap-2.5">
              {agents.map((agent) => (
                <article
                  key={agent.id}
                  className="group rounded-xl border border-[var(--border)] bg-white p-4 shadow-[var(--shadow-xs)] transition hover:border-[var(--border-strong)] hover:shadow-[var(--shadow-md)]"
                >
                  <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
                    <Link href={`/voice-agents/edit?id=${agent.id}`} className="min-w-0 flex-1">
                      <div className="flex items-center gap-3">
                        <div className="flex size-11 shrink-0 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
                          <Bot className="size-5" />
                        </div>
                        <div className="min-w-0">
                          <h2 className="truncate text-base font-semibold text-slate-900 group-hover:text-[var(--accent-hover)]">
                            {agent.name}
                          </h2>
                          <p className="mono mt-0.5 text-xs text-slate-400">
                            Updated {new Date(agent.updated_at).toLocaleString()}
                          </p>
                        </div>
                      </div>
                    </Link>
                    <div className="grid gap-2 text-xs text-slate-600 sm:grid-cols-4 lg:w-[560px]">
                      <Metric icon={Database} label={agent.tts_provider || "env TTS"} />
                      <Metric icon={Bot} label={agent.llm_model || "env model"} />
                      <Metric icon={Wrench} label={`${agent.mcp_tool_count} MCP`} />
                      <Metric icon={FileText} label={`${agent.knowledge_file_count} files`} />
                    </div>
                    <Button
                      variant="ghost"
                      size="icon"
                      aria-label={`Delete ${agent.name}`}
                      onClick={() => void removeAgent(agent.id)}
                      className="hover:bg-[var(--danger-soft)] hover:text-[var(--danger)]"
                    >
                      <Trash2 className="size-4" />
                    </Button>
                  </div>
                </article>
              ))}
            </div>
          )}
        </section>
      </div>
    </main>
  );
}

function Metric({ icon: Icon, label }: { icon: typeof Bot; label: string }) {
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-lg border border-[var(--border)] bg-[var(--surface-muted)] px-3 py-2">
      <Icon className="size-4 shrink-0 text-[var(--accent)]" />
      <span className="truncate">{label}</span>
    </div>
  );
}
