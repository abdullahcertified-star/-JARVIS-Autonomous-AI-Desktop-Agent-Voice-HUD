import { create } from "zustand";

export type JarvisState =
  | "booting"
  | "idle"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export type Speaker = "you" | "jarvis";
export type Tone = "positive" | "negative";

export interface ChatMessage {
  id: number;
  who: Speaker;
  text: string;
  tone: Tone;
  timestamp: string;
}

export type View = "dashboard" | "home" | "chat";

export interface TelemetryData {
  cpu_percent: number;
  memory_percent: number;
  memory_used_gb?: number;
  memory_total_gb?: number;
  disk_percent?: number;
  disk_free_gb?: number;
  disk_total_gb?: number;
  battery_percent: number | null;
  uptime_seconds: number;
  volume: number;
  system_muted?: boolean;
  mic_muted?: boolean;
  process_count?: number;
  ip_address?: string;
  active_window?: string;
  agent_model: string;
  tts_voice: string;
  tts_pitch: string;
  whisper_model?: string;
}

interface JarvisStore {
  state: JarvisState;
  level: number;
  muted: boolean;
  messages: ChatMessage[];
  view: View;
  isFullscreen: boolean;
  telemetry: TelemetryData | null;
  cpuHistory: number[];
  toast: string | null;

  setState: (state: JarvisState) => void;
  setLevel: (level: number) => void;
  setMuted: (muted: boolean) => void;
  addMessage: (who: Speaker, text: string, tone?: Tone) => void;
  clearLog: () => void;
  setView: (view: View) => void;
  setIsFullscreen: (isFullscreen: boolean) => void;
  setTelemetry: (telemetry: TelemetryData) => void;
  pushCpuHistory: (val: number) => void;
  setToast: (toast: string | null) => void;
}

let nextMessageId = 1;

function getNowTimeStr(): string {
  const d = new Date();
  return d.toTimeString().split(" ")[0];
}

export const useJarvisStore = create<JarvisStore>((set) => ({
  state: "booting",
  level: 0,
  muted: false,
  messages: [],
  view: "home",
  isFullscreen: false,
  telemetry: null,
  cpuHistory: [12, 18, 15, 22, 19, 28, 24, 20, 25, 30],
  toast: null,

  setState: (state) => set({ state }),
  setLevel: (level) => set({ level }),
  setMuted: (muted) => set({ muted }),
  addMessage: (who, text, tone = "positive") =>
    set((s) => ({
      messages: [
        ...s.messages,
        { id: nextMessageId++, who, text, tone, timestamp: getNowTimeStr() },
      ],
    })),
  clearLog: () => set({ messages: [] }),
  setView: (view) => set({ view }),
  setIsFullscreen: (isFullscreen) => set({ isFullscreen }),
  setTelemetry: (telemetry) => set({ telemetry }),
  pushCpuHistory: (val) =>
    set((s) => ({
      cpuHistory: [...s.cpuHistory.slice(-14), Math.max(0, Math.min(100, Math.round(val)))],
    })),
  setToast: (toast) => set({ toast }),
}));
