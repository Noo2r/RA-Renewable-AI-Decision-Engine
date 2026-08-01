"""Regression test for the notebook's plotly compatibility fix.

The notebook previously used fig.add_vline(x=<iso timestamp string>, ...)
to draw the "now" marker on the forecast chart, which raised a TypeError
deep inside BaseFigure.add_vline on some installed plotly versions. The fix
replaced it with the lower-level fig.add_shape + fig.add_annotation calls.
This test exercises that exact replacement against real ra_core-generated
data (the same data shape the notebook actually plots), without needing to
launch Jupyter or drive any widget UI.
"""
import plotly.graph_objects as go

from ra_core.config import DEFAULT_START_INDEX
from ra_core.data_generator import generate_series
from ra_core.forecasting import forecast_surplus


def _now_marker_figure(now_time: str) -> go.Figure:
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=["2026-07-02T09:00:00", "2026-07-02T10:00:00"], y=[1, 2]))
    fig.add_shape(
        type="line", xref="x", yref="paper",
        x0=now_time, x1=now_time, y0=0, y1=1,
        line=dict(color="#f59e0b", width=1, dash="dot"),
    )
    fig.add_annotation(
        x=now_time, y=1.0, yref="paper", yanchor="bottom",
        text="now", showarrow=False, font=dict(color="#f59e0b", size=12),
    )
    return fig


def test_add_shape_now_marker_does_not_raise():
    fig = _now_marker_figure("2026-07-02T10:00:00")
    assert len(fig.layout.shapes) == 1
    assert len(fig.layout.annotations) == 1


def test_now_marker_works_with_real_forecast_timestamps():
    rows = generate_series("sunny").to_dict("records")
    fc = forecast_surplus(rows, DEFAULT_START_INDEX)
    now_time = fc["history"][-1]["timestamp"]
    # This must not raise -- it's the exact failure mode from the original bug report.
    fig = _now_marker_figure(now_time)
    assert fig.layout.shapes[0].x0 == now_time
