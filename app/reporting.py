from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import matplotlib.pyplot as plt

from .models import DailyReportResponse, DailyStats


def _calc_stats(date_str: str, rows: List[Dict]) -> DailyStats:
    evaluated = [r for r in rows if r.get("outcome_return") is not None]
    returns = [float(r["outcome_return"]) for r in evaluated]

    total = len(rows)
    n_eval = len(evaluated)
    wins = [r for r in returns if r > 0]
    losses = [r for r in returns if r < 0]

    win_rate = len(wins) / n_eval if n_eval else 0.0
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = sum(losses) / len(losses) if losses else 0.0
    gross_win = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = (gross_win / gross_loss) if gross_loss > 0 else (999.0 if gross_win > 0 else 0.0)
    expectancy = sum(returns) / n_eval if n_eval else 0.0

    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))
    peak = 1.0
    max_dd = 0.0
    for val in equity:
        peak = max(peak, val)
        dd = (val - peak) / peak
        max_dd = min(max_dd, dd)

    cumulative_return = equity[-1] - 1 if len(equity) > 1 else 0.0

    return DailyStats(
        date=date_str,
        total_signals=total,
        evaluated_signals=n_eval,
        win_rate=win_rate,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        expectancy=expectancy,
        max_drawdown=abs(max_dd),
        cumulative_return=cumulative_return,
    )


def _plot_equity_curve(date_str: str, rows: List[Dict]) -> Path:
    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    chart_path = out_dir / f"equity_{date_str}.png"

    evaluated = [r for r in rows if r.get("outcome_return") is not None]
    returns = [float(r["outcome_return"]) for r in evaluated]

    equity = [1.0]
    for r in returns:
        equity.append(equity[-1] * (1 + r))

    plt.figure(figsize=(8, 4.2))
    plt.plot(equity, label="Equity Curve", color="#00A3FF", linewidth=2)
    plt.title(f"Daily Equity Curve - {date_str}")
    plt.xlabel("Trade #")
    plt.ylabel("Equity")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(chart_path)
    plt.close()
    return chart_path


def _write_html_report(date_str: str, stats: DailyStats, rows: List[Dict], chart_path: Path) -> Path:
    html_path = Path("reports") / f"daily_{date_str}.html"

    table_rows = "\n".join(
        f"<tr><td>{r['id']}</td><td>{r['created_at']}</td><td>{r['symbol']}</td><td>{r['action']}</td><td>{r.get('outcome_return', '')}</td></tr>"
        for r in rows
    )

    html = f"""
<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <title>AI交易日报 {date_str}</title>
  <style>
    body {{ font-family: Arial, sans-serif; margin: 24px; background: #111; color: #eee; }}
    .card {{ background: #1b1b1b; padding: 16px; border-radius: 10px; margin-bottom: 16px; }}
    table {{ border-collapse: collapse; width: 100%; }}
    th, td {{ border: 1px solid #333; padding: 8px; text-align: left; }}
    th {{ background: #232323; }}
  </style>
</head>
<body>
  <h1>AI辅助决策日报 - {date_str}</h1>
  <div class="card">
    <p>信号数: {stats.total_signals} | 已评估: {stats.evaluated_signals}</p>
    <p>命中率: {stats.win_rate:.2%} | 盈亏比(Profit Factor): {stats.profit_factor:.2f}</p>
    <p>期望收益: {stats.expectancy:.4f} | 累计收益: {stats.cumulative_return:.2%} | 最大回撤: {stats.max_drawdown:.2%}</p>
  </div>
  <div class="card">
    <img src="{chart_path.name}" alt="equity curve" style="max-width: 100%;" />
  </div>
  <div class="card">
    <h3>信号明细</h3>
    <table>
      <thead><tr><th>ID</th><th>时间</th><th>合约</th><th>动作</th><th>结果收益</th></tr></thead>
      <tbody>
        {table_rows}
      </tbody>
    </table>
  </div>
</body>
</html>
"""
    html_path.write_text(html, encoding="utf-8")
    return html_path


def build_daily_report(date_str: str, rows: List[Dict]) -> Tuple[DailyStats, Path, Path]:
    stats = _calc_stats(date_str, rows)
    chart_path = _plot_equity_curve(date_str, rows)
    html_path = _write_html_report(date_str, stats, rows, chart_path)
    return stats, chart_path, html_path


def to_response(date_str: str, rows: List[Dict]) -> DailyReportResponse:
    stats, chart_path, html_path = build_daily_report(date_str, rows)
    return DailyReportResponse(stats=stats, chart_path=str(chart_path), html_path=str(html_path))
