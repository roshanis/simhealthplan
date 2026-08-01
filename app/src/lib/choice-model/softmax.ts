/**
 * Numerically stable softmax, mirroring the max-subtraction approach in
 * `pipeline/choice_model/utility.py::choice_probabilities`:
 *
 *     max_u = max(utilities)
 *     exps = [exp(u - max_u) for u in utilities]
 *     total = sum(exps)
 *     probs = [e / total for e in exps]
 *
 * Kept as a standalone, order-preserving array -> array function (rather
 * than operating on the key/value dict directly) so it's trivially unit
 * testable and reusable outside the choice-model's key/value framing.
 */

export function softmax(utilities: number[]): number[] {
  if (utilities.length === 0) {
    return [];
  }
  const maxUtility = Math.max(...utilities);
  const exps = utilities.map((u) => Math.exp(u - maxUtility));
  const total = exps.reduce((sum, e) => sum + e, 0);
  return exps.map((e) => e / total);
}
