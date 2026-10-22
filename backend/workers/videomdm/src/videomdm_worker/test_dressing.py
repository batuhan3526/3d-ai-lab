"""Synthetic TDD test for transfer_skin_weights (Task 3.2).

Run with: python -m pytest test_dressing.py -v
or:        python test_dressing.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

import numpy as np
from dressing import transfer_skin_weights


def test_transfer_assigns_weights():
    """Garment vertices near body vertices must get valid, normalised weights."""
    rng = np.random.default_rng(42)
    body   = rng.random((100, 3))
    body_w = np.eye(100)[:, :24]          # 24 SMPL joints; each body vertex owns one joint
    garm   = body[:10] + 1e-3             # garment vertices very close to first 10 body verts

    w = transfer_skin_weights(garm, body, body_w)

    assert w.shape == (10, 24), f"Expected (10, 24), got {w.shape}"
    assert np.allclose(w.sum(axis=1), 1.0, atol=1e-3), \
        f"Row sums not 1: {w.sum(axis=1)}"
    print("test_transfer_assigns_weights PASSED")


def test_transfer_shape_generic():
    """Works for arbitrary garment / body counts and joint counts."""
    rng = np.random.default_rng(7)
    body   = rng.random((6890, 3))
    # Random weight matrix, normalised rows
    body_w_raw = rng.random((6890, 24))
    body_w = body_w_raw / body_w_raw.sum(axis=1, keepdims=True)

    garm = rng.random((500, 3))
    w = transfer_skin_weights(garm, body, body_w)

    assert w.shape == (500, 24), f"Expected (500, 24), got {w.shape}"
    assert np.allclose(w.sum(axis=1), 1.0, atol=1e-5), \
        f"Row sums not 1: max deviation {np.abs(w.sum(axis=1) - 1.0).max()}"
    print("test_transfer_shape_generic PASSED")


def test_transfer_exact_hit():
    """When garment vertex is exactly on a body vertex, that vertex's weights dominate."""
    body   = np.eye(5, 3, dtype=float)   # 5 body verts: [1,0,0],[0,1,0],[0,0,1],...
    body_w = np.eye(5, 5)                # body vert i owns joint i
    # Garment vertex exactly on body[0] = [1, 0, 0]
    garm   = np.array([[1.0, 0.0, 0.0]])

    w = transfer_skin_weights(garm, body, body_w, k=1)
    assert w.shape == (1, 5)
    # With k=1 and exact match on body[0], should be entirely joint 0
    assert w[0, 0] > 0.99, f"Expected joint 0 dominant, got {w[0]}"
    print("test_transfer_exact_hit PASSED")


if __name__ == "__main__":
    test_transfer_assigns_weights()
    test_transfer_shape_generic()
    test_transfer_exact_hit()
    print("\nAll dressing tests PASSED.")
