/**
 * Global vitest setup: extends `expect` with `@testing-library/jest-dom`'s
 * DOM matchers (`toBeInTheDocument`, `toHaveTextContent`, etc.) for every
 * test file, including the plain `lib/**` unit tests that run under the
 * `node` environment -- importing the matchers is a no-op until a DOM node
 * is actually asserted against, so this is safe to load globally rather
 * than per-component-test-file.
 */
import "@testing-library/jest-dom/vitest";

import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

/**
 * React Testing Library normally registers this itself automatically, but
 * only when it detects a GLOBAL `afterEach` (the Jest-style ambient global
 * `globals: true` gives you) -- this project's `vitest.config.mts`
 * deliberately does NOT set `globals: true` (component tests import
 * `describe`/`it`/`afterEach` explicitly from `"vitest"` instead), so RTL's
 * auto-detection never fires and unmounted trees would otherwise pile up in
 * `document.body` across `it()` blocks in the same file, corrupting later
 * queries in that file (e.g. a `getByRole` that matched exactly once now
 * matching N times, once per accumulated render). Registering it explicitly
 * here restores the cleanup-after-every-test behavior without needing
 * `globals: true`. A no-op for the plain `node`-environment `lib/**` tests,
 * which never call `render()` in the first place.
 */
afterEach(() => {
  cleanup();
});
