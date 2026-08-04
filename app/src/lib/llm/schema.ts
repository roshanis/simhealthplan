/**
 * Zod request schema for `POST /api/persona-live`. Mirrors the strictness
 * of `lib/scenario/schema.ts` (the house style: a 400 with `issues` for any
 * malformed body, never a best-effort guess) -- see that file's docstring.
 */

import { z } from "zod";

export const PersonaLiveRequestSchema = z.object({
  /** One of `archetypes.json`'s `id` values (see `lib/data/types.ts`'s
   * `ArchetypeDisplayRecord`). Validated for shape here; existence against
   * the real archetype roster is checked by the route handler, which can
   * give a more specific "unknown archetype" 400 than zod's enum error
   * would (the roster is 80 entries deep and can change with each pipeline
   * run, so it isn't hardcoded into this schema). */
  archetypeId: z.string().min(1, "archetypeId is required"),
});

export type PersonaLiveRequest = z.infer<typeof PersonaLiveRequestSchema>;
