import pytest

from custom_components.candy.helpers import cycles_remaining


@pytest.mark.parametrize(
    ("total", "last_reset", "threshold", "expected"),
    [
        # Just reset — full threshold remaining
        (100, 100, 100, 100),
        # Partway through — counts down normally
        (110, 100, 100, 90),
        (150, 100, 100, 50),
        (199, 100, 100, 1),
        # Exactly at threshold — due
        (200, 100, 100, 0),
        # Overdue by 1 — still 0 (not 99)
        (201, 100, 100, 0),
        # Overdue by a full extra threshold — still 0
        (300, 100, 100, 0),
        # Overdue by more — still 0
        (500, 100, 100, 0),
        # Negative elapsed (last_reset > total, e.g. after manual reset past current count)
        (50, 100, 100, 100),
        # Zero elapsed
        (100, 100, 50, 50),
        # Different threshold
        (85, 0, 85, 0),
        (84, 0, 85, 1),
        (86, 0, 85, 0),
    ],
)
def test_cycles_remaining(total, last_reset, threshold, expected):
    assert cycles_remaining(total, last_reset, threshold) == expected
