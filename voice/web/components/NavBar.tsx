"use client";

import { useState, useEffect } from "react";
import { useJarvisStore, type View } from "@/lib/store";
import { callPywebview } from "@/lib/bridge";
import styles from "./NavBar.module.css";

const ITEMS: { key: View; label: string; icon: string }[] = [
  { key: "dashboard", label: "DASHBOARD", icon: "▦" },
  { key: "home", label: "CORE ORB", icon: "⌂" },
  { key: "chat", label: "TERMINAL", icon: "💬" },
];

export default function NavBar() {
  const view = useJarvisStore((s) => s.view);
  const state = useJarvisStore((s) => s.state);
  const muted = useJarvisStore((s) => s.muted);
  const setView = useJarvisStore((s) => s.setView);
  const isFullscreen = useJarvisStore((s) => s.isFullscreen);
  const setIsFullscreen = useJarvisStore((s) => s.setIsFullscreen);
  const [timeStr, setTimeStr] = useState("");
  const [isCompact, setIsCompact] = useState(false);

  useEffect(() => {
    const updateTime = () => {
      const now = new Date();
      setTimeStr(now.toTimeString().split(" ")[0]);
    };
    updateTime();
    const interval = setInterval(updateTime, 1000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    const handleResize = () => {
      setIsCompact(window.innerWidth < 760);
    };
    handleResize();
    window.addEventListener("resize", handleResize);
    return () => window.removeEventListener("resize", handleResize);
  }, []);

  const handleToggleFullscreen = async () => {
    const fs = await callPywebview<boolean>("toggle_fullscreen");
    if (typeof fs === "boolean") {
      setIsFullscreen(fs);
    } else {
      setIsFullscreen(!isFullscreen);
    }
  };

  const handleMaximize = async () => {
    await callPywebview("maximize");
  };

  const handleToggleSize = async () => {
    if (window.innerWidth < 800) {
      await callPywebview("restore_window");
      await callPywebview("resize_window", 1240, 820);
      setIsCompact(false);
    } else {
      await callPywebview("resize_window", 460, 720);
      setIsCompact(true);
    }
  };

  return (
    <header className={styles.bar}>
      <div
        className={styles.drag}
        onDoubleClick={handleToggleSize}
        title="Double-click to toggle Compact Float / Expanded HUD"
      />

      <div className={styles.brand}>
        <span className={`${styles.statusDot} ${styles[state] || styles.idle}`} />
        <span className={styles.brandText}>J.A.R.V.I.S.</span>
        <span className={styles.stateBadge}>{muted ? "MUTED" : state.toUpperCase()}</span>
        {timeStr && <span className={styles.clockBadge}>{timeStr}</span>}
      </div>

      <nav className={styles.nav}>
        {ITEMS.map((item) => (
          <button
            key={item.key}
            className={`${styles.navBtn} ${view === item.key ? styles.active : ""}`}
            title={item.label}
            onClick={() => setView(item.key)}
          >
            <span className={styles.icon}>{item.icon}</span>
            <span className={styles.navLabel}>{item.label}</span>
          </button>
        ))}
      </nav>

      <div className={styles.controls}>
        <button
          className={`${styles.iconBtn} ${muted ? styles.muted : ""}`}
          title={muted ? "Unmute Microphone" : "Mute Microphone"}
          onClick={() => callPywebview("toggle_mute")}
        >
          {muted ? "🔇" : "🎙"}
        </button>

        <button
          className={`${styles.iconBtn} ${isCompact ? styles.expandBtnHighlight : ""}`}
          title={isCompact ? "Expand to Full Window (1240x820)" : "Compact Float Mode (460x720)"}
          onClick={handleToggleSize}
        >
          {isCompact ? "⤢" : "⤡"}
        </button>

        <button
          className={`${styles.iconBtn} ${isFullscreen ? styles.activeControl : ""}`}
          title="Toggle Fullscreen HUD (F11)"
          onClick={handleToggleFullscreen}
        >
          {isFullscreen ? "⊡" : "⛶"}
        </button>

        <button
          className={styles.iconBtn}
          title="Maximize Window"
          onClick={handleMaximize}
        >
          🗖
        </button>

        <button
          className={styles.iconBtn}
          title="Minimize to Taskbar"
          onClick={() => callPywebview("minimize")}
        >
          —
        </button>

        <button
          className={`${styles.iconBtn} ${styles.closeBtn}`}
          title="Close JARVIS"
          onClick={() => callPywebview("close")}
        >
          &times;
        </button>
      </div>
    </header>
  );
}
