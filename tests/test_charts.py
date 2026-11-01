"""构建期 SVG 图表测试。"""

from visual_report.charts import bar_chart, donut_chart, line_chart


def test_bar_chart_basic():
    svg = bar_chart(["Q1", "Q2"], [10, 20])
    assert svg.startswith("<svg") and svg.endswith("</svg>")
    assert "Q1" in svg and "10" in svg
    assert "var(--chart-1)" in svg  # 主题 token 联动


def test_bar_chart_multi_series_legend():
    svg = bar_chart(
        ["A", "B"],
        None,
        series=[{"name": "S1", "values": [1, 2]}, {"name": "S2", "values": [3, 4]}],
    )
    assert "S1" in svg and "S2" in svg


def test_line_chart_null_breaks_segment():
    """null 缺失值必须断线而不是连过去（ADR-009）。"""
    svg = line_chart(["a", "b", "c"], [1, None, 3])
    # 两段独立 polyline
    assert svg.count("<polyline") == 2


def test_line_chart_all_values_present_single_line():
    svg = line_chart(["a", "b", "c"], [1, 2, 3])
    assert svg.count("<polyline") == 1


def test_donut_skips_none_and_zero():
    svg = donut_chart(["A", "B", "C"], [50, None, 0])
    assert svg.count("<circle") == 1  # 只渲染 A 的扇区（不含中心文本）


def test_svg_escapes_labels():
    svg = bar_chart(["<script>"], [1])
    assert "<script>" not in svg
    assert "&lt;script&gt;" in svg
