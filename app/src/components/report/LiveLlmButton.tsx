"use client";

/**
 * Optional "Generate live persona" button. Only rendered by the server page
 * when `ENABLE_LIVE_LLM === 'true'` at build/runtime (see `app/page.tsx`) --
 * in the default zero-env-var build this component never ships. Even when
 * rendered, `/api/persona-live` always responds 501 today (see that
 * route's docstring); this button surfaces the reason rather than pretending
 * to succeed.
 */

import { useState } from "react";

export function LiveLlmButton() {
  const [status, setStatus] = useState<"idle" | "loading" | "done">("idle");
  const [reason, setReason] = useState<string | null>(null);

  async function handleClick() {
    setStatus("loading");
    try {
      const response = await fetch("/api/persona-live", { method: "POST" });
      const body = await response.json().catch(() => ({}));
      setReason(typeof body.reason === "string" ? body.reason : `HTTP ${response.status}`);
    } catch {
      setReason("Request failed.");
    } finally {
      setStatus("done");
    }
  }

  return (
    <div className="flex flex-col gap-1">
      <button
        type="button"
        onClick={handleClick}
        disabled={status === "loading"}
        className="self-start rounded-md border px-3 py-1.5 text-xs font-medium"
        style={{ borderColor: "var(--border)", color: "var(--text-secondary)" }}
      >
        {status === "loading" ? "Requesting…" : "Generate live persona (experimental)"}
      </button>
      {reason && (
        <p className="text-xs" style={{ color: "var(--text-muted)" }}>
          Not available: {reason}
        </p>
      )}
    </div>
  );
}
