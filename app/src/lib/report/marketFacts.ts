/**
 * Pure headline-fact computation for the "The world the personas live in"
 * market-snapshot section. Each fact is a plain sentence string plus the
 * numbers that back it, computed once from `market.json` so the copy can
 * never drift out of sync with the underlying data.
 */

import { formatCount, formatMoney, formatPercent } from "@/lib/format";
import type { MarketData } from "@/lib/data/types";

export interface MarketFact {
  id: string;
  text: string;
}

/** Four headline facts contrasting `year1` -> `year2` (defaults 2024 -> 2025,
 * matching this pilot's backtest window). Throws if either year is missing
 * from `market.market_totals`/`market.org_rollups` -- both years are always
 * present in a well-formed `market.json`, so a missing year indicates a
 * genuinely malformed artifact, not a "pending" state to degrade gracefully
 * for. */
export function buildMarketFacts(market: MarketData, year1 = "2024", year2 = "2025"): MarketFact[] {
  const totals1 = market.market_totals[year1];
  const totals2 = market.market_totals[year2];
  const rollups2 = market.org_rollups[year2];
  if (!totals1 || !totals2) {
    throw new Error(`market.json is missing market_totals for ${year1} or ${year2}`);
  }

  const planCountDelta = totals2.plan_count - totals1.plan_count;
  const planCountDeltaText =
    planCountDelta === 0 ? "unchanged" : `${planCountDelta > 0 ? "+" : ""}${planCountDelta} vs ${year1}`;

  const eligiblesDelta = totals2.eligibles - totals1.eligibles;

  const leader = rollups2?.[0];

  const facts: MarketFact[] = [
    {
      id: "roster-size",
      text: `${totals2.plan_count} Medicare Advantage plans competed for Maricopa County's ${formatCount(totals2.eligibles)} eligible beneficiaries in ${year2} (${planCountDeltaText}).`,
    },
    {
      id: "eligibles-growth",
      text: `The eligible population grew by ${formatCount(eligiblesDelta)} people from ${year1} to ${year2}, while MA penetration moved from ${formatPercent(totals1.ma_penetration)} to ${formatPercent(totals2.ma_penetration)}.`,
    },
  ];

  if (leader) {
    const leaderShare = leader.total_enrollment / totals2.total_ma_enrollment;
    facts.push({
      id: "market-leader",
      text: `${leader.org_name} leads the ${year2} market with ${leader.plan_count} plans and ${formatPercent(leaderShare)} of enrolled MA members (avg premium ${formatMoney(leader.avg_premium)}, avg star rating ${leader.avg_star_rating.toFixed(1)}).`,
    });
  }

  const avgPremium2 =
    market.plans[year2].reduce((sum, p) => sum + p.premium_total, 0) / market.plans[year2].length;
  const zeroPremiumShare =
    market.plans[year2].filter((p) => p.premium_total === 0).length / market.plans[year2].length;
  facts.push({
    id: "premium-landscape",
    text: `The average ${year2} plan premium is ${formatMoney(avgPremium2)}/month; ${formatPercent(zeroPremiumShare, 0)} of plans carry a $0 premium.`,
  });

  return facts;
}
