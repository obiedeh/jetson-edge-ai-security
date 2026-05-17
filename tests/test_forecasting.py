import pytest

from jetson_edge_ai_security.forecasting.attack_count import moving_average_forecast


def test_forecast_single_step_returns_mean():
    result = moving_average_forecast([2, 4, 6], horizon=1, lookback=3)

    assert len(result) == 1
    assert result[0] == pytest.approx(4.0)


def test_forecast_multi_step_repeats_mean():
    result = moving_average_forecast([10, 20], horizon=3, lookback=2)

    assert result == [pytest.approx(15.0)] * 3


def test_forecast_respects_lookback_window():
    result = moving_average_forecast([0, 0, 0, 10, 20], horizon=1, lookback=2)

    assert result[0] == pytest.approx(15.0)


def test_forecast_empty_values_returns_zeros():
    result = moving_average_forecast([], horizon=4)

    assert result == [0.0] * 4


def test_forecast_rejects_zero_horizon():
    with pytest.raises(ValueError, match="horizon"):
        moving_average_forecast([1, 2, 3], horizon=0)
