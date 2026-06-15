"use client";

import { Suspense } from "react";
import { useSearchParams } from "next/navigation";

import { VoiceAgentForm } from "@/components/voice-agents/voice-agent-form";

function EditForm() {
  const params = useSearchParams();
  const agentId = params.get("id") || undefined;
  return <VoiceAgentForm agentId={agentId} />;
}

export default function EditVoiceAgentPage() {
  // useSearchParams must be wrapped in Suspense for the static export build.
  return (
    <Suspense fallback={<div className="p-8 text-sm text-slate-400">Loading…</div>}>
      <EditForm />
    </Suspense>
  );
}
