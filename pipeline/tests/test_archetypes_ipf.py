"""Tests for archetypes/ipf.py — generic n-way iterative proportional fitting."""

from __future__ import annotations

import numpy as np
import pytest

from archetypes import ipf


def test_ipf_2way_reproduces_marginals_from_uniform_seed():
    row_target = np.array([0.3, 0.7])
    col_target = np.array([0.2, 0.5, 0.3])
    table, iterations = ipf.ipf_fit([row_target, col_target], tol=1e-9)

    assert table.shape == (2, 3)
    np.testing.assert_allclose(table.sum(axis=1), row_target, atol=1e-9)
    np.testing.assert_allclose(table.sum(axis=0), col_target, atol=1e-9)
    assert iterations >= 1


def test_ipf_3way_orthogonal_marginals_converges_to_product_form():
    age = np.array([0.4, 0.6])
    income = np.array([0.5, 0.5])
    race = np.array([0.2, 0.3, 0.5])
    table, iterations = ipf.ipf_fit([age, income, race], tol=1e-9)

    expected = np.einsum("a,i,r->air", age, income, race)
    np.testing.assert_allclose(table, expected, atol=1e-9)
    # Orthogonal single-axis marginals over a full contingency table with no
    # interaction constraints converge to the independence product form in
    # a single sweep.
    assert iterations == 1


def test_ipf_preserves_structural_zeros_from_seed():
    # Chosen so the unique solution keeps every non-structural cell
    # strictly positive (no cell needs to asymptotically approach zero,
    # which multiplicative IPF only does in the infinite-iteration limit).
    row_target = np.array([0.5, 1.5])
    col_target = np.array([1.0, 1.0])
    seed = np.array([[1.0, 0.0], [1.0, 1.0]])  # top-right structurally zero
    table, _ = ipf.ipf_fit([row_target, col_target], seed=seed, tol=1e-9)
    assert table[0, 1] == pytest.approx(0.0)
    np.testing.assert_allclose(table.sum(axis=1), row_target, atol=1e-9)
    np.testing.assert_allclose(table.sum(axis=0), col_target, atol=1e-9)


def test_ipf_seeded_tilt_changes_allocation_within_matched_margins():
    row_target = np.array([1.0, 1.0])
    col_target = np.array([1.0, 1.0])
    seed_uniform = np.ones((2, 2))
    seed_tilted = np.array([[3.0, 1.0], [1.0, 1.0]])

    table_uniform, _ = ipf.ipf_fit([row_target, col_target], seed=seed_uniform, tol=1e-12)
    table_tilted, _ = ipf.ipf_fit([row_target, col_target], seed=seed_tilted, tol=1e-12)

    # Margins match in both cases...
    np.testing.assert_allclose(table_uniform.sum(axis=1), row_target, atol=1e-9)
    np.testing.assert_allclose(table_tilted.sum(axis=1), row_target, atol=1e-9)
    # ...but the tilted seed shifts more mass into cell (0, 0).
    assert table_tilted[0, 0] > table_uniform[0, 0]


def test_ipf_raises_on_mismatched_marginal_totals():
    with pytest.raises(ValueError):
        ipf.ipf_fit([np.array([0.5, 0.5]), np.array([1.0, 1.0])])
