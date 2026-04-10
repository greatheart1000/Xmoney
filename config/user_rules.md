# 用户注入规则（可自行修改）

1. 先看文华指数（30m定方向，15m确认），再看单品种。
2. 使用 MA(5,10,20,40,60)、MACD、CJL/持仓量。
3. 合并历史重要支撑位/压力位。
4. 使用斐波那契价格回调位（0.236/0.382/0.5/0.618/0.786）。
5. 使用斐波那契时间窗（0.618/1.0/1.618）估算趋势剩余时间。
6. 输出观望/做多/做空/持有/减仓，给出 entry/stop/take-profit。
7. 输出 expected_remaining_bars、expected_total_move_pct。
8. 追求高盈亏比：仅在 Fib 0.382-0.618 且靠近 MA20/MA60 的黄金入场区考虑开仓。
9. 必须计算 risk_reward_ratio=(TakeProfit-Entry)/(Entry-Stop)（空头按对称公式）；若低于 3.0，action 强制降级为 wait。
10. 输出 risk_reward_ratio 与 is_high_quality_setup，并在报告中包含 break-even、分批止盈、时间止损建议。
