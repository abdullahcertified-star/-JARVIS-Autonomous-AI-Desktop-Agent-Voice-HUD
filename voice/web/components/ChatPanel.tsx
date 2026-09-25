"use client";

import { useEffect, useRef, useState } from "react";
import { useJarvisStore } from "@/lib/store";
import { callPywebview } from "@/lib/bridge";
import styles from "./ChatPanel.module.css";

export default function ChatPanel() {
  const messages = useJarvisStore((s) => s.messages);
  const clearLog = useJarvisStore((s) => s.clearLog);
  const endRef = useRef<HTMLDivElement>(null);
  const [text, setText] = useState("");
  const [isSending, setIsSending] = useState(false);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [messages.length]);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const promptText = text.trim();
    if (!promptText || isSending) return;

    setText("");
    setIsSending(true);
    try {
      await callPywebview("send_chat", promptText);
    } catch {
      // Handled
    } finally {
      setIsSending(false);
    }
  };

  return (
    <div className={styles.terminalContainer}>
      <div className={styles.terminalHeader}>
        <div className={styles.terminalTitle}>
          <span className={styles.dot} />
          <span>J.A.R.V.I.S. SECURE TERMINAL UPLINK</span>
        </div>
        <button className={styles.clearBtn} onClick={clearLog} title="Clear Terminal Log">
          CLEAR LOG
        </button>
      </div>

      <div className={styles.wrap}>
        {messages.length === 0 && (
          <div className={styles.empty}>
            No conversation yet. Say &ldquo;Hey Jarvis&rdquo; or type a command below.
          </div>
        )}
        {messages.map((m) => (
          <div
            key={m.id}
            className={`${styles.msg} ${m.who === "you" ? styles.you : styles.jarvis} ${
              m.who === "jarvis" && m.tone === "negative" ? styles.negative : ""
            }`}
          >
            <div className={styles.msgHeader}>
              <span className={styles.tag}>{m.who === "you" ? "SIR ABDULLAH" : "JARVIS"}</span>
              {m.timestamp && <span className={styles.timeTag}>{m.timestamp}</span>}
            </div>
            <div className={styles.msgContent} dangerouslySetInnerHTML={{ __html: m.text }} />
          </div>
        ))}
        <div ref={endRef} />
      </div>

      <form onSubmit={handleSubmit} className={styles.inputForm}>
        <span className={styles.promptIndicator}>&gt;</span>
        <input
          type="text"
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Transmit instruction to JARVIS (e.g. 'what is my IP address?', 'turn up volume')..."
          className={styles.terminalInput}
          disabled={isSending}
        />
        <button
          type="submit"
          className={styles.sendBtn}
          disabled={isSending || !text.trim()}
        >
          {isSending ? "TRANSMITTING..." : "EXECUTE ↵"}
        </button>
      </form>
    </div>
  );
}
