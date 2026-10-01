import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // Don't write editor-assistant rule files into the project on `next dev`.
  agentRules: false,
  // The repo root also has a package-lock.json (for the `concurrently`
  // dev-orchestration script); this tells Turbopack the frontend app's
  // own root is here, not the repo root, silencing the lockfile-detection warning.
  turbopack: {
    root: path.join(__dirname),
  },
};

export default nextConfig;
