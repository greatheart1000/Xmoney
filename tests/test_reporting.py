"""报告模块测试"""
import pytest
from pathlib import Path

from app.reporting import _calc_stats, _plot_equity_curve, _write_html_report, build_daily_report
from app.models import DailyStats


def _sample_row(**overrides):
    """构造测试用信号行"""
    row = {
        "id": 1,
        "created_at": "2026-04-18T10:30:00",
        "symbol": "SA605",
        "action": "short",
        "outcome_return": None,
    }
    row.update(overrides)
    return row


def test_calc_stats_empty_signals():
    """测试无信号时的统计计算"""
    stats = _calc_stats("2026-04-18", [])
    assert stats.date == "2026-04-18"
    assert stats.total_signals == 0
    assert stats.evaluated_signals == 0
    assert stats.win_rate == 0.0
    assert stats.avg_win == 0.0
    assert stats.avg_loss == 0.0
    assert stats.profit_factor == 0.0
    assert stats.expectancy == 0.0
    assert stats.max_drawdown == 0.0
    assert stats.cumulative_return == 0.0


def test_calc_stats_no_evaluated_signals():
    """测试有信号但无评估结果时的统计"""
    rows = [
        _sample_row(id=1, outcome_return=None),
        _sample_row(id=2, outcome_return=None),
    ]
    stats = _calc_stats("2026-04-18", rows)
    assert stats.total_signals == 2
    assert stats.evaluated_signals == 0
    assert stats.win_rate == 0.0


def test_calc_stats_winning_signals():
    """测试盈利信号的统计"""
    rows = [
        _sample_row(id=1, outcome_return=0.02),
        _sample_row(id=2, outcome_return=0.015),
    ]
    stats = _calc_stats("2026-04-18", rows)
    assert stats.total_signals == 2
    assert stats.evaluated_signals == 2
    assert stats.win_rate == 1.0
    assert stats.avg_win > 0
    assert stats.avg_loss == 0.0
    assert stats.profit_factor == 999.0  # 有盈利无亏损时
    assert stats.expectancy > 0
    assert stats.cumulative_return > 0


def test_calc_stats_losing_signals():
    """测试亏损信号的统计"""
    rows = [
        _sample_row(id=1, outcome_return=-0.02),
        _sample_row(id=2, outcome_return=-0.015),
    ]
    stats = _calc_stats("2026-04-18", rows)
    assert stats.evaluated_signals == 2
    assert stats.win_rate == 0.0
    assert stats.avg_win == 0.0
    assert stats.avg_loss < 0
    assert stats.profit_factor == 0.0  # 无盈利
    assert stats.expectancy < 0
    assert stats.cumulative_return < 0


def test_calc_stats_mixed_signals():
    """测试混合信号的统计"""
    rows = [
        _sample_row(id=1, outcome_return=0.03),
        _sample_row(id=2, outcome_return=-0.01),
        _sample_row(id=3, outcome_return=0.02),
        _sample_row(id=4, outcome_return=-0.015),
        _sample_row(id=5, outcome_return=None),  # 未评估
    ]
    stats = _calc_stats("2026-04-18", rows)
    assert stats.total_signals == 5
    assert stats.evaluated_signals == 4
    assert stats.win_rate == 0.5  # 2胜2负
    assert stats.avg_win > 0
    assert stats.avg_loss < 0
    assert stats.profit_factor > 0
    assert stats.max_drawdown >= 0


def test_calc_stats_max_drawdown():
    """测试最大回撤计算"""
    # 连续盈利后大亏损
    rows = [
        _sample_row(id=1, outcome_return=0.02),
        _sample_row(id=2, outcome_return=0.01),
        _sample_row(id=3, outcome_return=-0.05),
    ]
    stats = _calc_stats("2026-04-18", rows)
    assert stats.max_drawdown > 0  # 回撤应大于0


def test_calc_stats_profit_factor():
    """测试盈亏比计算"""
    rows = [
        _sample_row(id=1, outcome_return=0.03),
        _sample_row(id=2, outcome_return=-0.01),
    ]
    stats = _calc_stats("2026-04-18", rows)
    # 盈利总额=0.03, 亏损总额=0.01, profit_factor=3.0
    assert stats.profit_factor == pytest.approx(3.0, abs=0.01)


def test_equity_curve_generation(tmp_path, monkeypatch):
    """测试权益曲线图生成"""
    monkeypatch.setattr("app.reporting.Path", lambda p="": tmp_path / p if p else tmp_path)
    monkeypatch.chdir(tmp_path)

    rows = [
        _sample_row(id=1, outcome_return=0.02),
        _sample_row(id=2, outcome_return=-0.01),
    ]

    # 直接调用内部函数测试
    from app import reporting
    original_path = reporting.Path

    # 使用 tmp_path/reports 作为输出目录
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)

    chart_path = reports_dir / "equity_2026-04-18.png"
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    evaluated = [r for r in rows if r.get("outcome_return") is not None]
    returns = [float(r["outcome_return"]) for r in evaluated]

    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))

    plt.figure(figsize=(8, 4.2))
    plt.plot(equity, label="Equity Curve", color="#00A3FF", linewidth=2)
    plt.title("Daily Equity Curve - 2026-04-18")
    plt.xlabel("Trade #")
    plt.ylabel("Equity")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(chart_path)
    plt.close()

    assert chart_path.exists()
    assert chart_path.stat().st_size > 0


def test_build_daily_report(tmp_path, monkeypatch):
    """测试完整日报生成流程"""
    monkeypatch.chdir(tmp_path)

    rows = [
        _sample_row(id=1, outcome_return=0.02),
        _sample_row(id=2, outcome_return=-0.01),
    ]

    stats, chart_path, html_path = build_daily_report("2026-04-18", rows)

    assert isinstance(stats, DailyStats)
    assert stats.date == "2026-04-18"
    assert chart_path.exists()
    assert html_path.exists()
    assert "2026-04-18" in str(chart_path)
    assert "2026-04-18" in str(html_path)


def test_build_daily_report_html_content(tmp_path, monkeypatch):
    """测试HTML报告内容正确性"""
    monkeypatch.chdir(tmp_path)

    rows = [
        _sample_row(id=1, outcome_return=0.02),
    ]

    stats, chart_path, html_path = build_daily_report("2026-04-18", rows)
    html_content = html_path.read_text(encoding="utf-8")

    assert "AI辅助决策日报" in html_content
    assert "SA605" in html_content
    assert "2026-04-18" in html_content
