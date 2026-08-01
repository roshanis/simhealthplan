/**
 * Zod request schema for `POST /api/scenario`. Field-level validation
 * mirrors the choice-model engine's `Plan` shape (`lib/choice-model/types.ts`):
 * the four benefit flags are booleans and must be changed with `set`; the
 * three numeric fields (`premium_total`, `moop_inn`, `star_rating`) accept
 * either an additive `delta` or an absolute `set`, but exactly one of the
 * two -- never both, never neither (an ambiguous or no-op change is a 400,
 * not a silently-ignored request).
 */

import { z } from "zod";

export const BOOLEAN_SCENARIO_FIELDS = [
  "has_comprehensive_dental",
  "has_vision",
  "has_hearing_aids",
  "has_otc_or_flex",
] as const;

export const NUMERIC_SCENARIO_FIELDS = ["premium_total", "moop_inn", "star_rating"] as const;

export type BooleanScenarioField = (typeof BOOLEAN_SCENARIO_FIELDS)[number];
export type NumericScenarioField = (typeof NUMERIC_SCENARIO_FIELDS)[number];
export type ScenarioField = BooleanScenarioField | NumericScenarioField;

export const ScenarioFieldSchema = z.enum([...BOOLEAN_SCENARIO_FIELDS, ...NUMERIC_SCENARIO_FIELDS]);

const RawChangeSchema = z.object({
  plan_key: z.string().min(1, "plan_key is required"),
  field: ScenarioFieldSchema,
  delta: z.number().finite().optional(),
  set: z.union([z.number().finite(), z.boolean()]).optional(),
});

export type ScenarioChange = z.infer<typeof RawChangeSchema>;

function isBooleanField(field: ScenarioField): field is BooleanScenarioField {
  return (BOOLEAN_SCENARIO_FIELDS as readonly string[]).includes(field);
}

export const ScenarioChangeSchema = RawChangeSchema.superRefine((change, ctx) => {
  const hasDelta = change.delta !== undefined;
  const hasSet = change.set !== undefined;

  if (hasDelta === hasSet) {
    ctx.addIssue({
      code: "custom",
      message: "exactly one of `delta` or `set` must be provided",
      path: ["delta"],
    });
    return;
  }

  if (isBooleanField(change.field)) {
    if (hasDelta) {
      ctx.addIssue({ code: "custom", message: `${change.field} is a boolean field; use \`set\`, not \`delta\``, path: ["delta"] });
    } else if (typeof change.set !== "boolean") {
      ctx.addIssue({ code: "custom", message: `${change.field} requires a boolean \`set\` value`, path: ["set"] });
    }
  } else {
    if (hasSet && typeof change.set !== "number") {
      ctx.addIssue({ code: "custom", message: `${change.field} requires a numeric \`set\` value`, path: ["set"] });
    }
  }
});

export const ScenarioRequestSchema = z.object({
  changes: z.array(ScenarioChangeSchema).min(1, "at least one change is required"),
  /** Optional Monte Carlo controls, mainly for tests -- defaults chosen for
   * the <1s round-trip budget in production use (see `runScenario.ts`). */
  draws: z.number().int().positive().max(2000).optional(),
  seed: z.number().int().optional(),
});

export type ScenarioRequest = z.infer<typeof ScenarioRequestSchema>;
