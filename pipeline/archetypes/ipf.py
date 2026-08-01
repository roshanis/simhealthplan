"""Generic n-way iterative proportional fitting (IPF / RAS / raking).

Plain-numpy implementation: repeatedly rescale the working table along each
axis so its marginal sum matches the target, sweeping over all axes until
every marginal is within ``tol`` (default ``1e-9``) or ``max_iter`` sweeps
elapse. Starting from a uniform (or caller-supplied "seed") table and only
ever *multiplying*, any zero cell in the seed stays exactly zero forever --
this is how ``cells.py`` and ``plan_priors.py`` encode hard structural
constraints (e.g. "no D-SNP probability mass on non-dual archetypes").

Used for two distinct purposes in this package:
  1. ``cells.py``: 3-way IPF over the ACS age/income/race marginals with a
     uniform seed. With only one-way marginals and no interaction data, this
     is mathematically equivalent to (and converges in one sweep to) the
     conditional-independence product distribution -- see
     ``test_ipf_3way_orthogonal_marginals_converges_to_product_form``. That
     equivalence *is* the documented conditional-independence assumption:
     IPF is used here for auditability/consistency with the doubly-
     constrained use below, not because it finds something a product
     couldn't.
  2. ``plan_priors.py``: 2-way *doubly-constrained* IPF (row = archetype
     weight, column = actual plan enrollment) starting from a tilted,
     hard-zeroed seed matrix -- the classic biproportional/RAS fitting
     procedure for reconciling a prior cross-tabulation to new margins.
"""

from __future__ import annotations

import numpy as np


def ipf_fit(
    marginals: list[np.ndarray],
    seed: np.ndarray | None = None,
    tol: float = 1e-9,
    max_iter: int = 1000,
) -> tuple[np.ndarray, int]:
    """Fit a table to N one-way marginals via iterative proportional fitting.

    Args:
        marginals: one 1-D array per axis; ``marginals[k]`` is the target
            sum of the table along all axes except ``k``. All marginals
            must sum to (approximately) the same total.
        seed: optional starting table of shape ``tuple(len(m) for m in
            marginals)``. Defaults to all-ones (uniform). Zero cells in the
            seed remain zero after fitting (structural zeros).
        tol: convergence tolerance on the max absolute marginal error.
        max_iter: safety cap on the number of full axis sweeps.

    Returns:
        (table, iterations) -- the fitted table and the number of full
        sweeps performed (1-indexed; the sweep that reaches convergence).
    """
    marginals = [np.asarray(m, dtype=np.float64) for m in marginals]
    totals = [m.sum() for m in marginals]
    if max(totals) - min(totals) > 1e-6 * max(1.0, max(totals)):
        raise ValueError(f"Marginal totals must match; got {totals}")

    shape = tuple(len(m) for m in marginals)
    table = np.ones(shape, dtype=np.float64) if seed is None else np.array(seed, dtype=np.float64)
    if table.shape != shape:
        raise ValueError(f"seed shape {table.shape} does not match marginals shape {shape}")

    n_axes = len(shape)
    all_axes = tuple(range(n_axes))

    for iteration in range(1, max_iter + 1):
        for axis, target in enumerate(marginals):
            reduce_axes = tuple(a for a in all_axes if a != axis)
            current = table.sum(axis=reduce_axes) if reduce_axes else table
            safe_current = np.where(current > 0, current, 1.0)
            factor = np.where(current > 0, target / safe_current, 0.0)
            broadcast_shape = [1] * n_axes
            broadcast_shape[axis] = len(target)
            table = table * factor.reshape(broadcast_shape)

        max_err = 0.0
        for axis, target in enumerate(marginals):
            reduce_axes = tuple(a for a in all_axes if a != axis)
            current = table.sum(axis=reduce_axes) if reduce_axes else table
            max_err = max(max_err, float(np.max(np.abs(current - target))))

        if max_err < tol:
            return table, iteration

    return table, max_iter
