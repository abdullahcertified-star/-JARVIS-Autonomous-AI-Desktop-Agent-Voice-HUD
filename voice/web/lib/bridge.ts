"use client";

import { useEffect } from "react";
import { useJarvisStore, type JarvisState, type Speaker, type Tone, type TelemetryData } from "./store";

declare global {
  interface Window {
    setState: (state: string) => void;
    setLevel: (level: number) => void;
    setMuted: (muted: boolean) => void;
    addMessage: (who: string, text: string, tone: string) => void;
    clearLog: () => void;
    showConfirmation: (
      id: string,
      command: string,
      shell: string,
      riskLevel: string,
      reason: string,
      timeoutSeconds?: number
    ) => void;
    hideConfirmation: () => void;
    pywebview?: {
      api: {
        close: () => Promise<void>;
        minimize: () => Promise<void>;
        maximize: () => Promise<void>;
        toggle_fullscreen: () => Promise<boolean>;
        restore_window: () => Promise<void>;
        resize_window: (width: number, height: number) => Promise<void>;
        toggle_mute: () => Promise<void>;
        toggle_system_mute: () => Promise<any>;
        set_volume: (level: number) => Promise<any>;
        get_system_telemetry: () => Promise<TelemetryData & { success: boolean }>;
        execute_action: (payload: any) => Promise<any>;
        send_chat: (text: string) => Promise<{ success: boolean; reply: string }>;
        resolve_confirmation: (id: string, approved: boolean) => Promise<any>;
      };
    };
  }
}

/** Calls into pywebview's exposed Python API with arguments and returns a Promise,
 * with graceful HTTP fallbacks if running in an external browser. */
export async function callPywebview<T = any>(fn: string, ...args: any[]): Promise<T> {
  const invoke = async () => {
    const api = window.pywebview?.api as any;
    if (api && typeof api[fn] === "function") {
      return await api[fn](...args);
    }
    return null;
  };

  if (typeof window === "undefined") return null as any;

  if (window.pywebview?.api) {
    return await invoke();
  }

  return new Promise((resolve) => {
    let settled = false;
    const onReady = async () => {
      if (settled) return;
      settled = true;
      resolve(await invoke());
    };
    window.addEventListener("pywebviewready", onReady, { once: true });

    // Fallback if not inside pywebview after 400ms (e.g. opened in browser)
    setTimeout(async () => {
      if (settled) return;
      settled = true;
      window.removeEventListener("pywebviewready", onReady);

      if (fn === "toggle_fullscreen") {
        if (!document.fullscreenElement) {
          try {
            await document.documentElement.requestFullscreen();
            resolve(true as any);
          } catch {
            resolve(false as any);
          }
        } else {
          try {
            await document.exitFullscreen();
            resolve(false as any);
          } catch {
            resolve(false as any);
          }
        }
        return;
      }

      if (fn === "send_chat") {
        try {
          const res = await fetch("http://127.0.0.1:5000/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: args[0] }),
          });
          const data = await res.json();
          resolve(data as any);
        } catch {
          resolve(null as any);
        }
        return;
      }

      if (fn === "execute_action") {
        try {
          const res = await fetch("http://127.0.0.1:5000/execute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(args[0]),
          });
          const data = await res.json();
          resolve(data as any);
        } catch {
          resolve(null as any);
        }
        return;
      }

      resolve(null as any);
    }, 400);
  });
}

/** Wires the global functions Python calls into the Zustand store and starts telemetry polling. */
export function useBridge(): void {
  const setState = useJarvisStore((s) => s.setState);
  const setLevel = useJarvisStore((s) => s.setLevel);
  const setMuted = useJarvisStore((s) => s.setMuted);
  const addMessage = useJarvisStore((s) => s.addMessage);
  const clearLog = useJarvisStore((s) => s.clearLog);
  const setTelemetry = useJarvisStore((s) => s.setTelemetry);
  const pushCpuHistory = useJarvisStore((s) => s.pushCpuHistory);
  const setIsFullscreen = useJarvisStore((s) => s.setIsFullscreen);
  const setPendingConfirmation = useJarvisStore((s) => s.setPendingConfirmation);

  useEffect(() => {
    window.setState = (state) => setState(state as JarvisState);
    window.setLevel = (level) => setLevel(level);
    window.setMuted = (muted) => setMuted(muted);
    window.addMessage = (who, text, tone) =>
      addMessage(who as Speaker, text, (tone as Tone) || "positive");
    window.clearLog = () => clearLog();

    window.showConfirmation = (id, command, shell, riskLevel, reason, timeoutSeconds) => {
      setPendingConfirmation({
        id,
        command,
        shell,
        riskLevel: (riskLevel === "CRITICAL" ? "CRITICAL" : "HIGH"),
        reason,
        timeoutSeconds: timeoutSeconds || 20,
      });
    };
    window.hideConfirmation = () => {
      setPendingConfirmation(null);
    };

    const bootTimer = setTimeout(() => setState("idle"), 4000);

    // Global keyboard shortcuts (F11 for Fullscreen, F10/Escape to expand)
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "F11") {
        e.preventDefault();
        callPywebview<boolean>("toggle_fullscreen").then((fs) => {
          if (typeof fs === "boolean") {
            setIsFullscreen(fs);
          }
        });
      } else if (e.key === "F10" || (e.key === "Escape" && window.innerWidth < 800)) {
        e.preventDefault();
        callPywebview("restore_window").then(() => {
          callPywebview("resize_window", 1240, 820);
        });
      }
    };
    window.addEventListener("keydown", handleKeyDown);

    // Initial and periodic telemetry polling (every 1.5 seconds)
    const fetchTelemetry = async () => {
      try {
        const res = await callPywebview<any>("get_system_telemetry");
        if (res && res.success) {
          setTelemetry(res);
          if (typeof res.cpu_percent === "number") {
            pushCpuHistory(res.cpu_percent);
          }
          if (typeof res.mic_muted === "boolean") {
            setMuted(res.mic_muted);
          }
        }
      } catch {
        // Ignore if pywebview not ready yet
      }
    };

    fetchTelemetry();
    const interval = setInterval(fetchTelemetry, 3000);

    return () => {
      clearTimeout(bootTimer);
      clearInterval(interval);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [setState, setLevel, setMuted, addMessage, clearLog, setTelemetry, pushCpuHistory, setIsFullscreen]);
}
