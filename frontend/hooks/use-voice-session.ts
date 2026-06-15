"use client";

import { startTransition, useEffect, useRef, useState } from "react";
import { toast } from "sonner";

import { getToken } from "@/lib/api";

const SAMPLE_RATE = 16000;
const JITTER_BUFFER_SIZE = 1;
export const DEFAULT_MICROPHONE_VALUE = "default";

/**
 * Resolve the browser-adapter WebSocket URL.
 *
 * In the single-container deployment the SPA is served from the same origin as
 * the backend, so we derive ws(s)://<host>/ws/browser automatically — no env
 * var needed. NEXT_PUBLIC_BACKEND_WS_URL overrides this for split local dev.
 */
function defaultWsUrl(): string {
  if (typeof window === "undefined") return "ws://localhost:8000/ws/browser";
  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${protocol}//${window.location.host}/ws/browser`;
}

export type VoicePhase = "idle" | "listening" | "thinking" | "speaking";
export type ConnectionStatus = "disconnected" | "connecting" | "connected" | "error";

export type TranscriptMessage = {
  id: string;
  role: "user" | "agent" | "system";
  text: string;
  timestamp: Date;
};

type BrowserControlMessage =
  | { type: "clear" }
  | { type: "transcript"; text: string }
  | { type: "agent_text"; text: string }
  | { type: string; text?: string };

type AudioDevice = {
  deviceId: string;
  label: string;
};

export function useVoiceSession({ agentId = "" }: { agentId?: string } = {}) {
  const [status, setStatus] = useState<ConnectionStatus>("disconnected");
  const [phase, setPhase] = useState<VoicePhase>("idle");
  const [messages, setMessages] = useState<TranscriptMessage[]>([]);
  const [devices, setDevices] = useState<AudioDevice[]>([]);
  const [selectedDeviceId, setSelectedDeviceId] = useState("");
  const [durationSeconds, setDurationSeconds] = useState(0);
  const [latencyMs, setLatencyMs] = useState<number | null>(null);
  const [error, setError] = useState("");

  const wsRef = useRef<WebSocket | null>(null);
  const audioContextRef = useRef<AudioContext | null>(null);
  const mediaStreamRef = useRef<MediaStream | null>(null);
  const processorRef = useRef<ScriptProcessorNode | null>(null);
  const playbackQueueRef = useRef<ArrayBuffer[]>([]);
  const scheduledSourcesRef = useRef<AudioBufferSourceNode[]>([]);
  const nextPlayTimeRef = useRef(0);
  const isBufferingRef = useRef(true);
  const firstAudioReceivedAtRef = useRef(0);
  const durationTimerRef = useRef<number | null>(null);

  function addMessage(role: TranscriptMessage["role"], text: string) {
    setMessages((current) => [
      ...current,
      {
        id: crypto.randomUUID(),
        role,
        text,
        timestamp: new Date(),
      },
    ]);
  }

  function resetPlayback() {
    playbackQueueRef.current = [];
    nextPlayTimeRef.current = 0;
    isBufferingRef.current = true;
    firstAudioReceivedAtRef.current = 0;

    for (const source of scheduledSourcesRef.current) {
      source.onended = null;
      try {
        source.stop();
      } catch {
        // Source may already be stopped.
      }
    }
    scheduledSourcesRef.current = [];
  }

  function cleanup() {
    if (processorRef.current) {
      processorRef.current.disconnect();
      processorRef.current = null;
    }

    if (mediaStreamRef.current) {
      for (const track of mediaStreamRef.current.getTracks()) {
        track.stop();
      }
      mediaStreamRef.current = null;
    }

    if (audioContextRef.current) {
      void audioContextRef.current.close();
      audioContextRef.current = null;
    }

    if (durationTimerRef.current) {
      window.clearInterval(durationTimerRef.current);
      durationTimerRef.current = null;
    }

    wsRef.current = null;
    resetPlayback();
    setStatus("disconnected");
    setPhase("idle");
  }

  async function enumerateDevices() {
    if (!navigator.mediaDevices?.enumerateDevices) {
      setDevices([]);
      return;
    }

    const allDevices = await navigator.mediaDevices.enumerateDevices();
    const mics = allDevices
      .filter((device) => device.kind === "audioinput" && device.deviceId)
      .map((device, index) => ({
        deviceId: device.deviceId,
        label: device.label || `Microphone ${index + 1}`,
      }));

    setDevices(mics);
  }

  async function refreshDevicesWithPermission() {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      stream.getTracks().forEach((track) => track.stop());
      await enumerateDevices();
    } catch {
      await enumerateDevices();
    }
  }

  function decodeChunk(arrayBuffer: ArrayBuffer) {
    const audioContext = audioContextRef.current;
    if (!audioContext) return null;

    const int16 = new Int16Array(arrayBuffer);
    const float32 = new Float32Array(int16.length);
    for (let i = 0; i < int16.length; i += 1) {
      float32[i] = int16[i] / 0x8000;
    }

    const buffer = audioContext.createBuffer(1, float32.length, SAMPLE_RATE);
    buffer.getChannelData(0).set(float32);
    return buffer;
  }

  function drainQueue() {
    const audioContext = audioContextRef.current;
    if (!audioContext || playbackQueueRef.current.length === 0) return;

    const now = audioContext.currentTime;
    if (nextPlayTimeRef.current <= now) {
      nextPlayTimeRef.current = now + 0.01;
      if (firstAudioReceivedAtRef.current > 0) {
        setLatencyMs(Math.round(performance.now() - firstAudioReceivedAtRef.current + 10));
        firstAudioReceivedAtRef.current = 0;
      }
    }

    while (playbackQueueRef.current.length > 0) {
      const data = playbackQueueRef.current.shift();
      if (!data) continue;

      const buffer = decodeChunk(data);
      if (!buffer) continue;

      const source = audioContext.createBufferSource();
      source.buffer = buffer;
      source.connect(audioContext.destination);
      source.start(nextPlayTimeRef.current);
      nextPlayTimeRef.current += buffer.duration;
      scheduledSourcesRef.current.push(source);

      source.onended = () => {
        scheduledSourcesRef.current = scheduledSourcesRef.current.filter((item) => item !== source);
        if (scheduledSourcesRef.current.length === 0 && playbackQueueRef.current.length === 0) {
          setPhase("listening");
        }
      };
    }
  }

  function handleAudioResponse(arrayBuffer: ArrayBuffer) {
    setPhase("speaking");
    if (playbackQueueRef.current.length === 0 && scheduledSourcesRef.current.length === 0) {
      firstAudioReceivedAtRef.current = performance.now();
    }

    playbackQueueRef.current.push(arrayBuffer);
    if (isBufferingRef.current) {
      if (playbackQueueRef.current.length >= JITTER_BUFFER_SIZE) {
        isBufferingRef.current = false;
        drainQueue();
      }
      return;
    }

    drainQueue();
  }

  function handleControlMessage(message: BrowserControlMessage) {
    if (message.type === "clear") {
      resetPlayback();
      setPhase("listening");
      return;
    }

    if (message.type === "transcript" && message.text) {
      setPhase("thinking");
      addMessage("user", message.text);
      return;
    }

    if (message.type === "agent_text" && message.text) {
      addMessage("agent", message.text);
    }
  }

  function handleSocketMessage(event: MessageEvent) {
    if (event.data instanceof ArrayBuffer) {
      handleAudioResponse(event.data);
      return;
    }

    try {
      handleControlMessage(JSON.parse(event.data) as BrowserControlMessage);
    } catch {
      console.warn("Invalid control message", event.data);
    }
  }

  async function connect() {
    if (status === "connecting" || status === "connected") return;

    setStatus("connecting");
    setError("");
    setLatencyMs(null);

    const baseUrl =
      process.env.NEXT_PUBLIC_BACKEND_WS_URL || defaultWsUrl();
    const params = new URLSearchParams();
    if (agentId) params.set("agent_id", agentId);
    const token = getToken();
    if (token) params.set("token", token);
    const query = params.toString();
    const url = query ? `${baseUrl}${baseUrl.includes("?") ? "&" : "?"}${query}` : baseUrl;

    try {
      const audioConstraints: MediaTrackConstraints = {
        sampleRate: SAMPLE_RATE,
        channelCount: 1,
        echoCancellation: true,
        noiseSuppression: true,
      };

      if (selectedDeviceId && selectedDeviceId !== DEFAULT_MICROPHONE_VALUE) {
        audioConstraints.deviceId = { exact: selectedDeviceId };
      }

      const mediaStream = await navigator.mediaDevices.getUserMedia({ audio: audioConstraints });
      mediaStreamRef.current = mediaStream;

      const audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
      audioContextRef.current = audioContext;

      const source = audioContext.createMediaStreamSource(mediaStream);
      const processor = audioContext.createScriptProcessor(1024, 1, 1);
      processorRef.current = processor;

      const ws = new WebSocket(url);
      ws.binaryType = "arraybuffer";
      wsRef.current = ws;

      ws.onopen = () => {
        startTransition(() => {
          setStatus("connected");
          setPhase("listening");
          setDurationSeconds(0);
        });

        ws.send(JSON.stringify({ type: "start", session_id: crypto.randomUUID() }));
        addMessage("system", "Voice session connected.");

        source.connect(processor);
        processor.connect(audioContext.destination);

        processor.onaudioprocess = (event) => {
          if (ws.readyState !== WebSocket.OPEN) return;

          const inputData = event.inputBuffer.getChannelData(0);
          const pcm16 = new Int16Array(inputData.length);
          for (let i = 0; i < inputData.length; i += 1) {
            const sample = Math.max(-1, Math.min(1, inputData[i]));
            pcm16[i] = sample < 0 ? sample * 0x8000 : sample * 0x7fff;
          }
          ws.send(pcm16.buffer);
        };

        durationTimerRef.current = window.setInterval(() => {
          setDurationSeconds((current) => current + 1);
        }, 1000);

        void enumerateDevices();
      };

      ws.onmessage = (event) => {
        handleSocketMessage(event);
      };
      ws.onerror = () => {
        setError("Unable to connect to the voice backend.");
        setStatus("error");
        toast.error("Voice backend connection failed");
      };
      ws.onclose = () => {
        cleanup();
      };
    } catch (connectError) {
      const message = connectError instanceof Error ? connectError.message : "Connection failed";
      setError(message);
      setStatus("error");
      setPhase("idle");
      toast.error(message);
      cleanup();
    }
  }

  function disconnect() {
    if (wsRef.current?.readyState === WebSocket.OPEN) {
      wsRef.current.send(JSON.stringify({ type: "stop" }));
      wsRef.current.close();
    }

    addMessage("system", "Voice session disconnected.");
    cleanup();
  }

  function clearChat() {
    setMessages([]);
  }

  function newSession() {
    if (status === "connected" || status === "connecting") {
      disconnect();
    }
    setMessages([]);
    setLatencyMs(null);
    setDurationSeconds(0);
  }

  useEffect(() => {
    const initialDeviceRead = window.setTimeout(() => {
      void enumerateDevices();
    }, 0);

    function handleDeviceChange() {
      void enumerateDevices();
    }

    navigator.mediaDevices?.addEventListener("devicechange", handleDeviceChange);
    return () => {
      window.clearTimeout(initialDeviceRead);
      navigator.mediaDevices?.removeEventListener("devicechange", handleDeviceChange);
      cleanup();
    };
    // Device subscription should be created once for the session hook lifecycle.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return {
    status,
    phase,
    messages,
    devices,
    selectedDeviceId,
    durationSeconds,
    latencyMs,
    error,
    setSelectedDeviceId,
    connect,
    disconnect,
    clearChat,
    newSession,
    refreshDevicesWithPermission,
  };
}
