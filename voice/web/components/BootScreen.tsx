"use client";

import { useEffect, useState } from "react";
import styles from "./BootScreen.module.css";

const BOOT_LINES = [
  "Loading neural interface...",
  "Calibrating voice recognition...",
  "Initializing wake-word engine...",
  "Establishing n8n uplink...",
  "Warming up speech synthesis...",
  "All systems nominal.",
];

export default function BootScreen() {
  const [visibleLines, setVisibleLines] = useState(1);

  useEffect(() => {
    if (visibleLines >= BOOT_LINES.length) return;
    const timer = setTimeout(() => setVisibleLines((n) => n + 1), 420);
    return () => clearTimeout(timer);
  }, [visibleLines]);

  return (
    <div className={styles.wrap}>
      <div className={styles.textBlock}>
        <div className={styles.title}>J.A.R.V.I.S</div>
        <div className={styles.version}>VERSION 6.5</div>
        <div className={styles.subtitle}>PERSONAL ASSISTANT &amp; CORE INTELLIGENCE</div>
        <div className={styles.lines}>
          {BOOT_LINES.slice(0, visibleLines).map((line, i) => (
            <div key={i} className={styles.line}>
              <span className={styles.bullet}>&gt;</span> {line}
            </div>
          ))}
        </div>
      </div>

      <div className={styles.radar}>
        <div className={`${styles.ring} ${styles.ring1}`} />
        <div className={`${styles.ring} ${styles.ring2}`} />
        <div className={`${styles.ring} ${styles.ring3}`} />
        <div className={styles.core} />
      </div>
    </div>
  );
}
