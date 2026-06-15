"use client";

import { apiBaseUrl, apiFetch, getToken } from "@/lib/api";

export type JsonObject = Record<string, unknown>;

export type VoiceAgentConfigPayload = {
  azure_speech?: JsonObject | null;
  azure_stt?: JsonObject | null;
  azure_tts?: JsonObject | null;
  elevenlabs?: JsonObject | null;
  llm?: JsonObject | null;
  vad?: JsonObject | null;
  eot?: JsonObject | null;
  barge_in?: JsonObject | null;
  runtime?: JsonObject | null;
};

export type MCPToolPayload = {
  server_name: string;
  server_url?: string | null;
  command?: string | null;
  transport?: string;
  config?: JsonObject | null;
  tool_allowlist?: string[] | null;
  is_enabled: boolean;
};

export type AgentSecretPayload = {
  key: string;
  value?: string | null;
};

export type KnowledgeFile = {
  id: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
  status: string;
  chunk_count: number;
  error: string | null;
  created_at: string;
};

export type MCPTool = MCPToolPayload & {
  id: string;
  created_at: string;
  updated_at: string;
};

export type VoiceAgent = {
  id: string;
  name: string;
  system_prompt: string | null;
  welcome_message: string | null;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  config: VoiceAgentConfigPayload | null;
  mcp_tools: MCPTool[];
  knowledge_files: KnowledgeFile[];
  secret_fields_configured: Record<string, boolean>;
};

export type VoiceAgentListItem = {
  id: string;
  name: string;
  is_active: boolean;
  updated_at: string;
  tts_provider: string | null;
  llm_model: string | null;
  mcp_tool_count: number;
  knowledge_file_count: number;
};

export type VoiceAgentDefaults = {
  config: VoiceAgentConfigPayload;
  secret_fields_configured: Record<string, boolean>;
};

export type VoiceAgentPayload = {
  name: string;
  system_prompt?: string | null;
  welcome_message?: string | null;
  is_active: boolean;
  config: VoiceAgentConfigPayload;
  mcp_tools: MCPToolPayload[];
  secrets: AgentSecretPayload[];
};

export function listVoiceAgents() {
  return apiFetch<VoiceAgentListItem[]>("/api/voice-agents");
}

export function getVoiceAgentDefaults() {
  return apiFetch<VoiceAgentDefaults>("/api/voice-agents/defaults");
}

export function getVoiceAgent(agentId: string) {
  return apiFetch<VoiceAgent>(`/api/voice-agents/${agentId}`);
}

export function createVoiceAgent(payload: VoiceAgentPayload) {
  return apiFetch<VoiceAgent>("/api/voice-agents", {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export function updateVoiceAgent(agentId: string, payload: VoiceAgentPayload) {
  return apiFetch<VoiceAgent>(`/api/voice-agents/${agentId}`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export function deleteVoiceAgent(agentId: string) {
  return apiFetch<void>(`/api/voice-agents/${agentId}`, { method: "DELETE" });
}

export async function uploadKnowledgeFiles(agentId: string, files: FileList | File[]) {
  const formData = new FormData();
  Array.from(files).forEach((file) => formData.append("files", file));
  const token = getToken();
  const response = await fetch(
    `${apiBaseUrl()}/api/voice-agents/${agentId}/knowledge-files`,
    {
      method: "POST",
      body: formData,
      headers: token ? { Authorization: `Bearer ${token}` } : undefined,
    },
  );
  if (!response.ok) {
    const message = await response.text();
    throw new Error(message || `Upload failed: ${response.status}`);
  }
  return (await response.json()) as KnowledgeFile[];
}

export function removeKnowledgeFile(agentId: string, fileId: string) {
  return apiFetch<void>(`/api/voice-agents/${agentId}/knowledge-files/${fileId}`, {
    method: "DELETE",
  });
}
