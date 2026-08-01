/**
 * Global vitest setup: extends `expect` with `@testing-library/jest-dom`'s
 * DOM matchers (`toBeInTheDocument`, `toHaveTextContent`, etc.) for every
 * test file, including the plain `lib/**` unit tests that run under the
 * `node` environment -- importing the matchers is a no-op until a DOM node
 * is actually asserted against, so this is safe to load globally rather
 * than per-component-test-file.
 */
import "@testing-library/jest-dom/vitest";
