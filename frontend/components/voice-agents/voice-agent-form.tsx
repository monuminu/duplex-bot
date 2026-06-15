"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChangeEvent, useEffect, useState } from "react";
import {
  ArrowLeft,
  Bot,
  Check,
  FileText,
  HardDriveUpload,
  Plus,
  Save,
  Trash2,
  Wrench,
} from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  createVoiceAgent,
  getVoiceAgent,
  getVoiceAgentDefaults,
  removeKnowledgeFile,
  updateVoiceAgent,
  uploadKnowledgeFiles,
  type JsonObject,
  type KnowledgeFile,
  type MCPToolPayload,
  type VoiceAgentConfigPayload,
  type VoiceAgentPayload,
} from "@/lib/voice-agents";
import { cn } from "@/lib/utils";

const steps = [
  "Name",
  "Prompt",
  "STT",
  "TTS",
  "Secrets",
  "Tools",
  "Knowledge",
  "Runtime",
] as const;

// Dotted provider-secret keys the backend accepts (write-only).
const SECRET_KEYS = [
  { key: "llm.api_key", label: "LLM API key", hint: "OpenAI / Azure OpenAI / compatible" },
  { key: "azure_speech.subscription_key", label: "Azure Speech key", hint: "STT + Azure TTS" },
  { key: "elevenlabs.api_key", label: "ElevenLabs API key", hint: "ElevenLabs TTS" },
] as const;

type FormState = VoiceAgentPayload & {
  knowledge_files: KnowledgeFile[];
};

const emptyConfig: VoiceAgentConfigPayload = {
  azure_speech: {},
  azure_stt: {},
  azure_tts: {},
  elevenlabs: {},
  llm: {},
  vad: {},
  eot: {},
  barge_in: {},
  runtime: {},
};

function initialState(): FormState {
  return {
    name: "",
    system_prompt: "",
    welcome_message: "",
    is_active: true,
    config: structuredClone(emptyConfig),
    mcp_tools: [],
    secrets: [],
    knowledge_files: [],
  };
}

export function VoiceAgentForm({ agentId }: { agentId?: string }) {
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [saving, setSaving] = useState(false);
  const [loading, setLoading] = useState(Boolean(agentId));
  const [defaults, setDefaults] = useState<VoiceAgentConfigPayload>(emptyConfig);
  const [pendingFiles, setPendingFiles] = useState<FileList | null>(null);
  const [state, setState] = useState<FormState>(() => initialState());
  // Which secrets already have a stored value (shown as "configured").
  const [secretStatus, setSecretStatus] = useState<Record<string, boolean>>({});
  // New plaintext secret values entered this session (write-only).
  const [secretInputs, setSecretInputs] = useState<Record<string, string>>({});

  const title = agentId ? "Edit Voice Agent" : "New Voice Agent";
  const canSave = state.name.trim().length > 0;

  useEffect(() => {
    async function load() {
      try {
        const defaultResponse = await getVoiceAgentDefaults();
        setDefaults(defaultResponse.config);
        if (agentId) {
          const agent = await getVoiceAgent(agentId);
          setSecretStatus(agent.secret_fields_configured || {});
          setState({
            name: agent.name,
            system_prompt: agent.system_prompt || "",
            welcome_message: agent.welcome_message || "",
            is_active: agent.is_active,
            secrets: [],
            config: {
              ...structuredClone(emptyConfig),
              ...(agent.config || {}),
            },
            mcp_tools: agent.mcp_tools.map((tool) => ({
              server_name: tool.server_name,
              server_url: tool.server_url,
              command: tool.command,
              transport: tool.transport,
              config: tool.config,
              tool_allowlist: tool.tool_allowlist,
              is_enabled: tool.is_enabled,
            })),
            knowledge_files: agent.knowledge_files,
          });
        }
      } catch (error) {
        toast.error(error instanceof Error ? error.message : "Failed to load voice agent");
      } finally {
        setLoading(false);
      }
    }
    void load();
  }, [agentId]);

  async function save() {
    if (!canSave) {
      toast.error("Agent name is required");
      return;
    }

    setSaving(true);
    try {
      const secrets = Object.entries(secretInputs)
        .filter(([, value]) => value.trim().length > 0)
        .map(([key, value]) => ({ key, value: value.trim() }));

      const payload: VoiceAgentPayload = {
        name: state.name.trim(),
        system_prompt: normalizeText(state.system_prompt),
        welcome_message: normalizeText(state.welcome_message),
        is_active: state.is_active,
        config: state.config,
        mcp_tools: state.mcp_tools.filter((tool) => tool.server_name.trim()),
        secrets,
      };
      const saved = agentId
        ? await updateVoiceAgent(agentId, payload)
        : await createVoiceAgent(payload);

      if (pendingFiles?.length) {
        await uploadKnowledgeFiles(saved.id, pendingFiles);
      }

      toast.success("Voice agent saved");
      router.push(`/voice-agents/edit?id=${saved.id}`);
      router.refresh();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to save voice agent");
    } finally {
      setSaving(false);
    }
  }

  async function deleteFile(fileId: string) {
    if (!agentId) return;
    try {
      await removeKnowledgeFile(agentId, fileId);
      setState((current) => ({
        ...current,
        knowledge_files: current.knowledge_files.filter((file) => file.id !== fileId),
      }));
      toast.success("Knowledge file removed");
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Failed to remove file");
    }
  }

  const stepContent = (() => {
    if (loading) {
      return <div className="p-8 text-sm text-slate-500">Loading voice agent…</div>;
    }
    if (step === 0) {
      return (
        <Panel title="Agent name">
          <TextInput label="Name" value={state.name} onChange={(value) => updateRoot("name", value)} />
          <Toggle
            label="Enabled"
            checked={state.is_active}
            onChange={(checked) => updateRoot("is_active", checked)}
          />
          <TextInput
            label="Welcome message"
            value={state.welcome_message || ""}
            placeholder="Use environment default when blank"
            onChange={(value) => updateRoot("welcome_message", value)}
          />
        </Panel>
      );
    }
    if (step === 1) {
      return (
        <Panel title="System prompt">
          <Textarea
            label="Prompt"
            value={state.system_prompt || ""}
            placeholder={String(defaultsText("system_prompt") || "Use environment default when blank")}
            rows={12}
            onChange={(value) => updateRoot("system_prompt", value)}
          />
        </Panel>
      );
    }
    if (step === 2) {
      return (
        <Panel title="Speech to text">
          <div className="grid gap-3 md:grid-cols-2">
            <ConfigInput section="azure_speech" fieldKey="region" label="Azure region" />
            <ConfigInput section="azure_speech" fieldKey="resource_name" label="Resource name" />
            <ConfigInput section="azure_speech" fieldKey="auth_mode" label="Auth mode" />
            <ConfigInput section="azure_stt" fieldKey="language" label="STT language" />
            <ConfigInput section="azure_stt" fieldKey="api_version" label="STT API version" />
          </div>
        </Panel>
      );
    }
    if (step === 3) {
      return (
        <Panel title="Text to speech">
          <div className="grid gap-3 md:grid-cols-2">
            <SelectInput
              label="TTS provider"
              value={String(getConfig("runtime", "tts_provider") || "")}
              onChange={(value) => updateConfig("runtime", "tts_provider", value)}
              options={[
                ["", "Use environment default"],
                ["azure", "Azure Speech"],
                ["elevenlabs", "ElevenLabs"],
              ]}
            />
            <SelectInput
              label="Streaming mode"
              value={String(getConfig("runtime", "tts_streaming_mode") || "")}
              onChange={(value) => updateConfig("runtime", "tts_streaming_mode", value)}
              options={[
                ["", "Use environment default"],
                ["incremental", "Incremental"],
                ["sentence", "Sentence"],
              ]}
            />
            <ConfigInput section="azure_tts" fieldKey="voice_name" label="Azure voice" />
            <ConfigInput section="azure_tts" fieldKey="output_format" label="Azure output format" />
            <ConfigInput section="elevenlabs" fieldKey="voice_id" label="ElevenLabs voice id" />
            <ConfigInput section="elevenlabs" fieldKey="model_id" label="ElevenLabs model" />
          </div>
        </Panel>
      );
    }
    if (step === 4) {
      return (
        <Panel title="Provider credentials">
          <p className="mb-4 text-xs leading-5 text-slate-500">
            Bring your own keys. Values are encrypted at rest and never shown
            again — leave a field blank to keep the existing key.
          </p>
          <div className="grid gap-3">
            {SECRET_KEYS.map((secret) => (
              <SecretInput
                key={secret.key}
                label={secret.label}
                hint={secret.hint}
                configured={Boolean(secretStatus[secret.key])}
                value={secretInputs[secret.key] || ""}
                onChange={(value) =>
                  setSecretInputs((current) => ({ ...current, [secret.key]: value }))
                }
              />
            ))}
          </div>
        </Panel>
      );
    }
    if (step === 5) {
      return (
        <Panel title="MCP tools">
          <p className="mb-4 text-xs leading-5 text-slate-500">
            Connect Model Context Protocol servers to give the agent live tools.
            Tools are loaded per call and run through the async function-calling
            path (they survive barge-in).
          </p>
          <div className="space-y-3">
            {state.mcp_tools.map((tool, index) => (
              <div key={index} className="rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
                <div className="mb-3 flex items-center justify-between gap-3">
                  <div className="flex items-center gap-2 text-sm font-semibold text-slate-900">
                    <Wrench className="size-4 text-[var(--accent)]" />
                    MCP server
                  </div>
                  <Button variant="ghost" size="icon" onClick={() => removeTool(index)}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
                <div className="grid gap-3 md:grid-cols-2">
                  <TextInput
                    label="Server name"
                    value={tool.server_name}
                    onChange={(value) => updateTool(index, { server_name: value })}
                  />
                  <SelectInput
                    label="Transport"
                    value={tool.transport || "streamable_http"}
                    onChange={(value) => updateTool(index, { transport: value })}
                    options={[
                      ["streamable_http", "HTTP (streamable)"],
                      ["sse", "SSE"],
                      ["stdio", "Stdio (local command)"],
                    ]}
                  />
                  <TextInput
                    label="Server URL"
                    value={tool.server_url || ""}
                    onChange={(value) => updateTool(index, { server_url: value || null })}
                  />
                  <TextInput
                    label="Command (stdio)"
                    value={tool.command || ""}
                    onChange={(value) => updateTool(index, { command: value || null })}
                  />
                  <TextInput
                    label="Tool allowlist"
                    value={(tool.tool_allowlist || []).join(", ")}
                    onChange={(value) =>
                      updateTool(index, {
                        tool_allowlist: value
                          .split(",")
                          .map((item) => item.trim())
                          .filter(Boolean),
                      })
                    }
                  />
                </div>
              </div>
            ))}
            <Button variant="secondary" onClick={addTool}>
              <Plus className="size-4" />
              Add MCP server
            </Button>
          </div>
        </Panel>
      );
    }
    if (step === 6) {
      return (
        <Panel title="Knowledge Base">
          <label className="flex min-h-36 cursor-pointer flex-col items-center justify-center rounded-xl border border-dashed border-[var(--accent)]/40 bg-[var(--accent-soft)]/60 p-6 text-center transition hover:border-[var(--accent)] hover:bg-[var(--accent-soft)]">
            <HardDriveUpload className="mb-3 size-8 text-[var(--accent)]" />
            <span className="text-sm font-semibold text-slate-900">Upload files</span>
            <span className="mt-2 text-xs text-slate-500">
              PDF, Word, Markdown, or text. Files are parsed and indexed so the
              agent can answer from them via a built-in search tool.
            </span>
            <input
              className="hidden"
              type="file"
              multiple
              accept=".pdf,.docx,.txt,.md,.csv,.json,.html"
              onChange={(event: ChangeEvent<HTMLInputElement>) => setPendingFiles(event.target.files)}
            />
          </label>
          {pendingFiles?.length ? (
            <p className="mt-3 text-xs font-medium text-[var(--accent)]">{pendingFiles.length} file(s) ready to upload on save</p>
          ) : null}
          <div className="mt-4 grid gap-2">
            {state.knowledge_files.map((file) => (
              <div
                key={file.id}
                className="flex items-center justify-between gap-3 rounded-lg border border-[var(--border)] bg-white px-3 py-2 shadow-[var(--shadow-xs)]"
              >
                <div className="flex min-w-0 items-center gap-2 text-sm text-slate-700">
                  <FileText className="size-4 shrink-0 text-[var(--accent)]" />
                  <span className="truncate">{file.file_name}</span>
                </div>
                <div className="flex shrink-0 items-center gap-2">
                  <KnowledgeStatus file={file} />
                  <Button variant="ghost" size="icon" onClick={() => void deleteFile(file.id)}>
                    <Trash2 className="size-4" />
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </Panel>
      );
    }
    return (
      <Panel title="Runtime controls">
        <div className="grid gap-3 md:grid-cols-2">
          <NumberInput section="vad" fieldKey="activation_threshold" label="VAD activation threshold" />
          <NumberInput section="vad" fieldKey="min_silence_duration_ms" label="VAD min silence ms" />
          <NumberInput section="vad" fieldKey="trailing_silence_ms" label="VAD trailing silence ms" />
          <NumberInput section="vad" fieldKey="chunk_size_ms" label="VAD chunk size ms" />
          <ToggleConfig section="eot" fieldKey="enabled" label="Semantic end-of-turn" />
          <ConfigInput section="eot" fieldKey="detector_type" label="EOT detector type" />
          <NumberInput section="eot" fieldKey="silence_threshold_ms" label="EOT silence threshold ms" />
          <NumberInput section="eot" fieldKey="semantic_check_after_ms" label="Semantic check after ms" />
          <ToggleConfig
            section="barge_in"
            fieldKey="false_positive_resume_enabled"
            label="False-positive resume"
          />
          <NumberInput
            section="barge_in"
            fieldKey="false_positive_resume_timeout_s"
            label="Resume timeout seconds"
          />
          <NumberInput section="runtime" fieldKey="tts_output_chunk_ms" label="TTS output chunk ms" />
          <NumberInput section="runtime" fieldKey="max_call_duration_s" label="Max call duration seconds" />
          <ConfigInput section="llm" fieldKey="base_url" label="LLM base URL" />
          <ConfigInput section="llm" fieldKey="model" label="LLM model" />
          <NumberInput section="llm" fieldKey="temperature" label="LLM temperature" />
          <NumberInput section="llm" fieldKey="max_tokens" label="LLM max tokens" />
        </div>
      </Panel>
    );
  })();

  function updateRoot<Key extends keyof FormState>(key: Key, value: FormState[Key]) {
    setState((current) => ({ ...current, [key]: value }));
  }

  function getConfig(section: keyof VoiceAgentConfigPayload, key: string) {
    const sectionValue = state.config[section] as JsonObject | null | undefined;
    return sectionValue?.[key] ?? "";
  }

  function updateConfig(section: keyof VoiceAgentConfigPayload, key: string, value: unknown) {
    setState((current) => ({
      ...current,
      config: {
        ...current.config,
        [section]: {
          ...((current.config[section] as JsonObject | null | undefined) || {}),
          [key]: value === "" ? null : value,
        },
      },
    }));
  }

  function defaultsText(section: keyof VoiceAgentConfigPayload | "system_prompt", key?: string) {
    if (section === "system_prompt") return "";
    const sectionValue = defaults[section] as JsonObject | null | undefined;
    return key ? sectionValue?.[key] : "";
  }

  function addTool() {
    setState((current) => ({
      ...current,
      mcp_tools: [
        ...current.mcp_tools,
        {
          server_name: "",
          server_url: "",
          command: "",
          transport: "streamable_http",
          tool_allowlist: [],
          is_enabled: true,
        },
      ],
    }));
  }

  function updateTool(index: number, patch: Partial<MCPToolPayload>) {
    setState((current) => ({
      ...current,
      mcp_tools: current.mcp_tools.map((tool, toolIndex) =>
        toolIndex === index ? { ...tool, ...patch } : tool,
      ),
    }));
  }

  function removeTool(index: number) {
    setState((current) => ({
      ...current,
      mcp_tools: current.mcp_tools.filter((_, toolIndex) => toolIndex !== index),
    }));
  }

  function ConfigInput({
    section,
    fieldKey,
    label,
  }: {
    section: keyof VoiceAgentConfigPayload;
    fieldKey: string;
    label: string;
  }) {
    return (
      <TextInput
        label={label}
        value={String(getConfig(section, fieldKey) ?? "")}
        placeholder={placeholderFor(section, fieldKey)}
        onChange={(value) => updateConfig(section, fieldKey, value)}
      />
    );
  }

  function NumberInput({
    section,
    fieldKey,
    label,
  }: {
    section: keyof VoiceAgentConfigPayload;
    fieldKey: string;
    label: string;
  }) {
    return (
      <TextInput
        label={label}
        type="number"
        value={String(getConfig(section, fieldKey) ?? "")}
        placeholder={placeholderFor(section, fieldKey)}
        onChange={(value) => updateConfig(section, fieldKey, value === "" ? "" : Number(value))}
      />
    );
  }

  function ToggleConfig({
    section,
    fieldKey,
    label,
  }: {
    section: keyof VoiceAgentConfigPayload;
    fieldKey: string;
    label: string;
  }) {
    return (
      <Toggle
        label={label}
        checked={Boolean(getConfig(section, fieldKey))}
        onChange={(checked) => updateConfig(section, fieldKey, checked)}
      />
    );
  }

  function placeholderFor(section: keyof VoiceAgentConfigPayload, key: string) {
    const value = defaultsText(section, key);
    return value === undefined || value === "" ? "Use environment default when blank" : `Env: ${String(value)}`;
  }

  return (
    <main className="min-h-screen px-4 py-6 text-slate-900 md:px-7">
      <div className="mx-auto flex max-w-7xl flex-col gap-5 rise-in">
        <header className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
          <div>
            <Link
              href="/voice-agents"
              className="mb-3 inline-flex items-center gap-2 text-sm font-medium text-[var(--accent)] transition hover:text-[var(--accent-hover)]"
            >
              <ArrowLeft className="size-4" />
              Voice Agents
            </Link>
            <h1 className="display text-[1.7rem] text-slate-900">{title}</h1>
          </div>
          <Button onClick={() => void save()} disabled={!canSave || saving}>
            <Save className="size-4" />
            {saving ? "Saving" : "Save"}
          </Button>
        </header>

        <div className="grid gap-4 lg:grid-cols-[260px_minmax(0,1fr)]">
          <aside className="console-panel h-fit rounded-2xl p-3">
            <div className="grid gap-1">
              {steps.map((item, index) => {
                const done = index < step;
                const current = step === index;
                return (
                  <button
                    key={item}
                    type="button"
                    className={cn(
                      "flex items-center gap-3 rounded-lg px-3 py-2.5 text-left text-sm font-medium text-slate-500 transition hover:bg-slate-100 hover:text-slate-900",
                      current && "bg-[var(--accent-soft)] text-[var(--accent-hover)] hover:bg-[var(--accent-soft)]",
                    )}
                    onClick={() => setStep(index)}
                  >
                    <span
                      className={cn(
                        "flex size-6 items-center justify-center rounded-full border text-xs font-semibold transition",
                        done
                          ? "border-transparent bg-[var(--accent)] text-white"
                          : current
                            ? "border-[var(--accent)] text-[var(--accent)]"
                            : "border-[var(--border-strong)] text-slate-400",
                      )}
                    >
                      {done ? <Check className="size-3" /> : index + 1}
                    </span>
                    {item}
                  </button>
                );
              })}
            </div>
          </aside>

          <section className="console-panel min-h-[560px] rounded-2xl p-4 md:p-6">
            <div className="mb-5 flex items-center gap-3 border-b border-[var(--border)] pb-5">
              <div className="flex size-11 items-center justify-center rounded-xl bg-[var(--accent-soft)] text-[var(--accent)]">
                <Bot className="size-5" />
              </div>
              <div>
                <h2 className="text-base font-semibold text-slate-900">{steps[step]}</h2>
                <p className="mt-0.5 text-xs text-slate-500">
                  Blank configuration fields inherit the current environment value.
                </p>
              </div>
            </div>
            {stepContent}
            <div className="mt-6 flex items-center justify-between border-t border-[var(--border)] pt-4">
              <Button
                variant="secondary"
                disabled={step === 0}
                onClick={() => setStep((current) => Math.max(0, current - 1))}
              >
                Back
              </Button>
              {step === steps.length - 1 ? (
                <Button onClick={() => void save()} disabled={!canSave || saving}>
                  <Save className="size-4" />
                  {saving ? "Saving" : "Save"}
                </Button>
              ) : (
                <Button onClick={() => setStep((current) => Math.min(steps.length - 1, current + 1))}>
                  Next
                </Button>
              )}
            </div>
          </section>
        </div>
      </div>
    </main>
  );
}

function normalizeText(value: string | null | undefined) {
  const trimmed = value?.trim();
  return trimmed ? trimmed : null;
}

function Panel({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="mb-4 text-sm font-semibold text-slate-900">{title}</h3>
      {children}
    </div>
  );
}

function TextInput({
  label,
  value,
  onChange,
  placeholder,
  type = "text",
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  type?: string;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-slate-600">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-lg border border-[var(--border-strong)] bg-white px-3 text-sm text-slate-900 shadow-[var(--shadow-xs)] outline-none transition placeholder:text-slate-400 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-ring)]"
      />
    </label>
  );
}

function Textarea({
  label,
  value,
  onChange,
  placeholder,
  rows,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  placeholder?: string;
  rows?: number;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-slate-600">{label}</span>
      <textarea
        value={value}
        rows={rows}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="w-full resize-y rounded-lg border border-[var(--border-strong)] bg-white px-3 py-3 text-sm leading-6 text-slate-900 shadow-[var(--shadow-xs)] outline-none transition placeholder:text-slate-400 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-ring)]"
      />
    </label>
  );
}

function SelectInput({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: string;
  options: Array<[string, string]>;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-xs font-medium text-slate-600">{label}</span>
      <select
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-lg border border-[var(--border-strong)] bg-white px-3 text-sm text-slate-900 shadow-[var(--shadow-xs)] outline-none transition focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-ring)]"
      >
        {options.map(([optionValue, labelText]) => (
          <option key={optionValue} value={optionValue}>
            {labelText}
          </option>
        ))}
      </select>
    </label>
  );
}

function Toggle({
  label,
  checked,
  onChange,
}: {
  label: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  return (
    <label className="flex h-10 items-center justify-between gap-3 rounded-lg border border-[var(--border-strong)] bg-white px-3 text-sm font-medium text-slate-700 shadow-[var(--shadow-xs)]">
      <span>{label}</span>
      <input
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
        className="size-4 accent-[var(--accent)]"
      />
    </label>
  );
}

function SecretInput({
  label,
  hint,
  configured,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  configured: boolean;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <label className="block rounded-xl border border-[var(--border)] bg-[var(--surface-muted)] p-3">
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-slate-900">{label}</span>
        <span
          className={cn(
            "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
            configured
              ? "bg-[var(--success-soft)] text-[var(--success)]"
              : "bg-slate-100 text-slate-500",
          )}
        >
          {configured ? "Configured" : "Not set"}
        </span>
      </div>
      <input
        type="password"
        value={value}
        autoComplete="new-password"
        placeholder={configured ? "•••••••• (leave blank to keep)" : "Paste key"}
        onChange={(event) => onChange(event.target.value)}
        className="h-10 w-full rounded-lg border border-[var(--border-strong)] bg-white px-3 text-sm text-slate-900 shadow-[var(--shadow-xs)] outline-none transition placeholder:text-slate-400 focus:border-[var(--accent)] focus:ring-2 focus:ring-[var(--accent-ring)]"
      />
      <span className="mt-2 block text-[11px] text-slate-500">{hint}</span>
    </label>
  );
}

function KnowledgeStatus({ file }: { file: KnowledgeFile }) {
  const map: Record<string, { label: string; className: string }> = {
    ready: { label: `${file.chunk_count} chunks`, className: "bg-[var(--success-soft)] text-[var(--success)]" },
    processing: { label: "Processing", className: "bg-[var(--warning-soft)] text-[var(--warning)]" },
    empty: { label: "No text found", className: "bg-slate-100 text-slate-500" },
    error: { label: "Failed", className: "bg-[var(--danger-soft)] text-[var(--danger)]" },
    stored: { label: "Stored", className: "bg-slate-100 text-slate-500" },
  };
  const entry = map[file.status] || map.stored;
  return (
    <span
      title={file.error || undefined}
      className={cn(
        "rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide",
        entry.className,
      )}
    >
      {entry.label}
    </span>
  );
}
