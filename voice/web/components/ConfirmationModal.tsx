"use client";

import { useEffect, useState, useCallback } from "react";
import { useJarvisStore } from "@/lib/store";
import { callPywebview } from "@/lib/bridge";
import styles from "./ConfirmationModal.module.css";

export default function ConfirmationModal() {
  const pendingConfirmation = useJarvisStore((s) => s.pendingConfirmation);
  const setPendingConfirmation = useJarvisStore((s) => s.setPendingConfirmation);

  const [timeLeft, setTimeLeft] = useState(20);
  const [initialTime, setInitialTime] = useState(20);

  const resolve = useCallback(
    async (approved: boolean) => {
      if (!pendingConfirmation) return;
      const id = pendingConfirmation.id;
      setPendingConfirmation(null);
      try {
        await callPywebview("resolve_confirmation", id, approved);
      } catch (err) {
        console.error("Failed to resolve confirmation:", err);
      }
    },
    [pendingConfirmation, setPendingConfirmation]
  );

  useEffect(() => {
    if (!pendingConfirmation) return;
    const dur = pendingConfirmation.timeoutSeconds || 20;
    setTimeLeft(dur);
    setInitialTime(dur);

    const interval = setInterval(() => {
      setTimeLeft((prev) => {
        if (prev <= 1) {
          clearInterval(interval);
          resolve(false);
          return 0;
        }
        return prev - 1;
      });
    }, 1000);

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Enter" || e.key === "y" || e.key === "Y") {
        e.preventDefault();
        resolve(true);
      } else if (e.key === "Escape" || e.key === "n" || e.key === "N") {
        e.preventDefault();
        resolve(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);

    return () => {
      clearInterval(interval);
      window.removeEventListener("keydown", handleKeyDown);
    };
  }, [pendingConfirmation, resolve]);

  if (!pendingConfirmation) return null;

  const isCritical = pendingConfirmation.riskLevel === "CRITICAL";
  const progressPercent = Math.max(0, Math.min(100, (timeLeft / initialTime) * 100));

  return (
    <div className={styles.backdrop}>
      <div className={`${styles.dialog} ${isCritical ? styles.critical : styles.high}`}>
        {/* Glow Header */}
        <div className={styles.header}>
          <div className={styles.headerTitle}>
            <span className={styles.warningIcon}>{isCritical ? "☣" : "⚠"}</span>
            <div>
              <span className={styles.kicker}>
                {isCritical ? "CRITICAL PROTOCOL RESTRICTION" : "SECURITY ACCESS CONFIRMATION"}
              </span>
              <h3>HIGH PRIVILEGE COMMAND</h3>
            </div>
          </div>
          <button className={styles.closeBtn} onClick={() => resolve(false)} title="Deny & Close">
            ✕
          </button>
        </div>

        {/* Risk Badge */}
        <div className={styles.badgeRow}>
          <span className={`${styles.badge} ${isCritical ? styles.criticalBadge : styles.highBadge}`}>
            RISK TIER: {pendingConfirmation.riskLevel}
          </span>
          <span className={styles.shellBadge}>
            SHELL: {pendingConfirmation.shell.toUpperCase()}
          </span>
        </div>

        {/* Reason */}
        <div className={styles.reasonBox}>
          <p>{pendingConfirmation.reason}</p>
        </div>

        {/* Command Display Terminal */}
        <div className={styles.terminalBox}>
          <div className={styles.terminalHeader}>
            <span>COMMAND PREVIEW</span>
            <span className={styles.readOnlyTag}>READ-ONLY PREVIEW</span>
          </div>
          <pre className={styles.commandCode}>
            <code>{pendingConfirmation.command}</code>
          </pre>
        </div>

        {/* Live Countdown Progress */}
        <div className={styles.timerSection}>
          <div className={styles.timerLabel}>
            <span>Auto-denying in: <strong>{timeLeft}s</strong></span>
            <span className={styles.timerHint}>Press [Y] to Approve • [N] to Deny</span>
          </div>
          <div className={styles.progressBarBg}>
            <div
              className={`${styles.progressBarFill} ${isCritical ? styles.criticalFill : styles.highFill}`}
              style={{ width: `${progressPercent}%` }}
            />
          </div>
        </div>

        {/* Action Buttons */}
        <div className={styles.actions}>
          <button
            className={`${styles.btn} ${styles.btnDeny}`}
            onClick={() => resolve(false)}
          >
            ✕ DENY / CANCEL <span className={styles.keyHint}>[Esc]</span>
          </button>
          <button
            className={`${styles.btn} ${isCritical ? styles.btnCritical : styles.btnApprove}`}
            onClick={() => resolve(true)}
          >
            ✓ APPROVE &amp; EXECUTE <span className={styles.keyHint}>[Enter]</span>
          </button>
        </div>
      </div>
    </div>
  );
}
