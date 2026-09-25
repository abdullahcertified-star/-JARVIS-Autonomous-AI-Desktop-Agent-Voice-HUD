"use client";

import React, { useState, useRef, useEffect } from "react";
import { useJarvisStore, type TelemetryData } from "@/lib/store";
import { callPywebview } from "@/lib/bridge";
import styles from "./Dashboard.module.css";

function formatUptime(seconds?: number): string {
  if (!seconds || seconds <= 0) return "00h 00m";
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  return `${h.toString().padStart(2, "0")}h ${m.toString().padStart(2, "0")}m ${s.toString().padStart(2, "0")}s`;
}

// Circular progress ring helper
function ProgressRing({
  value,
  size = 94,
  strokeWidth = 7,
  color = "#00f0ff",
  trackColor = "rgba(0, 240, 255, 0.12)",
  label,
  sublabel,
}: {
  value: number;
  size?: number;
  strokeWidth?: number;
  color?: string;
  trackColor?: string;
  label: string;
  sublabel?: string;
}) {
  const radius = (size - strokeWidth) / 2;
  const circumference = 2 * Math.PI * radius;
  const clampedVal = Math.max(0, Math.min(100, value));
  const strokeDashoffset = circumference - (clampedVal / 100) * circumference;

  return (
    <div className={styles.ringWrapper} style={{ width: size, height: size }}>
      <svg width={size} height={size} className={styles.ringSvg}>
        <circle
          stroke={trackColor}
          fill="transparent"
          strokeWidth={strokeWidth}
          r={radius}
          cx={size / 2}
          cy={size / 2}
        />
        <circle
          stroke={color}
          fill="transparent"
          strokeWidth={strokeWidth}
          strokeDasharray={`${circumference} ${circumference}`}
          style={{ strokeDashoffset, transition: "stroke-dashoffset 0.6s ease" }}
          strokeLinecap="round"
          r={radius}
          cx={size / 2}
          cy={size / 2}
          transform={`rotate(-90 ${size / 2} ${size / 2})`}
        />
      </svg>
      <div className={styles.ringInner}>
        <span className={styles.ringVal} style={{ color }}>{label}</span>
        {sublabel && <span className={styles.ringSub}>{sublabel}</span>}
      </div>
    </div>
  );
}

// Sparkline SVG component
function Sparkline({ points, color = "#00f0ff" }: { points: number[]; color?: string }) {
  if (points.length < 2) return null;
  const width = 160;
  const height = 40;
  const max = 100;
  const step = width / (points.length - 1);
  const coords = points.map((p, i) => {
    const x = i * step;
    const y = height - (Math.min(100, Math.max(0, p)) / max) * (height - 6) - 3;
    return `${x},${y}`;
  });

  const pathStr = `M ${coords.join(" L ")}`;
  const areaStr = `${pathStr} L ${width},${height} L 0comma${height} Z`.replace("0comma", "0,");

  return (
    <svg width="100%" height={height} viewBox={`0 0 ${width} ${height}`} className={styles.sparkSvg}>
      <defs>
        <linearGradient id="sparkGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={color} stopOpacity="0.35" />
          <stop offset="100%" stopColor={color} stopOpacity="0.0" />
        </linearGradient>
      </defs>
      <path d={areaStr} fill="url(#sparkGrad)" />
      <path d={pathStr} fill="none" stroke={color} strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

export default function Dashboard() {
  const state = useJarvisStore((s) => s.state);
  const level = useJarvisStore((s) => s.level);
  const muted = useJarvisStore((s) => s.muted);
  const messages = useJarvisStore((s) => s.messages);
  const clearLog = useJarvisStore((s) => s.clearLog);
  const telemetry = useJarvisStore((s) => s.telemetry);
  const cpuHistory = useJarvisStore((s) => s.cpuHistory);
  const isFullscreen = useJarvisStore((s) => s.isFullscreen);
  const setIsFullscreen = useJarvisStore((s) => s.setIsFullscreen);

  const [prompt, setPrompt] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [toastMsg, setToastMsg] = useState<string | null>(null);
  const feedEndRef = useRef<HTMLDivElement>(null);

  const showToast = (msg: string) => {
    setToastMsg(msg);
    setTimeout(() => {
      setToastMsg((prev) => (prev === msg ? null : prev));
    }, 3200);
  };

  const handleToggleFullscreen = async () => {
    const fs = await callPywebview<boolean>("toggle_fullscreen");
    if (typeof fs === "boolean") {
      setIsFullscreen(fs);
      showToast(fs ? "Fullscreen Mode Enabled" : "Windowed Mode");
    } else {
      setIsFullscreen(!isFullscreen);
    }
  };

  const handleVolumeChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const val = Number(e.target.value);
    await callPywebview("set_volume", val);
  };

  const handleVolumeStep = async (step: number) => {
    const current = telemetry?.volume ?? 50;
    const target = Math.max(0, Math.min(100, current + step));
    await callPywebview("set_volume", target);
    showToast(`Master Volume: ${target}%`);
  };

  const handleToggleSystemMute = async () => {
    await callPywebview("toggle_system_mute");
    showToast("System Audio Mute Toggled");
  };

  const handleToggleMic = async () => {
    await callPywebview("toggle_mute");
    showToast(muted ? "Microphone Activated" : "Microphone Muted");
  };

  const handleExecuteAction = async (payload: any, label: string) => {
    showToast(`Executing: ${label}...`);
    try {
      const res = await callPywebview("execute_action", payload);
      if (res && res.success) {
        showToast(`✓ ${label} Successful`);
      } else {
        showToast(res?.message ? `Notice: ${res.message}` : `✓ ${label} executed`);
      }
    } catch (err: any) {
      showToast(`Error: ${err.message || "Failed"}`);
    }
  };

  const handleSendPrompt = async (e?: React.FormEvent, customText?: string) => {
    if (e) e.preventDefault();
    const textToSend = (customText ?? prompt).trim();
    if (!textToSend || isSending) return;

    setPrompt("");
    setIsSending(true);
    try {
      const res = await callPywebview("send_chat", textToSend);
      if (res && !res.success && res.message) {
        showToast(`Agent error: ${res.message}`);
      }
    } catch (err: any) {
      showToast(`Transmit error: ${err.message || "Failed"}`);
    } finally {
      setIsSending(false);
    }
  };

  useEffect(() => {
    feedEndRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  // Telemetry safe accessors
  const cpuVal = telemetry?.cpu_percent ?? 0;
  const memVal = telemetry?.memory_percent ?? 0;
  const memUsed = telemetry?.memory_used_gb ?? 0;
  const memTotal = telemetry?.memory_total_gb ?? 0;
  const diskVal = telemetry?.disk_percent ?? 0;
  const diskFree = telemetry?.disk_free_gb ?? 0;
  const diskTotal = telemetry?.disk_total_gb ?? 0;
  const volumeVal = telemetry?.volume ?? 50;
  const sysMuted = telemetry?.system_muted ?? false;
  const ipAddr = telemetry?.ip_address ?? "127.0.0.1";
  const activeWin = telemetry?.active_window || "JARVIS System Core";
  const agentModel = telemetry?.agent_model ?? "gemini-3.5-flash-lite";
  const ttsVoice = telemetry?.tts_voice ?? "en-GB-RyanNeural";
  const whisperModel = telemetry?.whisper_model ?? "base.en";
  const uptime = formatUptime(telemetry?.uptime_seconds);
  const processCount = telemetry?.process_count ?? 0;

  // VU meter bars simulation based on level
  const numBars = 16;
  const normalizedLevel = Math.min(1, Math.max(0, level * 2.8));
  const activeBarsCount = Math.round(normalizedLevel * numBars);

  const quickPrompts = [
    "What is my IP address?",
    "System status report",
    "Open Chrome",
    "Take a screenshot",
    "Increase volume by 15%",
  ];

  return (
    <div className={styles.container}>
      {toastMsg && <div className={styles.toast}>{toastMsg}</div>}

      {/* TOP TACTICAL HUD STRIP */}
      <div className={styles.hudHeader}>
        <div className={styles.hudHeaderLeft}>
          <div className={styles.starkBranding}>
            <span className={styles.techMarker}>[MARK LXXXV]</span>
            <h1 className={styles.hudTitle}>STARK TACTICAL COMMAND CENTER</h1>
            <span className={styles.classifiedBadge}>RESTRICTED ACCESS // PROTOCOL OMNI</span>
          </div>
          <div className={styles.metaRow}>
            <span className={styles.metaItem}>
              <strong className={styles.metaKey}>OPERATOR:</strong> SIR ABDULLAH
            </span>
            <span className={styles.metaSeparator}>//</span>
            <span className={styles.metaItem}>
              <strong className={styles.metaKey}>HOST IP:</strong> {ipAddr}
            </span>
            <span className={styles.metaSeparator}>//</span>
            <span className={styles.metaItem}>
              <strong className={styles.metaKey}>UPTIME:</strong> {uptime}
            </span>
            <span className={styles.metaSeparator}>//</span>
            <span className={styles.metaItem}>
              <strong className={styles.metaKey}>ACTIVE FOCUS:</strong> {activeWin}
            </span>
          </div>
        </div>

        <div className={styles.hudHeaderRight}>
          <button
            className={`${styles.actionBtn} ${isFullscreen ? styles.btnActiveGlow : ""}`}
            onClick={handleToggleFullscreen}
            title="Toggle Fullscreen Command Deck (F11)"
          >
            <span className={styles.btnIcon}>{isFullscreen ? "⊡" : "⛶"}</span>
            {isFullscreen ? "EXIT FULLSCREEN" : "FULLSCREEN HUD"}
          </button>
          <button
            className={styles.actionBtn}
            onClick={() => showToast("Telemetry synchronized.")}
            title="Synchronize System Metrics"
          >
            <span className={styles.btnIcon}>↻</span>
            REFRESH
          </button>
          <button
            className={`${styles.actionBtn} ${styles.btnDanger}`}
            onClick={() => {
              clearLog();
              showToast("Activity history cleared.");
            }}
            title="Clear interaction log"
          >
            <span className={styles.btnIcon}>🗑</span>
            CLEAR LOG
          </button>
        </div>
      </div>

      {/* MAIN COMMAND DECK GRID */}
      <div className={styles.deckGrid}>
        
        {/* TILE 1: NEURAL CORE & AUDIO SPECTRUM */}
        <div className={`${styles.card} ${styles.neuralCard}`}>
          <div className={styles.cardHeader}>
            <span className={styles.cardIndicator} />
            <h2 className={styles.cardTitle}>NEURAL ENGINE &amp; ACOUSTICS</h2>
            <span className={`${styles.statePill} ${styles[state] || styles.idle}`}>
              {muted ? "MIC MUTED" : state.toUpperCase()}
            </span>
          </div>

          <div className={styles.coreDisplay}>
            {/* Holographic Arc Reactor Visualizer */}
            <div className={`${styles.arcReactor} ${styles[state] || styles.idle}`}>
              <div className={styles.arcRingOuter} />
              <div className={styles.arcRingInner} />
              <div className={styles.arcCoreCenter}>
                <span className={styles.arcText}>AI</span>
              </div>
            </div>

            <div className={styles.neuralSpecs}>
              <div className={styles.specRow}>
                <span className={styles.specLabel}>BRAIN MODEL:</span>
                <span className={styles.specVal}>{agentModel}</span>
              </div>
              <div className={styles.specRow}>
                <span className={styles.specLabel}>VOICE ENGINE:</span>
                <span className={styles.specVal}>{ttsVoice} (-35Hz Deep)</span>
              </div>
              <div className={styles.specRow}>
                <span className={styles.specLabel}>SPEECH RECOG:</span>
                <span className={styles.specVal}>Whisper {whisperModel}</span>
              </div>
              <div className={styles.specRow}>
                <span className={styles.specLabel}>WAKE WORD:</span>
                <span className={styles.specVal}>&ldquo;Hey Jarvis&rdquo; (Active)</span>
              </div>
            </div>
          </div>

          {/* Real-time Acoustic Waveform & VU Meter */}
          <div className={styles.audioSection}>
            <div className={styles.audioHeader}>
              <span className={styles.audioTitle}>MICROPHONE SPECTRUM (LIVE VU)</span>
              <span className={styles.audioDb}>
                {muted ? "MUTED" : `${Math.round(normalizedLevel * 100)}% PEAK`}
              </span>
            </div>
            <div className={styles.vuMeterBars}>
              {Array.from({ length: numBars }).map((_, idx) => {
                const isActive = !muted && idx < activeBarsCount;
                const isPeak = !muted && idx === activeBarsCount - 1 && activeBarsCount > 0;
                return (
                  <div
                    key={idx}
                    className={`${styles.vuBar} ${isActive ? styles.vuActive : ""} ${
                      isPeak ? styles.vuPeak : ""
                    }`}
                    style={{
                      height: `${Math.max(15, (idx / numBars) * 100)}%`,
                    }}
                  />
                );
              })}
            </div>
            <div className={styles.micControlRow}>
              <button
                className={`${styles.micToggleBtn} ${muted ? styles.micMutedBtn : ""}`}
                onClick={handleToggleMic}
              >
                {muted ? "🎙 UNMUTE MICROPHONE" : "🔇 MUTE MICROPHONE"}
              </button>
            </div>
          </div>
        </div>

        {/* TILE 2: HARDWARE TELEMETRY & SYSTEM LOAD */}
        <div className={`${styles.card} ${styles.hardwareCard}`}>
          <div className={styles.cardHeader}>
            <span className={styles.cardIndicator} />
            <h2 className={styles.cardTitle}>HARDWARE TELEMETRY MATRIX</h2>
            <span className={styles.cardBadge}>LIVE SENSORS</span>
          </div>

          <div className={styles.gaugesContainer}>
            {/* CPU Gauge */}
            <div className={styles.gaugeBlock}>
              <ProgressRing
                value={cpuVal}
                size={102}
                strokeWidth={8}
                color={cpuVal > 80 ? "#ff3355" : cpuVal > 50 ? "#ffaa00" : "#00f0ff"}
                label={`${Math.round(cpuVal)}%`}
                sublabel="CPU LOAD"
              />
              <div className={styles.gaugeMeta}>
                <span className={styles.gaugeTitle}>CPU MATRIX</span>
                <span className={styles.gaugeStatus}>
                  {cpuVal < 50 ? "NOMINAL" : cpuVal < 80 ? "ELEVATED" : "HIGH LOAD"}
                </span>
                <span className={styles.gaugeDetail}>{processCount} Processes</span>
              </div>
            </div>

            {/* RAM Gauge */}
            <div className={styles.gaugeBlock}>
              <ProgressRing
                value={memVal}
                size={102}
                strokeWidth={8}
                color={memVal > 85 ? "#ff3355" : "#00ffcc"}
                label={`${Math.round(memVal)}%`}
                sublabel="RAM USAGE"
              />
              <div className={styles.gaugeMeta}>
                <span className={styles.gaugeTitle}>MEMORY CORE</span>
                <span className={styles.gaugeStatus}>
                  {memUsed > 0 ? `${memUsed} / ${memTotal} GB` : `${memVal}% Used`}
                </span>
                <span className={styles.gaugeDetail}>DDR4/DDR5 POOL</span>
              </div>
            </div>
          </div>

          {/* CPU Sparkline activity curve */}
          <div className={styles.sparklineSection}>
            <div className={styles.sparkHeader}>
              <span className={styles.sparkTitle}>PROCESSOR DYNAMIC LOAD CURVE</span>
              <span className={styles.sparkCurrent}>{cpuVal}%</span>
            </div>
            <Sparkline points={cpuHistory} color="#00f0ff" />
          </div>

          {/* Storage & Drive info */}
          <div className={styles.storageSection}>
            <div className={styles.storageHeader}>
              <span className={styles.storageLabel}>PRIMARY STORAGE (C: DRIVE)</span>
              <span className={styles.storageVals}>
                {diskFree > 0 ? `${diskFree} GB FREE / ${diskTotal} GB` : `${diskVal}% USED`}
              </span>
            </div>
            <div className={styles.segmentedBar}>
              <div className={styles.segmentedFill} style={{ width: `${Math.min(100, diskVal)}%` }} />
            </div>
          </div>
        </div>

        {/* TILE 3: TACTICAL AUTOMATION & CONTROLS */}
        <div className={`${styles.card} ${styles.tacticalCard}`}>
          <div className={styles.cardHeader}>
            <span className={styles.cardIndicator} />
            <h2 className={styles.cardTitle}>TACTICAL AUTOMATION DECK</h2>
            <span className={styles.cardBadge}>ONE-CLICK ACTIONS</span>
          </div>

          {/* Master Volume Sliders & Controls */}
          <div className={styles.volumeBlock}>
            <div className={styles.volHeader}>
              <span className={styles.volTitle}>MASTER AUDIO SYSTEM</span>
              <span className={styles.volVal}>
                {sysMuted ? "MUTED" : `${volumeVal}%`}
              </span>
            </div>
            <div className={styles.volSliderRow}>
              <input
                type="range"
                min="0"
                max="100"
                value={volumeVal}
                onChange={handleVolumeChange}
                className={styles.volSlider}
              />
              <div className={styles.volStepBtns}>
                <button
                  className={styles.stepBtn}
                  onClick={() => handleVolumeStep(-10)}
                  title="Decrease volume by 10%"
                >
                  -10%
                </button>
                <button
                  className={`${styles.stepBtn} ${sysMuted ? styles.stepMuted : ""}`}
                  onClick={handleToggleSystemMute}
                  title="Mute / Unmute System Audio"
                >
                  {sysMuted ? "UNMUTE" : "MUTE"}
                </button>
                <button
                  className={styles.stepBtn}
                  onClick={() => handleVolumeStep(10)}
                  title="Increase volume by 10%"
                >
                  +10%
                </button>
              </div>
            </div>
          </div>

          {/* Quick Automation Launchers */}
          <div className={styles.quickGrid}>
            <button
              className={styles.gridBtn}
              onClick={() =>
                handleExecuteAction({ action: "screenshot", operation: "take" }, "Capture Screen")
              }
            >
              <span className={styles.gridBtnIcon}>📸</span>
              <span className={styles.gridBtnLabel}>SCREENSHOT</span>
              <span className={styles.gridBtnSub}>Desktop Capture</span>
            </button>

            <button
              className={styles.gridBtn}
              onClick={() =>
                handleExecuteAction({ action: "system", operation: "lock" }, "Lock Workstation")
              }
            >
              <span className={styles.gridBtnIcon}>🔒</span>
              <span className={styles.gridBtnLabel}>LOCK PC</span>
              <span className={styles.gridBtnSub}>Security Protocol</span>
            </button>

            <button
              className={styles.gridBtn}
              onClick={() =>
                handleExecuteAction(
                  { action: "browser", operation: "open", url: "https://www.google.com" },
                  "Open Browser"
                )
              }
            >
              <span className={styles.gridBtnIcon}>🌐</span>
              <span className={styles.gridBtnLabel}>BROWSER</span>
              <span className={styles.gridBtnSub}>Google Search</span>
            </button>

            <button
              className={styles.gridBtn}
              onClick={() =>
                handleExecuteAction(
                  { action: "explorer", operation: "open", path: "C:\\Users\\Abdullah_\\Desktop" },
                  "Open Explorer"
                )
              }
            >
              <span className={styles.gridBtnIcon}>📂</span>
              <span className={styles.gridBtnLabel}>EXPLORER</span>
              <span className={styles.gridBtnSub}>Desktop Folder</span>
            </button>

            <button
              className={styles.gridBtn}
              onClick={() =>
                handleExecuteAction({ action: "media", operation: "play_pause" }, "Media Play/Pause")
              }
            >
              <span className={styles.gridBtnIcon}>⏯</span>
              <span className={styles.gridBtnLabel}>PLAY / PAUSE</span>
              <span className={styles.gridBtnSub}>Media Player</span>
            </button>

            <button
              className={styles.gridBtn}
              onClick={() =>
                handleExecuteAction({ action: "media", operation: "next_track" }, "Next Track")
              }
            >
              <span className={styles.gridBtnIcon}>⏭</span>
              <span className={styles.gridBtnLabel}>NEXT TRACK</span>
              <span className={styles.gridBtnSub}>Media Forward</span>
            </button>
          </div>
        </div>
      </div>

      {/* BOTTOM SECTION: DIRECT TERMINAL PROMPT & RECENT ACTIVITY FEED */}
      <div className={styles.bottomSection}>
        {/* INTERACTIVE COMMAND UPLINK BAR */}
        <div className={styles.promptBarWrap}>
          <div className={styles.promptHeader}>
            <span className={styles.promptTech}>DIRECT AI UPLINK // TRANSMIT TO JARVIS</span>
            <div className={styles.quickPrompts}>
              {quickPrompts.map((qp, i) => (
                <button
                  key={i}
                  className={styles.qpChip}
                  onClick={() => handleSendPrompt(undefined, qp)}
                >
                  &ldquo;{qp}&rdquo;
                </button>
              ))}
            </div>
          </div>

          <form onSubmit={handleSendPrompt} className={styles.promptForm}>
            <span className={styles.promptPrefix}>JARVIS&gt;</span>
            <input
              type="text"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Ask anything or command JARVIS (e.g. 'What is my IP address?', 'Check system status', 'Open Spotify')..."
              className={styles.promptInput}
              disabled={isSending}
            />
            <button
              type="submit"
              className={`${styles.promptSubmitBtn} ${isSending ? styles.sending : ""}`}
              disabled={isSending || !prompt.trim()}
            >
              {isSending ? "TRANSMITTING..." : "TRANSMIT ↵"}
            </button>
          </form>
        </div>

        {/* RECENT ACTIVITY & CONVERSATION FEED */}
        <div className={styles.feedCard}>
          <div className={styles.feedHeader}>
            <div className={styles.feedTitleWrap}>
              <span className={styles.feedDot} />
              <h3 className={styles.feedTitle}>MISSION LOG &amp; CONVERSATION STREAM</h3>
            </div>
            <span className={styles.feedCount}>{messages.length} ENTRIES</span>
          </div>

          <div className={styles.feedScroll}>
            {messages.length === 0 ? (
              <div className={styles.feedEmpty}>
                <span className={styles.emptyIcon}>📡</span>
                <p>System listening on wake word &ldquo;Hey Jarvis&rdquo; or use the Direct AI Uplink above.</p>
              </div>
            ) : (
              messages.map((m) => (
                <div
                  key={m.id}
                  className={`${styles.feedMsg} ${m.who === "you" ? styles.msgYou : styles.msgJarvis} ${
                    m.who === "jarvis" && m.tone === "negative" ? styles.msgNegative : ""
                  }`}
                >
                  <div className={styles.msgTop}>
                    <span className={styles.msgSender}>
                      {m.who === "you" ? "SIR ABDULLAH" : "JARVIS MARK LXXXV"}
                    </span>
                    <span className={styles.msgTime}>{m.timestamp || "LIVE"}</span>
                  </div>
                  <div className={styles.msgBody} dangerouslySetInnerHTML={{ __html: m.text }} />
                </div>
              ))
            )}
            <div ref={feedEndRef} />
          </div>
        </div>
      </div>
    </div>
  );
}
