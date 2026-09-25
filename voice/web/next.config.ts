import path from "path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Served locally by voice/ui.py's own tiny HTTP server (not deployed
  // anywhere), so a plain static export is all that's needed.
  output: "export",
  images: {
    unoptimized: true,
  },
  turbopack: {
    // An unrelated lockfile in the parent user directory was confusing
    // Turbopack's workspace-root auto-detection -- pin it explicitly.
    root: path.join(__dirname),
  },
};

export default nextConfig;
