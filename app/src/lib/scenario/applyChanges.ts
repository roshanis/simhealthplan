/**
 * Pure plan-mutation logic for the scenario demo: applies validated
 * `ScenarioChange`s (see `schema.ts`) to a `Plan[]` roster, returning a new
 * array (the input is never mutated) plus the set of `plan_key`s touched.
 *
 * Numeric fields clamp to a physically sane range after `delta`/`set` is
 * applied -- premium/MOOP can't go negative, star rating stays in Medicare's
 * documented 1.0-5.0 range -- so an aggressive slider (e.g. premium delta
 * -$500) degrades to a sane boundary instead of producing a nonsense plan.
 */

import type { Plan } from "@/lib/choice-model/types";
import { BOOLEAN_SCENARIO_FIELDS, type ScenarioChange } from "@/lib/scenario/schema";

const CLAMPS: Partial<Record<string, [number, number]>> = {
  premium_total: [0, Number.POSITIVE_INFINITY],
  moop_inn: [0, Number.POSITIVE_INFINITY],
  star_rating: [1, 5],
};

function clamp(field: string, value: number): number {
  const bounds = CLAMPS[field];
  if (!bounds) return value;
  const [min, max] = bounds;
  return Math.min(max, Math.max(min, value));
}

function isBooleanField(field: string): boolean {
  return (BOOLEAN_SCENARIO_FIELDS as readonly string[]).includes(field);
}

/** Applies one change to one plan, returning a new plan object. Assumes the
 * change has already passed `ScenarioChangeSchema` validation (exactly one
 * of `delta`/`set`, correctly typed for the field). */
export function applyChangeToPlan(plan: Plan, change: ScenarioChange): Plan {
  if (isBooleanField(change.field)) {
    return { ...plan, [change.field]: change.set as boolean };
  }

  const current = (plan as unknown as Record<string, number>)[change.field] ?? 0;
  const next = change.set !== undefined ? (change.set as number) : current + (change.delta as number);
  return { ...plan, [change.field]: clamp(change.field, next) };
}

export interface ApplyChangesResult {
  plans: Plan[];
  changedPlanKeys: string[];
}

/** Applies every change in `changes` to the matching plan(s) in `basePlans`
 * (matched by `plan_key`; multiple changes to the same plan all apply,
 * in order). `basePlans` is never mutated. Changes referencing a
 * `plan_key` not present in `basePlans` are silently skipped (the caller
 * -- the route handler -- validates `plan_key` exists before calling this,
 * so this is a defensive no-op, not the primary validation path). */
export function applyChanges(basePlans: Plan[], changes: ScenarioChange[]): ApplyChangesResult {
  const changesByKey = new Map<string, ScenarioChange[]>();
  for (const change of changes) {
    const existing = changesByKey.get(change.plan_key);
    if (existing) {
      existing.push(change);
    } else {
      changesByKey.set(change.plan_key, [change]);
    }
  }

  const plans = basePlans.map((plan) => {
    const planChanges = changesByKey.get(plan.plan_key);
    if (!planChanges) return plan;
    return planChanges.reduce((acc, change) => applyChangeToPlan(acc, change), plan);
  });

  return { plans, changedPlanKeys: [...changesByKey.keys()] };
}
