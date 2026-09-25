"use client";

import { useState, useEffect } from "react";
import dynamic from "next/dynamic";
import { useBridge, callPywebview } from "@/lib/bridge";
import { useJarvisStore } from "@/lib/store";
import BootScreen from "@/components/BootScreen";
import NavBar from "@/components/NavBar";
import ChatPanel from "@/components/ChatPanel";
import Dashboard from "@/components/Dashboard";
import styles from "./page.module.css";

// Three.js/WebGL needs the real browser environment -- never render it
// during the static export's build-time prerender.
const ParticleSphere = dynamic(() => import("@/components/ParticleSphere"), { ssr: false });

const STATUS_TEXT: Record<string, string> = {
  idle: 'Say "Hey Jarvis"',
  listening: "Listening...",
  thinking: "Thinking...",
  speaking: "Speaking...",
  error: "Something went wrong",
};

export default function Page() {
  useBridge();
  const state = useJarvisStore((s) => s.state);
  const muted = useJarvisStore((s) => s.muted);
  const view = useJarvisStore((s) => s.view);
  const [isCompact, setIsCompact] = useState(false);

  useEffect(() => {
    const handleResize = () => {
      setIsCompact(window.innerWidth < 760);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const handleExpand = async () => {
    await callPywebview("restore_window");
    await callPywebview("resize_window", 1240, 820);
    setIsCompact(false);
  };

  if (state === "booting") {
    return <BootScreen />;
  }

  return (
    <div className={styles.app}>
      <NavBar />
      <div className={styles.body}>
        {view === "home" && (
          <div className={styles.home}>
            <div className={styles.sphereStage}>
              <ParticleSphere />
            </div>
            <div className={styles.status}>{muted ? "Muted" : STATUS_TEXT[state] ?? state}</div>
          </div>
        )}
        {view === "chat" && <ChatPanel />}
        {view === "dashboard" && <Dashboard />}

        {isCompact && (
          <button
            className={styles.floatExpandPill}
            onClick={handleExpand}
            title="Expand to Full HUD Window (1240x820)"
          >
            <span className={styles.expandIcon}>⤢</span>
            <span>EXPAND HUD</span>
          </button>
        )}
      </div>
    </div>
  );
}
