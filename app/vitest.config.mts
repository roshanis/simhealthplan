import { defineConfig } from "vitest/config";
import path from "node:path";

export default defineConfig({
  test: {
    // Component tests opt into a DOM per-file via the `// @vitest-environment
    // jsdom` docblock (see e.g. `tests/components/StatusBadge.test.tsx`)
    // rather than flipping this global default -- so the plain `lib/**` /
    // `api/**` unit tests below keep running under cheap, fast `node` with
    // zero jsdom overhead.
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    setupFiles: ["./tests/setup.ts"],
    coverage: {
      provider: "v8",
      reporter: ["text", "html"],
    },
  },
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "./src"),
    },
  },
});
