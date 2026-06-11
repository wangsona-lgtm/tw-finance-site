#!/usr/bin/env python3
"""0050.TW MA Crossover Backtest — fast=5, slow=20"""
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import json

SYMBOL = "0050.TW"
START = "2022-01-01"
END = "2024-12-31"
CAPITAL = 2_000_000
FAST = 5
SLOW = 20

print(f"📥 下載 {SYMBOL} 資料 ({START} ~ {END})...")
df = yf.download(SYMBOL, start=START, end=END, auto_adjust=True)
# Flatten MultiIndex columns (('Close','0050.TW') -> 'Close')
if isinstance(df.columns, pd.MultiIndex):
    df.columns = df.columns.get_level_values(0)
# Ensure required columns exist
cols = ['Open','High','Low','Close','Volume']
if all(c in df.columns for c in cols):
    df = df[cols].copy()
df.dropna(inplace=True)
print(f"   共 {len(df)} 個交易日")

# ---- 策略 ----
df['MA5'] = df['Close'].rolling(window=FAST).mean()
df['MA20'] = df['Close'].rolling(window=SLOW).mean()
df['Signal'] = 0
df.loc[df['MA5'] > df['MA20'], 'Signal'] = 1
df.loc[df['MA5'] <= df['MA20'], 'Signal'] = -1
df['Position'] = df['Signal'].diff()

# ---- 回測 ----
cash = CAPITAL
shares = 0
equity_curve = [CAPITAL]
trades = []
entry_price = 0
entry_date = None
entry_cash = CAPITAL

for i in range(len(df)):
    date = df.index[i]
    close = float(df['Close'].iloc[i])
    
    if df['Position'].iloc[i] == 2 and cash > 0:    # 黃金交叉：買入
        shares_to_buy = int(cash / close / 1000) * 1000  # 千股為單位
        if shares_to_buy == 0:
            shares_to_buy = int(cash / close)
        cost = shares_to_buy * close
        cash -= cost
        shares += shares_to_buy
        entry_price = close
        entry_date = date
        entry_cash = cash
        trades.append({'type': 'buy', 'date': str(date.date()), 'price': round(close,2), 'shares': shares_to_buy, 'cost': round(cost,2)})
        print(f"  🟢 買入 {date.date()} @ {close:.2f}  股數:{shares_to_buy}  現金:${cash:,.0f}")

    elif df['Position'].iloc[i] == -2 and shares > 0: # 死亡交叉：賣出
        proceeds = shares * close
        cash += proceeds
        pnl = (close - entry_price) / entry_price * 100
        trades.append({'type': 'sell', 'date': str(date.date()), 'price': round(close,2), 'proceeds': round(proceeds,2), 'pnl_pct': round(pnl,2)})
        print(f"  🔴 賣出 {date.date()} @ {close:.2f}  入帳:${proceeds:,.0f}  損益:{pnl:+.2f}%")
        shares = 0
        entry_price = 0

    equity = cash + shares * close
    equity_curve.append(equity)

# 持有到期末
if shares > 0:
    close = float(df['Close'].iloc[-1])
    cash += shares * close
    pnl = (close - entry_price) / entry_price * 100
    trades.append({'type': 'sell_force', 'date': str(df.index[-1].date()), 'price': round(close,2), 'pnl_pct': round(pnl,2)})
    print(f"  🔴 強制賣出 {df.index[-1].date()} @ {close:.2f}  損益:{pnl:+.2f}%")
    shares = 0

final_value = cash
total_return = (final_value - CAPITAL) / CAPITAL * 100

# Buy & Hold
bh_return = (float(df['Close'].iloc[-1]) / float(df['Close'].iloc[0]) - 1) * 100

# Sharpe
daily_returns = pd.Series(equity_curve).pct_change().dropna()
sharpe = np.sqrt(252) * daily_returns.mean() / daily_returns.std() if daily_returns.std() > 0 else 0

# Max drawdown
cummax = pd.Series(equity_curve).cummax()
dd = (pd.Series(equity_curve) - cummax) / cummax
max_dd = dd.min() * 100

# Win rate
win_trades = [t for t in trades if t.get('pnl_pct',0) > 0]
loss_trades = [t for t in trades if t.get('pnl_pct',0) < 0]
win_rate = len(win_trades) / (len(win_trades) + len(loss_trades)) * 100 if (len(win_trades)+len(loss_trades)) > 0 else 0

# 年化
years = (df.index[-1] - df.index[0]).days / 365.25
ann_return = ((1 + total_return/100) ** (1/years) - 1) * 100 if years > 0 else 0

print(f"\n{'='*50}")
print(f"📊 回測結果 — 0050 MA({FAST}/{SLOW}) 交叉")
print(f"{'='*50}")
print(f"  初始資金:  ${CAPITAL:,.0f}")
print(f"  最終資值:  ${final_value:,.0f}")
print(f"  總報酬率:  {total_return:+.2f}%")
print(f"  年化報酬:  {ann_return:+.2f}%")
print(f"  Buy & Hold: {bh_return:+.2f}%")
print(f"  Sharpe:     {sharpe:.2f}")
print(f"  最大回撤:  {max_dd:.2f}%")
print(f"  勝率:      {win_rate:.1f}% ({len(win_trades)}W/{len(loss_trades)}L)")
print(f"  交易次數:  {len(trades)//2} 次")
print(f"{'='*50}")

# === Generate HTML ===
fig = make_subplots(
    rows=3, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.05,
    row_heights=[0.6, 0.2, 0.2],
    subplot_titles=(f"0050.TW K線 + MA({FAST}/{SLOW})", "策略淨值曲線", "最大回撤")
)

# K-line
fig.add_trace(go.Candlestick(
    x=df.index, open=df['Open'], high=df['High'],
    low=df['Low'], close=df['Close'],
    name='K線', increasing_line_color='#ef5350', decreasing_line_color='#26a69a'
), row=1, col=1)

# MA lines
fig.add_trace(go.Scatter(x=df.index, y=df['MA5'], name=f'MA{FAST}',
    line=dict(color='#FFA726', width=1.5)), row=1, col=1)
fig.add_trace(go.Scatter(x=df.index, y=df['MA20'], name=f'MA{SLOW}',
    line=dict(color='#42A5F5', width=1.5)), row=1, col=1)

# Buy/Sell signals
buy_signals = df[df['Position'] == 2]
sell_signals = df[df['Position'] == -2]
fig.add_trace(go.Scatter(x=buy_signals.index, y=buy_signals['Close'],
    mode='markers', name='買入', marker=dict(color='#00E676', size=12, symbol='triangle-up')),
    row=1, col=1)
fig.add_trace(go.Scatter(x=sell_signals.index, y=sell_signals['Close'],
    mode='markers', name='賣出', marker=dict(color='#FF5252', size=12, symbol='triangle-down')),
    row=1, col=1)

# Equity curve
fig.add_trace(go.Scatter(x=df.index, y=equity_curve[1:],
    name='策略淨值', line=dict(color='#FFD54F', width=2),
    fill='tozeroy', fillcolor='rgba(255,213,79,0.15)'), row=2, col=1)

# Drawdown
fig.add_trace(go.Scatter(x=df.index, y=dd[1:]*100,
    name='回撤', line=dict(color='#FF5252', width=1.5),
    fill='tozeroy', fillcolor='rgba(255,82,82,0.15)'), row=3, col=1)

fig.update_layout(
    title=f'0050.TW MA({FAST}/{SLOW}) 交叉策略回測',
    template='plotly_white',
    height=1000,
    hovermode='x unified',
    xaxis_rangeslider_visible=False,
    showlegend=True,
)
fig.update_yaxes(title_text="價格 (NT$)", row=1, col=1)
fig.update_yaxes(title_text="淨值 (NT$)", row=2, col=1)
fig.update_yaxes(title_text="回撤 (%)", row=3, col=1)

html = fig.to_html(include_plotlyjs='cdn', full_html=False)
# Use dark-theme card layout like old reports
full_html = f'''<!DOCTYPE html>
<html lang="zh-TW">
<head>
<meta charset="UTF-8">
<title>0050.TW 回測報告 — ma_cross</title>
<style>
* {{ box-sizing: border-box; margin: 0; padding: 0; }}
body {{ background: #1e1e2e; color: #cdd6f4; font-family: 'Segoe UI', sans-serif; padding: 24px; }}
h1 {{ font-size: 1.6rem; margin-bottom: 4px; color: #cba6f7; }}
.subtitle {{ color: #6c7086; font-size: 0.9rem; margin-bottom: 20px; }}
.card {{ background: #313244; border-radius: 12px; padding: 16px 20px; min-width: 130px; text-align: center; }}
.card .label {{ font-size: 0.75rem; color: #6c7086; margin-bottom: 6px; }}
.card .value {{ font-size: 1.4rem; font-weight: 700; }}
h2 {{ font-size: 1.1rem; margin: 28px 0 12px; color: #89b4fa; }}
table {{ width: 100%%; border-collapse: collapse; font-size: 0.85rem; }}
th {{ background: #313244; padding: 10px 14px; text-align: left; color: #89b4fa; font-weight: 600; }}
td {{ padding: 8px 14px; border-bottom: 1px solid #313244; }}
tr:hover td {{ background: #2a2a3c; }}
</style>
</head>
<body>
<h1>📊 0050.TW 回測報告</h1>
<div class="subtitle">策略：ma_cross (MA{FAST}/{SLOW}) ｜ 初始資金：${CAPITAL:,}</div>

<div style="display:flex;gap:16px;flex-wrap:wrap;margin:20px 0;">
<div class="card"><div class="label">總報酬</div><div class="value" style="color:{"#00E676" if total_return>=0 else "#FF5252"}">{total_return:+.1f}%</div></div>
<div class="card"><div class="label">年化報酬</div><div class="value">{ann_return:+.1f}%</div></div>
<div class="card"><div class="label">Buy & Hold</div><div class="value" style="color:#42A5F5">{bh_return:+.1f}%</div></div>
<div class="card"><div class="label">Sharpe</div><div class="value">{sharpe:.2f}</div></div>
<div class="card"><div class="label">最大回撤</div><div class="value" style="color:#FF5252">{max_dd:.1f}%</div></div>
<div class="card"><div class="label">勝率</div><div class="value">{win_rate:.0f}%</div></div>
<div class="card"><div class="label">交易次數</div><div class="value">{len(trades)//2} 筆</div></div>
<div class="card"><div class="label">盈/虧</div><div class="value">{len(win_trades)}W / {len(loss_trades)}L</div></div>
<div class="card"><div class="label">最終資值</div><div class="value">${final_value:,.0f}</div></div>
</div>

{html}

<h2>📋 交易明細</h2>
<table>
<tr><th>序號</th><th>日期</th><th>類型</th><th>價格</th><th>金額</th><th>損益</th></tr>
{"".join(f'<tr><td>{i+1}</td><td>{t["date"]}</td><td>{"買入" if t["type"]=="buy" else "賣出"}</td><td>${t["price"]:,.2f}</td><td>${t.get("cost", t.get("proceeds",0)):,.0f}</td><td style="color:{"#00E676" if t.get("pnl_pct",0)>=0 else "#FF5252"}">{t.get("pnl_pct","—")}{"%" if t.get("pnl_pct") else ""}</td></tr>'.replace("%","%%") for i,t in enumerate(trades))}
</table>

<h2>📝 策略評估</h2>
<p style="color:#a6adc8; line-height:1.7; margin-bottom:20px;">
MA({FAST}/{SLOW}) 均線交叉策略在 0050.TW {START[:4]}-{END[:4]} 期間表現{"優於大盤" if total_return > bh_return else "不如單純持有"}。
策略於黃金交叉時買入、死亡交叉時賣出，共觸發 {len(trades)//2} 次完整交易，勝率 {win_rate:.0f}%。
</p>

<div style="border-top:1px solid #313244; padding-top:16px; color:#6c7086; font-size:0.8rem;">
📅 回測區間: {START} ~ {END} ｜ 📊 資料來源: Yahoo Finance<br>
⚠️ 本報告僅供策略研究參考，不構成投資建議。
</div>
</body>
</html>'''

import re
output_path = f"0050-ma{FAST}-cross-backtest.html"
with open(output_path, 'w', encoding='utf-8') as f:
    f.write(full_html)

# Summary
summary = (
    f"0050 MA({FAST}/{SLOW}) 交叉策略回測摘要\n"
    f"──────────────────────────────\n"
    f"股票: {SYMBOL} ({START} ~ {END})\n"
    f"策略: MA{FAST}/MA{SLOW} 均線交叉\n"
    f"初始資金: ${CAPITAL:,}\n"
    f"最終資值: ${final_value:,.0f} ({total_return:+.1f}%)\n"
    f"Buy & Hold: {bh_return:+.1f}%\n"
    f"年化報酬: {ann_return:+.1f}%\n"
    f"Sharpe: {sharpe:.2f}\n"
    f"最大回撤: {max_dd:.1f}%\n"
    f"勝率: {win_rate:.0f}%\n"
    f"交易次數: {len(trades)//2} 筆\n"
    f"──────────────────────────────\n"
    f"報告: {output_path}\n"
)
with open('0050-ma5-cross-summary.txt', 'w') as f:
    f.write(summary)

print(summary)
sz = len(full_html.encode('utf-8'))
print(f"📄 HTML 大小: {sz:,} bytes ({'✅ >50KB' if sz > 50000 else '❌ <50KB'})")
