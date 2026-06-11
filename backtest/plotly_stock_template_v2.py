#!/usr/bin/env python3
"""
Plotly 形態學增強版股市圖 v3.0 老大sp
- K線 + MA均線 + 成交量 + RSI + 布林通道
- 🆕 自動型態偵測（頭肩頂/底、雙重頂/底、三角形、楔形、旗形、V型反轉）
- 🆕 趨勢線自動繪製
- 🆕 頸線標示 + 量度目標計算
- 🆕 型態標註（中英文對照）
- 🔴 鐵律三：Y軸自動 zoom-in
- 暗色機構主題

Usage:
  python3 plotly_stock_template_v2.py <股票代碼> [--rsi] [--bollinger] [--pattern] [--output PATH]
  python3 plotly_stock_template_v2.py 6770 --pattern
  python3 plotly_stock_template_v2.py 2330 --rsi --bollinger --pattern
"""

import sys
import argparse
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.signal import argrelextrema
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
import warnings
warnings.filterwarnings('ignore')

# ═══════════════════════════════════════════
# 🎨 暗色機構主題配色
# ═══════════════════════════════════════════
THEME = {
    'bg':             '#0d1117',
    'paper':          '#0d1117',
    'grid':           '#21262d',
    'text':           '#c9d1d9',
    'text_muted':     '#8b949e',
    'green':          '#3fb950',
    'red':            '#f85149',
    'ma5':            '#58a6ff',
    'ma10':           '#d2a8ff',
    'ma20':           '#ffa657',
    'ma60':           '#79c0ff',
    'volume_green':   '#238636',
    'volume_red':     '#da3633',
    'bollinger_bg':       'rgba(88,166,255,0.08)',
    'bollinger_border':   'rgba(88,166,255,0.3)',
    'rsi_line':           '#f0e68c',
    'rsi_ob':             'rgba(248,81,73,0.15)',
    'rsi_os':             'rgba(63,185,80,0.15)',
    # 🆕 型態學配色
    'pattern_line':       '#ff7b72',      # 型態線 — 珊瑚紅
    'pattern_neckline':   '#ffa657',      # 頸線 — 橙色
    'pattern_target':     '#7ee787',      # 目標價 — 綠色
    'pattern_fill':       'rgba(255,123,114,0.08)',  # 型態區域填充
    'pattern_text_bull':  '#3fb950',      # 多頭型態文字
    'pattern_text_bear':  '#f85149',      # 空頭型態文字
    'pattern_text_neutral': '#d2a8ff',    # 中性型態文字
    'trendline_support':  '#3fb950',      # 支撐線
    'trendline_resist':   '#f85149',      # 壓力線
}

FONT_FAMILY = 'Geist, Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif'

# ═══════════════════════════════════════════
# 📐 型態學引擎
# ═══════════════════════════════════════════

@dataclass
class PatternResult:
    """型態辨識結果 v2.2（老大 Time-frame Hierarchy 架構）"""
    name_zh: str          # 中文名
    name_en: str          # 英文名
    category: str         # bullish / bearish / neutral
    confidence: float     # 0.0 ~ 1.0
    start_idx: int        # 起始 index
    end_idx: int          # 結束 index
    neckline: Optional[float] = None     # 頸線價位
    target_price: Optional[float] = None  # 量度目標價
    stop_price: Optional[float] = None   # 停損價
    points: List[Tuple[int, float]] = field(default_factory=list)  # 關鍵點 (idx, price)
    description: str = ''
    # 🆕 成交量確認（老大整理的框架）
    volume_confirm: Optional[str] = None   # '放量' / '量縮' / '價漲量縮⚠️' / None
    volume_ratio: Optional[float] = None    # 突破日量 / 5日均量
    confirmed: bool = False                 # 是否已確認（突破/跌破頸線）
    # 🔧 2026-06-09 老大剖析補入：時間週期權重
    timeframe: str = 'medium'  # 'long'（週線級別） / 'medium'（日線級別） / 'short'（3-5日短線）
    # 🔧 v2.2 老大追加：層級標示（主結構/次級修正）
    hierarchy: str = 'main'   # 'main'（主結構/背景趨勢） / 'sub'（次級修正/波動）
    # 🔧 v2.2：RR風暴比
    risk_reward: Optional[float] = None
    # 🔧 v3.0 老大規範：進場品質完全獨立於 patternScore
    entry_quality: float = 50.0       # 0-100, 由 EntryQualityCalculator 計算
    entry_action: str = '觀望'        # 作多（進場）/ 觀望／等止跌 / 不宜進場
    entry_diagnosis: str = ''
    # 🔧 老大2026-06-09複審：每個型態各自攜帶失效點
    hard_invalidation: Optional[float] = None  # 跌破此價 → 型態全失效
    regime_break: Optional[float] = None       # 跌破此價 → 回到大區間

    @property
    def timeframe_weight(self) -> int:
        """長線權重3、中線2、短線1，用於多空整合"""
        return {'long': 3, 'medium': 2, 'short': 1}.get(self.timeframe, 1)

    @property
    def emoji(self):
        return '🟢' if self.category == 'bullish' else '🔴' if self.category == 'bearish' else '🟡'

    @property
    def direction(self):
        if self.category == 'bullish':
            return '看多 ↗'
        elif self.category == 'bearish':
            return '看空 ↘'
        return '中性 →'


def check_volume_confirmation(df: pd.DataFrame, idx: int, direction: str = 'breakout') -> Tuple[str, float]:
    """
    🆕 成交量確認（老大整理的框架核心）
    
    突破要看量、跌破要守停損、整理時量縮較健康
    
    direction: 'breakout' (向上突破) / 'breakdown' (向下跌破) / 'consolidation' (整理中)
    Returns: (volume_label, volume_ratio)
    """
    if 'volume' not in df.columns or len(df) < 6:
        return '量資料不足', 0.0
    
    avg_vol = df['volume'].rolling(5).mean().iloc[-1] if len(df) >= 5 else df['volume'].mean()
    if avg_vol <= 0:
        return '量資料不足', 0.0
    
    current_vol = df['volume'].iloc[idx] if idx < len(df) else df['volume'].iloc[-1]
    vol_ratio = current_vol / avg_vol
    
    if direction == 'breakout':
        # 向上突破：量要放大（>1.3x均量）
        if vol_ratio >= 1.5:
            return f'放量突破✅ ({vol_ratio:.1f}x)', vol_ratio
        elif vol_ratio >= 1.2:
            return f'量能尚可 ({vol_ratio:.1f}x)', vol_ratio
        else:
            return f'量能不足⚠️ ({vol_ratio:.1f}x)', vol_ratio
    elif direction == 'breakdown':
        # 向下跌破：放量跌破更危險
        if vol_ratio >= 1.5:
            return f'放量跌破🔴 ({vol_ratio:.1f}x)', vol_ratio
        elif vol_ratio >= 1.2:
            return f'量能尚可 ({vol_ratio:.1f}x)', vol_ratio
        else:
            return f'量縮跌破 ({vol_ratio:.1f}x)', vol_ratio
    else:  # consolidation
        # 整理中：量縮較健康
        if vol_ratio <= 0.7:
            return f'量縮沉澱✅ ({vol_ratio:.1f}x)', vol_ratio
        elif vol_ratio <= 1.0:
            return f'量能平穩 ({vol_ratio:.1f}x)', vol_ratio
        else:
            return f'量能偏大⚠️ ({vol_ratio:.1f}x)', vol_ratio


def find_swing_points(df: pd.DataFrame, order: int = 5, pct_threshold: float = 0.03) -> Tuple[np.ndarray, np.ndarray]:
    """
    找 Swing High / Swing Low
    
    改用 ZigZag 演算法（老大強烈推薦）取代原來的 argrelextrema。
    ZigZag 看回撤幅度不看左右幾根K棒 → 完全沒有時間延遲。
    
    邏輯：
    - 設定回撤門檻 pct_threshold (預設 3%)
    - 價格從近期低點反彈超過門檻 → 確認前一個低點
    - 價格從近期高點回檔超過門檻 → 確認前一個高點
    - 點位 100% 貼合真實影線
    
    order 參數保留，只在 ZigZag 找不到足夠點時 fallback。
    """
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    n = len(close)
    
    if n < 10:
        return argrelextrema(df['high'].values, np.greater_equal, order=order)[0], \
               argrelextrema(df['low'].values, np.less_equal, order=order)[0]
    
    # Phase 1: ZigZag 掃描
    zig_highs = []
    zig_lows = []
    
    direction = 0  # 1=up, -1=down, 0=start
    last_high_idx = 0
    last_low_idx = 0
    last_high_price = high[0]
    last_low_price = low[0]
    
    for i in range(1, n):
        if direction >= 0:
            # 正在找高點
            if high[i] > last_high_price:
                last_high_idx = i
                last_high_price = high[i]
            elif (last_high_price - low[i]) / last_high_price >= pct_threshold:
                # 從高點回檔超過門檻 → 確認高點
                zig_highs.append(last_high_idx)
                direction = -1
                last_low_idx = i
                last_low_price = low[i]
        
        if direction <= 0:
            # 正在找低點
            if low[i] < last_low_price:
                last_low_idx = i
                last_low_price = low[i]
            elif (high[i] - last_low_price) / last_low_price >= pct_threshold:
                # 從低點反彈超過門檻 → 確認低點
                zig_lows.append(last_low_idx)
                direction = 1
                last_high_idx = i
                last_high_price = high[i]
        
        if direction == 0:
            # initial direction
            if high[i] > high[0]:
                direction = 1
                last_high_idx = i
                last_high_price = high[i]
            elif low[i] < low[0]:
                direction = -1
                last_low_idx = i
                last_low_price = low[i]
    
    # Phase 2: 加入 Provisional Pivot（解決右側延遲）
    # 最後一段趨勢還沒被確認，直接把最後的極值加入
    if direction == 1 and len(zig_highs) > 0:
        # 最後在上漲趨勢 → 最後的高點是暫定高點
        # 檢查是否大於前一個確認高點
        if high[last_high_idx] > high[zig_highs[-1]] or len(zig_highs) == 0:
            zig_highs.append(last_high_idx)
    elif direction == -1 and len(zig_lows) > 0:
        if low[last_low_idx] < low[zig_lows[-1]] or len(zig_lows) == 0:
            zig_lows.append(last_low_idx)
    
    zig_highs = np.array(sorted(set(zig_highs)))
    zig_lows = np.array(sorted(set(zig_lows)))
    
    # Phase 3: 如果 ZigZag 抓不到足夠點，fallback 到 argrelextrema
    if len(zig_highs) < 2 or len(zig_lows) < 2:
        highs = argrelextrema(df['high'].values, np.greater_equal, order=order)[0]
        lows = argrelextrema(df['low'].values, np.less_equal, order=order)[0]
        return highs, lows
    
    return zig_highs, zig_lows


def detect_head_shoulders_top(df, highs, lows, order=5) -> Optional[PatternResult]:
    """
    頭肩頂偵測：
    - 找最近的三個高點：左肩、頭、右肩
    - 頭 > 左肩 且 頭 > 右肩
    - 左右肩價位接近（差異 < 頭的 3%）
    - 頸線：兩個低點的連線
    """
    if len(highs) < 3:
        return None

    # 取最近的高點
    recent_highs = highs[-5:] if len(highs) >= 5 else highs
    if len(recent_highs) < 3:
        return None

    # 找最高點作為頭
    head_idx = recent_highs[np.argmax(df['high'].iloc[recent_highs])]
    head_pos = np.where(recent_highs == head_idx)[0][0]

    # 需要左肩和右肩
    if head_pos == 0 or head_pos == len(recent_highs) - 1:
        return None

    left_shoulder_idx = recent_highs[head_pos - 1]
    right_shoulder_idx = recent_highs[head_pos + 1]

    head_price = df['high'].iloc[head_idx]
    ls_price = df['high'].iloc[left_shoulder_idx]
    rs_price = df['high'].iloc[right_shoulder_idx]

    # 頭部必須最高
    if head_price <= ls_price or head_price <= rs_price:
        return None

    # 左右肩差異 < 5%
    shoulder_diff = abs(ls_price - rs_price) / head_price
    if shoulder_diff > 0.05:
        return None

    # 找頸線（頭部兩側的低點）
    neckline_low_left = df['low'].iloc[left_shoulder_idx:head_idx+1].min()
    neckline_low_right = df['low'].iloc[head_idx:right_shoulder_idx+1].min()
    neckline = (neckline_low_left + neckline_low_right) / 2

    # 量度目標：頸線到頭部的距離
    target = neckline - (head_price - neckline)
    stop = head_price * 1.02

    # 右肩是否已跌破頸線
    last_close = df['close'].iloc[-1]
    confirmed = last_close < neckline

    confidence = 0.75 if confirmed else 0.55
    # 肩膀越對稱信心越高
    confidence += (1 - shoulder_diff / 0.05) * 0.15

    return PatternResult(
        name_zh='頭肩頂',
        name_en='Head & Shoulders Top',
        category='bearish',
        confidence=min(confidence, 0.95),
        start_idx=left_shoulder_idx,
        end_idx=right_shoulder_idx,
        neckline=neckline,
        target_price=target,
        stop_price=stop,
        points=[
            (left_shoulder_idx, ls_price),
            (head_idx, head_price),
            (right_shoulder_idx, rs_price),
        ],
        description=f'左肩${ls_price:.1f} → 頭${head_price:.1f} → 右肩${rs_price:.1f}，頸線${neckline:.1f}，{"已跌破頸線🔴" if confirmed else "頸線未破觀察中🟡"}',
    )


def detect_head_shoulders_bottom(df, highs, lows, order=5) -> Optional[PatternResult]:
    """
    頭肩底（倒頭肩）偵測：
    - 找最近的三個低點：左肩、頭、右肩
    - 頭 < 左肩 且 頭 < 右肩
    """
    if len(lows) < 3:
        return None

    recent_lows = lows[-5:] if len(lows) >= 5 else lows
    if len(recent_lows) < 3:
        return None

    head_idx = recent_lows[np.argmin(df['low'].iloc[recent_lows])]
    head_pos = np.where(recent_lows == head_idx)[0][0]

    if head_pos == 0 or head_pos == len(recent_lows) - 1:
        return None

    left_shoulder_idx = recent_lows[head_pos - 1]
    right_shoulder_idx = recent_lows[head_pos + 1]

    head_price = df['low'].iloc[head_idx]
    ls_price = df['low'].iloc[left_shoulder_idx]
    rs_price = df['low'].iloc[right_shoulder_idx]

    if head_price >= ls_price or head_price >= rs_price:
        return None

    shoulder_diff = abs(ls_price - rs_price) / abs(head_price) if head_price != 0 else 999
    if shoulder_diff > 0.05:
        return None

    neckline_high_left = df['high'].iloc[left_shoulder_idx:head_idx+1].max()
    neckline_high_right = df['high'].iloc[head_idx:right_shoulder_idx+1].max()
    neckline = (neckline_high_left + neckline_high_right) / 2

    target = neckline + (neckline - head_price)
    stop = head_price * 0.98

    last_close = df['close'].iloc[-1]
    confirmed = last_close > neckline

    confidence = 0.75 if confirmed else 0.55
    confidence += (1 - min(shoulder_diff, 0.05) / 0.05) * 0.15

    return PatternResult(
        name_zh='頭肩底',
        name_en='Inv. Head & Shoulders',
        category='bullish',
        confidence=min(confidence, 0.95),
        start_idx=left_shoulder_idx,
        end_idx=right_shoulder_idx,
        neckline=neckline,
        target_price=target,
        stop_price=stop,
        points=[
            (left_shoulder_idx, ls_price),
            (head_idx, head_price),
            (right_shoulder_idx, rs_price),
        ],
        description=f'左肩${ls_price:.1f} → 頭${head_price:.1f} → 右肩${rs_price:.1f}，頸線${neckline:.1f}，{"突破頸線🟢" if confirmed else "未突破觀察中🟡"}',
    )


def detect_double_top(df, highs, lows) -> Optional[PatternResult]:
    """
    雙重頂（M頭）偵測：
    - 找最近兩個高點接近
    - 中間有一個明顯回檔
    """
    if len(highs) < 2:
        return None

    peak1_idx = highs[-2]
    peak2_idx = highs[-1]
    peak1_price = df['high'].iloc[peak1_idx]
    peak2_price = df['high'].iloc[peak2_idx]

    # 兩個高點差距 < 3%
    if abs(peak1_price - peak2_price) / max(peak1_price, peak2_price) > 0.03:
        return None

    # 中間的低點（頸線）
    trough_idx = (df['low'].iloc[peak1_idx:peak2_idx+1]).idxmin()
    trough_price = df['low'].iloc[peak1_idx:peak2_idx+1].min()

    neckline = trough_price
    pattern_height = max(peak1_price, peak2_price) - neckline
    target = neckline - pattern_height
    stop = max(peak1_price, peak2_price) * 1.02

    last_close = df['close'].iloc[-1]
    confirmed = last_close < neckline

    confidence = 0.70 if confirmed else 0.50

    return PatternResult(
        name_zh='雙重頂（M頭）',
        name_en='Double Top (M)',
        category='bearish',
        confidence=min(confidence, 0.90),
        start_idx=peak1_idx,
        end_idx=peak2_idx,
        neckline=neckline,
        target_price=target,
        stop_price=stop,
        points=[
            (peak1_idx, peak1_price),
            (peak2_idx, peak2_price),
        ],
        description=f'雙頂${peak1_price:.1f}/${peak2_price:.1f}，頸線${neckline:.1f}，{"跌破頸線🔴" if confirmed else "觀察中🟡"}',
    )


def detect_double_bottom(df, highs, lows) -> Optional[PatternResult]:
    """
    雙重底（W底）偵測
    """
    if len(lows) < 2:
        return None

    trough1_idx = lows[-2]
    trough2_idx = lows[-1]
    trough1_price = df['low'].iloc[trough1_idx]
    trough2_price = df['low'].iloc[trough2_idx]

    if abs(trough1_price - trough2_price) / min(trough1_price, trough2_price) > 0.03:
        return None

    neckline = df['high'].iloc[trough1_idx:trough2_idx+1].max()
    pattern_height = neckline - min(trough1_price, trough2_price)
    target = neckline + pattern_height
    stop = min(trough1_price, trough2_price) * 0.98

    last_close = df['close'].iloc[-1]
    confirmed = last_close > neckline

    confidence = 0.70 if confirmed else 0.50

    return PatternResult(
        name_zh='雙重底（W底）',
        name_en='Double Bottom (W)',
        category='bullish',
        confidence=min(confidence, 0.90),
        start_idx=trough1_idx,
        end_idx=trough2_idx,
        neckline=neckline,
        target_price=target,
        stop_price=stop,
        points=[
            (trough1_idx, trough1_price),
            (trough2_idx, trough2_price),
        ],
        description=f'雙底${trough1_price:.1f}/${trough2_price:.1f}，頸線${neckline:.1f}，{"突破頸線🟢" if confirmed else "觀察中🟡"}',
    )


def detect_ascending_triangle(df, highs, lows) -> Optional[PatternResult]:
    """
    上升三角形：
    - 高點趨平（壓力線水平）
    - 低點逐步墊高（支撐線上斜）
    - 看多型態
    """
    if len(highs) < 2 or len(lows) < 2:
        return None

    recent_highs = highs[-3:] if len(highs) >= 3 else highs
    recent_lows = lows[-3:] if len(lows) >= 3 else lows

    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return None

    # 壓力線：高點趨平（標準差 / 均值 < 1.5%）
    high_prices = df['high'].iloc[recent_highs].values
    high_cv = np.std(high_prices) / np.mean(high_prices) if np.mean(high_prices) > 0 else 999

    if high_cv > 0.015:
        return None

    # 支撐線：低點逐步墊高
    low_prices = df['low'].iloc[recent_lows].values
    if len(low_prices) >= 2 and low_prices[-1] <= low_prices[0]:
        # 低點沒有墊高，不是上升三角形
        pass  # still check, might be early

    resistance = np.mean(high_prices)
    confidence = 0.60 + min(high_cv / 0.015, 1) * 0.1  # 越平信心越高

    target = resistance + (resistance - min(low_prices))
    stop = min(low_prices) * 0.97

    return PatternResult(
        name_zh='上升三角形',
        name_en='Ascending Triangle',
        category='bullish',
        confidence=min(confidence, 0.85),
        start_idx=recent_lows[0],
        end_idx=df.index[-1],
        neckline=resistance,
        target_price=target,
        stop_price=stop,
        points=[(i, df['high'].iloc[i]) for i in recent_highs] + [(i, df['low'].iloc[i]) for i in recent_lows],
        description=f'壓力線${resistance:.1f}，低點墊高，看多突破目標${target:.1f}',
    )


def detect_descending_triangle(df, highs, lows) -> Optional[PatternResult]:
    """
    下降三角形：
    - 低點趨平（支撐線水平）
    - 高點逐步降低（壓力線下斜）
    - 看空型態
    """
    if len(highs) < 2 or len(lows) < 2:
        return None

    recent_lows = lows[-3:] if len(lows) >= 3 else lows
    recent_highs = highs[-3:] if len(highs) >= 3 else highs

    if len(recent_lows) < 2:
        return None

    low_prices = df['low'].iloc[recent_lows].values
    low_cv = np.std(low_prices) / np.mean(low_prices) if np.mean(low_prices) > 0 else 999

    if low_cv > 0.015:
        return None

    support = np.mean(low_prices)
    high_prices = df['high'].iloc[recent_highs].values

    # 高點逐步降低
    if len(high_prices) >= 2 and high_prices[-1] >= high_prices[0]:
        return None

    target = support - (max(high_prices) - support)
    stop = max(high_prices) * 1.02

    confidence = 0.60

    return PatternResult(
        name_zh='下降三角形',
        name_en='Descending Triangle',
        category='bearish',
        confidence=min(confidence, 0.85),
        start_idx=recent_highs[0],
        end_idx=df.index[-1],
        neckline=support,
        target_price=target,
        stop_price=stop,
        points=[(i, df['high'].iloc[i]) for i in recent_highs] + [(i, df['low'].iloc[i]) for i in recent_lows],
        description=f'支撐線${support:.1f}，高點降低，看空跌破目標${target:.1f}',
    )


def detect_wedge(df, highs, lows) -> Optional[PatternResult]:
    """
    楔形偵測：
    - 上升楔形（高點墊高+低點墊高但收斂）= 看空
    - 下降楔形（高點降低+低點降低但收斂）= 看多
    """
    if len(highs) < 2 or len(lows) < 2:
        return None

    recent_highs = highs[-3:] if len(highs) >= 3 else highs
    recent_lows = lows[-3:] if len(lows) >= 3 else lows

    if len(recent_highs) < 2 or len(recent_lows) < 2:
        return None

    high_prices = df['high'].iloc[recent_highs].values
    low_prices = df['low'].iloc[recent_lows].values

    high_range = max(high_prices) - min(high_prices)
    low_range = max(low_prices) - min(low_prices)
    price_range = df['close'].iloc[-1]

    if price_range == 0:
        return None

    # 收斂判定：高低範圍差距在縮小
    if len(recent_highs) >= 2 and len(recent_lows) >= 2:
        # 🆕 價格正規化（老大修正）：避免台積電$2300 vs 金融股$50 斜率差百倍
        norm_highs = high_prices / high_prices[0]
        norm_lows = low_prices / low_prices[0]
        
        # 每根K棒平均變化率
        slope_high = (norm_highs[-1] - norm_highs[0]) / len(recent_highs)
        slope_low = (norm_lows[-1] - norm_lows[0]) / len(recent_lows)
        
        # 上升楔形：高點墊高 + 低點墊高
        high_ascending = high_prices[-1] > high_prices[0]
        low_ascending = low_prices[-1] > low_prices[0]

        # 下降楔形：高點降低 + 低點降低
        high_descending = high_prices[-1] < high_prices[0]
        low_descending = low_prices[-1] < low_prices[0]

        if high_ascending and low_ascending:
            # 🆕 上升楔形成立條件加強：支撐線斜率必須 > 壓力線斜率（才有收斂）
            if slope_low <= slope_high:
                return None  # 沒有收斂，不構成楔形
            
            # 🆕 動態信心分數（老大建議）：取代固定 0.60
            # 收斂度 delta_m = 支撐線斜率 - 壓力線斜率
            delta_m = slope_low - slope_high
            # 收斂越快越危險
            convergence_score = min(delta_m * 5.0, 0.30)
            # 高低點觸碰次數越多越可靠
            touch_count = len(recent_highs) + len(recent_lows)
            touch_score = min((touch_count - 4) * 0.05, 0.20) if touch_count > 4 else 0
            
            confidence = 0.40 + convergence_score + touch_score
            
            wedge_range = max(high_prices) - min(low_prices)
            target = min(low_prices) - wedge_range * 0.5
            stop = max(high_prices) * 1.02
            return PatternResult(
                name_zh='上升楔形',
                name_en='Rising Wedge',
                category='bearish',
                confidence=min(confidence, 0.85),
                start_idx=recent_highs[0],
                end_idx=df.index[-1],
                target_price=target,
                stop_price=stop,
                points=[(i, df['high'].iloc[i]) for i in recent_highs] + [(i, df['low'].iloc[i]) for i in recent_lows],
                description=f'壓力+{slope_high*100:.2f}%/K 支撐+{slope_low*100:.2f}%/K 收斂Δ={delta_m*100:.2f}% 目標${target:.1f}',
            )
        elif high_descending and low_descending:
            # 下降楔形 = 看多反轉
            # 🆕 同上升楔形邏輯，用正規化 + 動態信心
            if slope_high >= slope_low:
                return None
            
            delta_m = slope_low - slope_high
            convergence_score = min(abs(delta_m) * 5.0, 0.30)
            touch_count = len(recent_highs) + len(recent_lows)
            touch_score = min((touch_count - 4) * 0.05, 0.20) if touch_count > 4 else 0
            
            confidence = 0.40 + convergence_score + touch_score
            
            wedge_range = max(high_prices) - min(low_prices)
            target = max(high_prices) + wedge_range * 0.5
            stop = min(low_prices) * 0.98
            return PatternResult(
                name_zh='下降楔形',
                name_en='Falling Wedge',
                category='bullish',
                confidence=min(confidence, 0.85),
                start_idx=recent_highs[0],
                end_idx=df.index[-1],
                target_price=target,
                stop_price=stop,
                points=[(i, df['high'].iloc[i]) for i in recent_highs] + [(i, df['low'].iloc[i]) for i in recent_lows],
                description=f'壓力{slope_high*100:.2f}%/K 支撐{slope_low*100:.2f}%/K 收斂Δ={abs(delta_m)*100:.2f}% 目標${target:.1f}',
            )

    return None


def detect_v_reversal(df) -> Optional[PatternResult]:
    """
    V型底偵測（v2.3 改爲V型底/V底反轉，避免與倒V混淆）
    - 急跌後急漲（或反過來）
    - 近期波動 > 15%
    - 只找最近60根K線
    - 底部含打底區 → 降信心（偏W底/破底翻）
    """
    if len(df) < 10:
        return None

    # 🔧 只找最近60根K線（Blind Spot B修正）
    lookback = min(60, len(df))
    recent = df.tail(lookback).copy().reset_index(drop=True)
    offset = len(df) - len(recent)  # recent在全局df中的起始位置

    trough_idx = recent['low'].idxmin()
    trough_price = recent['low'].min()

    # 低點前：下跌段
    pre_trough = recent.loc[:trough_idx]
    # 低點後：反彈段
    post_trough = recent.loc[trough_idx:]

    if len(pre_trough) < 3 or len(post_trough) < 3:
        return None

    pre_high = pre_trough['high'].max()
    post_high = post_trough['high'].max()

    drop_pct = (pre_high - trough_price) / pre_high if pre_high > 0 else 0
    bounce_pct = (post_high - trough_price) / trough_price if trough_price > 0 else 0

    # 急跌 > 15% + 急漲 > 10%
    if drop_pct > 0.15 and bounce_pct > 0.10:
        # v2.3 老大建議：檢查底部是否含「打底區」（數日窄幅整理）
        # 若有 → 更偏向W底/破底翻，減少V底信心
        trough_window = recent.loc[max(0, trough_idx-3):min(len(recent)-1, trough_idx+3)]
        trough_range = trough_window['high'].max() - trough_window['low'].min()
        base_adjust = 0
        base_note = ''
        if not trough_window.empty and trough_price > 0:
            trough_range_pct = trough_range / trough_price
            if trough_range_pct < 0.05:  # 底部窄幅<5% → 有打底
                base_adjust = -0.10  # 降信心10%
                base_note = '，含打底區（偏W底破底翻）'
        
        conf = min(0.55 + bounce_pct * 0.5, 0.85) + base_adjust
        return PatternResult(
            name_zh='V型底/V底反轉',
            name_en='V-Bottom Reversal',
            category='bullish',
            confidence=max(conf, 0.30),
            start_idx=offset,
            end_idx=len(df)-1,
            target_price=post_high * 1.05,
            stop_price=trough_price * 0.97,
            points=[
                (offset, pre_high),
                (offset + trough_idx, trough_price),
                (len(df)-1, post_high),
            ],
            description=f'急跌{drop_pct*100:.0f}%後反彈{bounce_pct*100:.0f}%{base_note}，V底成形',
            timeframe='medium',
        )

    # 倒V（急漲後急跌）
    peak_idx = recent['high'].idxmax()
    peak_price = recent['high'].max()

    pre_peak = recent.loc[:peak_idx]
    post_peak = recent.loc[peak_idx:]

    if len(pre_peak) < 3 or len(post_peak) < 3:
        return None

    pre_low = pre_peak['low'].min()
    post_low = post_peak['low'].min()

    rise_pct = (peak_price - pre_low) / pre_low if pre_low > 0 else 0
    drop_pct2 = (peak_price - post_low) / peak_price if peak_price > 0 else 0

    if rise_pct > 0.15 and drop_pct2 > 0.10:
        return PatternResult(
            name_zh='倒V型反轉',
            name_en='Inverted V (Top Reversal)',
            category='bearish',
            confidence=min(0.55 + drop_pct2 * 0.5, 0.85),
            start_idx=offset,  # 🔧 只從最近60根開始
            end_idx=len(df)-1,
            target_price=post_low * 0.95,
            stop_price=peak_price * 1.02,
            points=[
                (0, pre_low),
                (peak_idx, peak_price),
                (len(recent)-1, post_low),
            ],
            description=f'急漲{rise_pct*100:.0f}%後回跌{drop_pct2*100:.0f}%，倒V成形',
        )

    return None


def detect_cup_handle(df, highs, lows) -> Optional[PatternResult]:
    """
    杯柄型態偵測：
    - 圓弧杯底 + 右杯緣回到前高附近 + 短期回檔（把手）
    - 出現在上升趨勢中更有效
    - 突破杯緣 = 看多訊號
    """
    if len(df) < 30:
        return None
    
    recent = df.tail(min(60, len(df))).copy().reset_index(drop=True)
    if len(recent) < 30:
        return None
    
    # 找左杯緣（前期高點）和杯底（中期低點）
    left_third = recent.iloc[:len(recent)//3]
    mid_third = recent.iloc[len(recent)//3:2*len(recent)//3]
    right_third = recent.iloc[2*len(recent)//3:]
    
    cup_rim = left_third['high'].max()  # 杯緣高點
    cup_bottom = mid_third['low'].min()  # 杯底低點
    right_rim = right_third['high'].max()  # 右杯緣
    
    if cup_rim <= 0:
        return None
    
    # 杯底深度：至少8%回檔，但不要太深（>35%不像杯柄）
    cup_depth = (cup_rim - cup_bottom) / cup_rim
    if cup_depth < 0.08 or cup_depth > 0.35:
        return None
    
    # 右杯緣要回到左杯緣附近（差距<5%）
    rim_diff = abs(right_rim - cup_rim) / cup_rim
    if rim_diff > 0.05:
        return None
    
    # 把手回檔不要太深（<杯深的50%）
    handle_low = right_third['low'].min()
    handle_depth = (right_rim - handle_low) / (cup_rim - cup_bottom) if (cup_rim - cup_bottom) > 0 else 999
    if handle_depth > 0.5:
        return None
    
    # 量度目標：杯緣 + 杯深
    target = cup_rim + (cup_rim - cup_bottom)
    stop = handle_low * 0.97
    
    # 確認：是否已突破杯緣
    last_close = recent['close'].iloc[-1]
    confirmed = last_close > cup_rim
    confidence = 0.70 if confirmed else 0.50
    confidence += min(cup_depth / 0.2, 0.15)  # 杯深越深信心略高
    
    return PatternResult(
        name_zh='杯柄型態',
        name_en='Cup & Handle',
        category='bullish',
        confidence=min(confidence, 0.88),
        start_idx=0,
        end_idx=len(df)-1,
        neckline=cup_rim,
        target_price=target,
        stop_price=stop,
        points=[(0, cup_rim), (len(recent)//2, cup_bottom), (len(recent)-1, right_rim)],
        description=f'杯緣${cup_rim:.1f}→杯底${cup_bottom:.1f}（回檔{cup_depth*100:.0f}%），{"突破杯緣🟢" if confirmed else "觀察中🟡"}，目標${target:.1f}',
    )


def detect_triple_top(df, highs) -> Optional[PatternResult]:
    """
    三重頂偵測：
    - 三個高點接近同一壓力區
    - 比M頭多一次測試，更強的看空訊號
    """
    if len(highs) < 3:
        return None
    
    recent = highs[-5:] if len(highs) >= 5 else highs
    if len(recent) < 3:
        return None
    
    peak_prices = df['high'].iloc[recent].values
    avg_peak = np.mean(peak_prices)
    
    # 三個高點差距 < 3%
    for p in peak_prices:
        if abs(p - avg_peak) / avg_peak > 0.03:
            return None
    
    # 找兩個谷底（頸線）
    neck_low1 = df['low'].iloc[recent[0]:recent[1]].min()
    neck_low2 = df['low'].iloc[recent[1]:recent[2]].min()
    neckline = (neck_low1 + neck_low2) / 2
    
    pattern_height = avg_peak - neckline
    target = neckline - pattern_height
    stop = max(peak_prices) * 1.02 if max(peak_prices) > 0 else None
    
    last_close = df['close'].iloc[-1]
    confirmed = last_close < neckline
    confidence = 0.72 if confirmed else 0.52
    
    return PatternResult(
        name_zh='三重頂',
        name_en='Triple Top',
        category='bearish',
        confidence=min(confidence, 0.85),
        start_idx=recent[0],
        end_idx=recent[-1],
        neckline=neckline,
        target_price=target,
        stop_price=stop,
        points=[(i, df['high'].iloc[i]) for i in recent[:3]],
        description=f'三高${avg_peak:.1f}測壓失敗，頸線${neckline:.1f}，{"跌破🔴" if confirmed else "觀察中🟡"}',
    )


def detect_triple_bottom(df, lows) -> Optional[PatternResult]:
    """
    三重底偵測：
    - 三個低點接近同一支撐區
    - 比W底多一次測試，更強的看多訊號
    """
    if len(lows) < 3:
        return None
    
    recent = lows[-5:] if len(lows) >= 5 else lows
    if len(recent) < 3:
        return None
    
    trough_prices = df['low'].iloc[recent].values
    avg_trough = np.mean(trough_prices)
    
    for p in trough_prices:
        if abs(p - avg_trough) / avg_trough > 0.03:
            return None
    
    neck_high1 = df['high'].iloc[recent[0]:recent[1]].max()
    neck_high2 = df['high'].iloc[recent[1]:recent[2]].max()
    neckline = (neck_high1 + neck_high2) / 2
    
    pattern_height = neckline - avg_trough
    target = neckline + pattern_height
    stop = min(trough_prices) * 0.97
    
    last_close = df['close'].iloc[-1]
    confirmed = last_close > neckline
    confidence = 0.72 if confirmed else 0.52
    
    return PatternResult(
        name_zh='三重底',
        name_en='Triple Bottom',
        category='bullish',
        confidence=min(confidence, 0.85),
        start_idx=recent[0],
        end_idx=recent[-1],
        neckline=neckline,
        target_price=target,
        stop_price=stop,
        points=[(i, df['low'].iloc[i]) for i in recent[:3]],
        description=f'三低${avg_trough:.1f}測撐成功，頸線${neckline:.1f}，{"突破🟢" if confirmed else "觀察中🟡"}',
    )


def detect_box_range(df, highs, lows) -> Optional[PatternResult]:
    """
    箱型整理偵測：
    - 價格在固定支撐與壓力間來回
    - 支撐和壓力大致水平
    - 突破箱頂看多，跌破箱底看空
    """
    if len(df) < 20:
        return None
    
    recent = df.tail(min(40, len(df))).copy()
    
    # 找高點和低點的 rough 水平線
    high_rolling = recent['high'].rolling(5, center=True).max()
    low_rolling = recent['low'].rolling(5, center=True).min()
    
    resistance = high_rolling.max()
    support = low_rolling.min()
    
    if resistance <= 0 or support <= 0:
        return None
    
    box_range = (resistance - support) / support
    
    # 箱型範圍要在 5-25% 之間（太小不是箱型，太大是趨勢）
    if box_range < 0.05 or box_range > 0.25:
        return None
    
    # 檢查是否多次測試支撐和壓力
    touch_resistance = (recent['high'] >= resistance * 0.98).sum()
    touch_support = (recent['low'] <= support * 1.02).sum()
    
    if touch_resistance < 2 or touch_support < 2:
        return None
    
    last_close = recent['close'].iloc[-1]
    last_high = recent['high'].iloc[-1]
    last_low = recent['low'].iloc[-1]
    
    # 判斷方向
    if last_close > resistance:
        confirmed = True
        category = 'bullish'
        target = resistance + (resistance - support)
        stop = support
        desc_suffix = f'突破箱頂🟢'
    elif last_close < support:
        confirmed = True
        category = 'bearish'
        target = support - (resistance - support)
        stop = resistance
        desc_suffix = f'跌破箱底🔴'
    else:
        confirmed = False
        category = 'neutral'
        target = None
        stop = None
        desc_suffix = f'箱內整理中🟡'
    
    confidence = 0.65 if confirmed else 0.45
    confidence += min(touch_resistance + touch_support - 4, 4) * 0.03  # 測試越多越可靠
    
    return PatternResult(
        name_zh='箱型整理',
        name_en='Box Range',
        category=category,
        confidence=min(confidence, 0.82),
        start_idx=0,
        end_idx=len(df)-1,
        neckline=resistance if category != 'bearish' else support,
        target_price=target,
        stop_price=stop,
        points=[],
        description=f'箱頂${resistance:.1f}/箱底${support:.1f}（範圍{box_range*100:.0f}%），測頂{touch_resistance}次/測底{touch_support}次，{desc_suffix}',
    )


def detect_rounding(df) -> Optional[PatternResult]:
    """
    圓弧頂/底偵測：
    - 價格逐步轉向，沒有明顯的V型反轉
    - 用迴歸曲率判斷
    """
    if len(df) < 30:
        return None
    
    recent = df.tail(min(50, len(df))).copy().reset_index(drop=True)
    if len(recent) < 30:
        return None
    
    # 用 close 的線性迴歸殘差判斷曲率
    x = np.arange(len(recent))
    y = recent['close'].values
    
    # 線性迴歸
    coeffs = np.polyfit(x, y, 1)
    linear_fit = np.polyval(coeffs, x)
    residuals = y - linear_fit
    
    # 二次曲率：用殘差對 x 的二次迴歸
    curve_coeffs = np.polyfit(x, residuals, 2)
    curvature = curve_coeffs[0]  # 二次項係數
    
    # 歸一化曲率
    price_range = y.max() - y.min()
    if price_range == 0:
        return None
    
    norm_curvature = curvature * (len(recent)**2) / price_range
    
    # 曲率絕對值要夠大（明顯的弧形）
    if abs(norm_curvature) < 0.05:
        return None
    
    # 判斷頂還是底
    if norm_curvature < -0.05:
        # 圓弧頂（concave down）
        name_zh = '圓弧頂'
        name_en = 'Rounding Top'
        category = 'bearish'
        confidence = min(abs(norm_curvature) * 5, 0.75)
        
        # 🆕 MA60 乖離濾網（老大建議）：避免主升段飆股誤判
        if len(df) >= 65:
            ma60 = df['close'].rolling(60).mean()
            ma60_val = ma60.iloc[-1]
            if not np.isnan(ma60_val) and ma60_val > 0:
                last_close = df['close'].iloc[-1]
                ma60_div = (last_close - ma60_val) / ma60_val
                if ma60_div > 0.15:
                    ma60_5d_ago = ma60.iloc[-5]
                    if not np.isnan(ma60_5d_ago) and ma60_5d_ago > 0:
                        ma60_slope = (ma60_val - ma60_5d_ago) / ma60_5d_ago
                        if ma60_slope > 0.005:
                            confidence *= 0.5
                            desc = f'逐步反轉向下，曲率{norm_curvature:.2f} | MA60乖離{ma60_div*100:.0f}%⚠️ 信心減半'
                        else:
                            desc = f'逐步反轉向下，曲率{norm_curvature:.2f}'
                    else:
                        desc = f'逐步反轉向下，曲率{norm_curvature:.2f}'
                else:
                    desc = f'逐步反轉向下，曲率{norm_curvature:.2f}'
            else:
                desc = f'逐步反轉向下，曲率{norm_curvature:.2f}'
        else:
            desc = f'逐步反轉向下，曲率{norm_curvature:.2f}'
        
        target_price = y.min() - (y.max() - y.min()) * 0.3
        stop_price = y.max() * 1.02
    elif norm_curvature > 0.05:
        # 圓弧底（concave up）
        name_zh = '圓弧底'
        name_en = 'Rounding Bottom'
        category = 'bullish'
        confidence = min(abs(norm_curvature) * 5, 0.75)
        target_price = y.max() + (y.max() - y.min()) * 0.3
        stop_price = y.min() * 0.98
        desc = f'逐步築底向上，曲率{norm_curvature:.2f}'
    else:
        return None
    
    return PatternResult(
        name_zh=name_zh,
        name_en=name_en,
        category=category,
        confidence=confidence,
        start_idx=0,
        end_idx=len(df)-1,
        target_price=target_price,
        stop_price=stop_price,
        points=[],
        description=desc,
    )





def detect_flag(df, highs, lows) -> Optional[PatternResult]:
    """
    旗形偵測：
    - 前期急漲/急跌（旗桿）
    - 跟隨收斂的平行通道（旗面）
    """
    if len(df) < 20:
        return None

    recent = df.tail(20).copy().reset_index(drop=True)

    # 找最大漲幅段（旗桿）
    pct_change = recent['close'].pct_change().cumsum()
    max_rise = pct_change.max() - pct_change.min()

    if max_rise < 0.20:  # 旗桿至少 20%
        return None

    peak_idx = pct_change.idxmax()
    trough_idx = pct_change.idxmin()

    if peak_idx > trough_idx:
        # 先漲後回 = 看多旗形
        flag_type = 'bull'
        pole_high = recent['high'].iloc[:peak_idx+1].max()
        pole_low = recent['low'].iloc[:trough_idx+1].min()
    else:
        # 先跌後盤 = 看空旗形
        flag_type = 'bear'
        pole_high = recent['high'].iloc[:trough_idx+1].max()
        pole_low = recent['low'].iloc[:peak_idx+1].min()

    pole_height = pole_high - pole_low

    if flag_type == 'bull':
        target = pole_high + pole_height * 0.5  # 旗形目標 = 桿高 + 50%
        stop = pole_low
        name_zh = '看多旗形'
        name_en = 'Bull Flag'
        category = 'bullish'
    else:
        target = pole_low - pole_height * 0.5
        stop = pole_high
        name_zh = '看空旗形'
        name_en = 'Bear Flag'
        category = 'bearish'

    return PatternResult(
        name_zh=name_zh,
        name_en=name_en,
        category=category,
        confidence=0.55,
        start_idx=0,
        end_idx=len(recent)-1,
        target_price=target,
        stop_price=stop,
        points=[(trough_idx, pole_low), (peak_idx, pole_high)],
        description=f'旗桿高度${pole_height:.1f}，量度目標${target:.1f}',
    )



def detect_candlestick_patterns(df) -> List[PatternResult]:
    """
    🆕 K線型態偵測（老大手寫筆記買入/賣出型態表）
    短線轉折訊號（1-3根K線），與圖表型態（10-200根K線）互補。
    """
    results = []
    if len(df) < 5:
        return results
    
    close = df['close'].values
    open_ = df['open'].values
    high = df['high'].values
    low = df['low'].values
    
    body = np.abs(close - open_)
    upper_shadow = high - np.maximum(close, open_)
    lower_shadow = np.minimum(close, open_) - low
    candle_range = high - low
    tr = high - low
    tr = np.where(tr == 0, 0.001, tr)
    body_ratio = body / tr
    idx = len(df) - 1
    
    if idx < 2:
        return results
    
    # 趨勢方向
    if idx >= 5:
        rc = close[idx-5:idx+1]
        slope = (rc[-1] - rc[0]) / rc[0] if rc[0] > 0 else 0
        downtrend = slope < -0.03
        uptrend = slope > 0.03
    else:
        downtrend = uptrend = False
    
    # ─── 買入型態 ───
    # 1. 錘頭線
    if (downtrend and lower_shadow[idx] > body[idx] * 2
        and upper_shadow[idx] < body[idx] * 0.3 and body_ratio[idx] < 0.4):
        results.append(PatternResult(
            name_zh='錘頭線', name_en='Hammer', category='bullish',
            confidence=0.55, start_idx=idx-1, end_idx=idx,
            points=[(idx, close[idx])],
            description=f'下跌後長下影({lower_shadow[idx]:.1f}>{body[idx]:.1f}x2)，低檔承接 🟢'))
    
    # 2. 晨星
    if (idx >= 2 and downtrend
        and body[idx-2]/tr[idx-2] > 0.6 and close[idx-2] < open_[idx-2]
        and body[idx-1]/tr[idx-1] < 0.3
        and body[idx]/tr[idx] > 0.5 and close[idx] > open_[idx]
        and close[idx] > (open_[idx-2] + close[idx-2]) / 2):
        results.append(PatternResult(
            name_zh='晨星', name_en='Morning Star', category='bullish',
            confidence=0.68, start_idx=idx-2, end_idx=idx,
            points=[(idx-2, close[idx-2]), (idx, close[idx])],
            description='下跌末端黑K→小K→紅K，多頭反攻 🟢'))
    
    # 3. 多頭吞噬 / 微小燭+錘頭線
    if (idx >= 1 and close[idx-1] < open_[idx-1] and close[idx] > open_[idx]
        and open_[idx] < close[idx-1] and close[idx] > open_[idx-1]):
        engulf_r = body[idx] / (body[idx-1] + 0.001)
        if engulf_r > 1.2:
            prev_body_r = body[idx-1] / (candle_range[idx-1] + 0.001)
            if prev_body_r < 0.25 and lower_shadow[idx-1] > body[idx-1] * 2:
                results.append(PatternResult(
                    name_zh='微小燭+錘頭線+吞噬', name_en='Doji-Hammer-Engulf',
                    category='bullish', confidence=0.72, start_idx=idx-1, end_idx=idx,
                    points=[(idx-1, min(close[idx-1], open_[idx-1])), (idx, close[idx])],
                    description='猶豫(微小燭)+承接(錘頭)+反攻(吞噬)=強烈底部 🟢'))
            else:
                conf = min(0.55 + engulf_r * 0.05, 0.75)
                results.append(PatternResult(
                    name_zh='多頭吞噬', name_en='Bullish Engulfing',
                    category='bullish', confidence=conf, start_idx=idx-1, end_idx=idx,
                    points=[(idx-1, close[idx-1]), (idx, close[idx])],
                    description=f'紅K包黑K，多頭強勢反攻 🟢'))
    
    # ─── 賣出型態 ───
    # 4. 射擊之星
    if (uptrend and upper_shadow[idx] > body[idx] * 2
        and lower_shadow[idx] < body[idx] * 0.3 and body_ratio[idx] < 0.4):
        results.append(PatternResult(
            name_zh='射擊之星', name_en='Shooting Star', category='bearish',
            confidence=0.55, start_idx=idx-1, end_idx=idx,
            points=[(idx, close[idx])],
            description=f'上漲後長上影({upper_shadow[idx]:.1f}>{body[idx]:.1f}x2)，高檔賣壓 🔴'))
    
    # 5. 黃昏星
    if (idx >= 2 and uptrend
        and body[idx-2]/tr[idx-2] > 0.6 and close[idx-2] > open_[idx-2]
        and body[idx-1]/tr[idx-1] < 0.3
        and body[idx]/tr[idx] > 0.5 and close[idx] < open_[idx]
        and close[idx] < (open_[idx-2] + close[idx-2]) / 2):
        results.append(PatternResult(
            name_zh='黃昏星', name_en='Evening Star', category='bearish',
            confidence=0.68, start_idx=idx-2, end_idx=idx,
            points=[(idx-2, close[idx-2]), (idx, close[idx])],
            description='上漲末端紅K→小K→黑K，空頭逆襲 🔴'))
    
    # 6. 黑三兵
    if (idx >= 2
        and all(close[idx-i] < open_[idx-i] for i in range(3))
        and all(close[idx-i] < close[idx-i-1] for i in range(2))
        and all(body[idx-i]/(candle_range[idx-i]+0.001) > 0.4 for i in range(3))):
        results.append(PatternResult(
            name_zh='黑三兵', name_en='Three Black Crows', category='bearish',
            confidence=0.62, start_idx=idx-2, end_idx=idx,
            points=[(idx-i, close[idx-i]) for i in range(3)],
            description='連續三根黑K，空方通吃 🔴'))
    
    # 7. 空頭吞噬
    if (idx >= 1 and uptrend
        and close[idx-1] > open_[idx-1] and close[idx] < open_[idx]
        and open_[idx] > close[idx-1] and close[idx] < open_[idx-1]):
        results.append(PatternResult(
            name_zh='空頭吞噬', name_en='Bearish Engulfing', category='bearish',
            confidence=0.58, start_idx=idx-1, end_idx=idx,
            points=[(idx-1, close[idx-1]), (idx, close[idx])],
            description='黑K包紅K，空方強勢反殺 🔴'))
    
    return results


def detect_support_resistance(df) -> List[PatternResult]:
    """🆕 支撐/壓力偵測（老大：跌破支撐線是重要賣出訊號）"""
    results = []
    if len(df) < 15:
        return results
    recent = df.tail(min(30, len(df)))
    lows = argrelextrema(recent['low'].values, np.less_equal, order=3)[0]
    if len(lows) < 2:
        return results
    low_prices = recent['low'].iloc[lows].values
    last_close = df['close'].iloc[-1]
    for price in low_prices:
        nearby = low_prices[abs(low_prices - price) / price < 0.02]
        if len(nearby) >= 2:
            if last_close < price * 0.97:
                results.append(PatternResult(
                    name_zh='跌破支撐線', name_en='Support Breakdown',
                    category='bearish', confidence=0.60,
                    start_idx=0, end_idx=len(df)-1, neckline=price,
                    target_price=price * 0.95, stop_price=price * 1.02,
                    description=f'跌破近期支撐${price:.1f}（{len(nearby)}次測試），支撐轉壓力 🔴'))
            break
    return results


def detect_parallel_bottom(df) -> Optional[PatternResult]:
    """🆕 平行底（老大：多次在同一區域獲得支撐）"""
    if len(df) < 15:
        return None
    recent = df.tail(min(40, len(df)))
    lows = argrelextrema(recent['low'].values, np.less_equal, order=3)[0]
    if len(lows) < 2:
        return None
    lp = recent['low'].iloc[lows].values
    avg = np.mean(lp)
    cv = np.std(lp) / avg if avg > 0 else 999
    if cv < 0.025:
        confirmed = recent['close'].iloc[-1] > avg * 1.03
        return PatternResult(
            name_zh='平行底', name_en='Parallel Bottom', category='bullish',
            confidence=0.55 if confirmed else 0.45,
            start_idx=0, end_idx=len(df)-1, neckline=avg,
            target_price=avg * 1.08, stop_price=avg * 0.96,
            description=f'{len(lp)}次測試${avg:.1f}支撐(CV={cv*100:.1f}%)，{"脫離底部🟢" if confirmed else "盤整中🟡"}')
    return None


def detect_ma_cross(df) -> List[PatternResult]:
    """
    🆕 均線交叉偵測（老大手寫筆記框架）
    
    核心邏輯：
    - 黃金交叉 + 長期線上升中 = ✅ 買入
    - 黃金交叉 + 長期線下降中 = ❌ 不要買（假黃金交叉）
    - 死亡交叉 + 長期線下降中 = ✅ 賣出
    - 死亡交叉 + 長期線上升中 = ❌ 不要賣（假死亡交叉）
    
    交叉組合（依老大筆記）：
    - 短線：MA5 / MA50
    - 中線：MA10 / MA100
    - 長線：MA20 / MA200
    """
    results = []
    
    # 計算需要的均線
    ma_pairs = [
        ('ma5', 'ma50', 5, 50, '短線'),
        ('ma10', 'ma100', 10, 100, '中線'),
        ('ma20', 'ma200', 20, 200, '長線'),
    ]
    
    for short_name, long_name, short_w, long_w, timeframe in ma_pairs:
        # 計算均線（如果還沒算）
        if short_name not in df.columns:
            if len(df) >= short_w:
                df[short_name] = df['close'].rolling(short_w).mean()
            else:
                continue
        if long_name not in df.columns:
            if len(df) >= long_w:
                df[long_name] = df['close'].rolling(long_w).mean()
            else:
                continue
        
        short_ma = df[short_name]
        long_ma = df[long_name]
        
        # 需要至少2筆有效數據
        valid = short_ma.notna() & long_ma.notna()
        if valid.sum() < 3:
            continue
        
        # 最近兩天的交叉狀態
        curr_short = short_ma.iloc[-1]
        curr_long = long_ma.iloc[-1]
        prev_short = short_ma.iloc[-2]
        prev_long = long_ma.iloc[-2]
        
        if pd.isna(curr_short) or pd.isna(curr_long) or pd.isna(prev_short) or pd.isna(prev_long):
            continue
        
        # 判斷長期均線方向（近5日斜率）
        long_slope_window = min(5, valid.sum())
        long_recent = long_ma.iloc[-long_slope_window:].dropna()
        if len(long_recent) >= 3:
            long_slope = (long_recent.iloc[-1] - long_recent.iloc[0]) / long_recent.iloc[0]
            long_rising = long_slope > 0.001  # 0.1% 門檻
        else:
            long_rising = None  # 數據不足判斷
        
        # 黃金交叉：短期穿過長期向上
        if prev_short <= prev_long and curr_short > curr_long:
            if long_rising is True:
                # ✅ 真黃金交叉
                results.append(PatternResult(
                    name_zh=f'黃金交叉({timeframe})',
                    name_en=f'Golden Cross ({short_w}/{long_w})',
                    category='bullish',
                    confidence=0.78,
                    start_idx=len(df)-3,
                    end_idx=len(df)-1,
                    target_price=curr_short * 1.05,  # 粗估目標
                    stop_price=curr_short * 0.97,
                    volume_confirm=None,
                    volume_ratio=None,
                    confirmed=True,
                    description=f'MA{short_w}上穿MA{long_w}，長期線上升中→真黃金交叉✅，看多訊號',
                ))
            elif long_rising is False:
                # ❌ 假黃金交叉
                results.append(PatternResult(
                    name_zh=f'假黃金交叉({timeframe})',
                    name_en=f'False Golden Cross ({short_w}/{long_w})',
                    category='neutral',
                    confidence=0.45,
                    start_idx=len(df)-3,
                    end_idx=len(df)-1,
                    target_price=None,
                    stop_price=curr_short * 0.97,
                    volume_confirm=None,
                    volume_ratio=None,
                    confirmed=False,
                    description=f'MA{short_w}上穿MA{long_w}，但長期線下降中→假黃金交叉❌，不要買',
                ))
        
        # 死亡交叉：短期穿過長期向下
        elif prev_short >= prev_long and curr_short < curr_long:
            if long_rising is False:
                # ✅ 真死亡交叉
                results.append(PatternResult(
                    name_zh=f'死亡交叉({timeframe})',
                    name_en=f'Death Cross ({short_w}/{long_w})',
                    category='bearish',
                    confidence=0.78,
                    start_idx=len(df)-3,
                    end_idx=len(df)-1,
                    target_price=curr_short * 0.93,
                    stop_price=curr_short * 1.03,
                    volume_confirm=None,
                    volume_ratio=None,
                    confirmed=True,
                    description=f'MA{short_w}下穿MA{long_w}，長期線下降中→真死亡交叉✅，看空訊號',
                ))
            elif long_rising is True:
                # ❌ 假死亡交叉
                results.append(PatternResult(
                    name_zh=f'假死亡交叉({timeframe})',
                    name_en=f'False Death Cross ({short_w}/{long_w})',
                    category='neutral',
                    confidence=0.45,
                    start_idx=len(df)-3,
                    end_idx=len(df)-1,
                    target_price=None,
                    stop_price=curr_short * 1.03,
                    volume_confirm=None,
                    volume_ratio=None,
                    confirmed=False,
                    description=f'MA{short_w}下穿MA{long_w}，但長期線上升中→假死亡交叉❌，不要賣',
                ))
    
    return results


# ═══════════════════════════════════════════
# 🧮 v3.0 entryQuality 進場品質計算引擎
# 老大2026-06-09規格：分數拆分、波動率正規化、共線因子塌
# ═══════════════════════════════════════════

class EntryQualityCalculator:
    """
    v3.0 老大規範：
    - patternScore（型態辨識度）與 entryQuality（進場品質）完全分離
    - 所有閾值用 ATR 波動率正規化（跨股票通用）
    - 共線的四個延伸因子 → 單一 composite position score
    - 階梯函數 → 連續斜坡（linear ramp）
    - 正交風險獨立計算：vol_climax、RSI背離、趨勢方向
    """

    def __init__(self, df: pd.DataFrame, atr_period: int = 14):
        self.df = df
        self.last = df.iloc[-1]
        self.last_close = float(self.last['close'])
        self.atr = self._calc_atr(atr_period)

    def calc(self, pattern: PatternResult) -> dict:
        """計算 entryQuality 及行動建議，返回完整診斷"""
        result = {'pattern_score': pattern.confidence}

        # ① Composite Position Score（老大 v3.0 核心）
        # 取代 dev_signal + rally_low + dev_ma20 + pullback 四個共線因子
        # 用 df['low'] 確保跨 pattern 的 consistent swing_low
        swing_low = self.df['low'].iloc[pattern.start_idx:pattern.end_idx+1].min() if pattern.start_idx < len(self.df) else None
        if swing_low is not None and swing_low > 0 and self.atr > 0:
            dist_atr = (self.last_close - swing_low) / self.atr
            # 老大規範：連續斜坡——從 1x ATR 輕罰（10），3x ATR 滿罰（40）
            position_penalty = self._ramp(dist_atr, start=1.0, end=3.0, max_penalty=40)
        else:
            position_penalty = 0
        result['position'] = position_penalty

        # ② Dev from MA——也用 ATR 正規化
        for ma_col, max_p in [('ma20', 20), ('ma60', 15)]:
            if ma_col in self.df.columns:
                ma_val = self.last.get(ma_col)
                if pd.notna(ma_val) and ma_val > 0:
                    dev_atr = abs(self.last_close - ma_val) / self.atr
                    result[f'dev_{ma_col}'] = self._ramp(dev_atr, start=1.0, end=2.5, max_penalty=max_p)
                else:
                    result[f'dev_{ma_col}'] = 0
            else:
                result[f'dev_{ma_col}'] = 0

        # ③ 派發量偵測（vol_climax）——正交風險
        result['vol_climax'] = self._detect_vol_climax() * 25

        # ④ RSI 頂背離——正交風險
        result['rsi_div'] = self._detect_rsi_divergence() * 30

        # ⑤ 趨勢方向——正交風險：季線向下 + 在季線下 = 強烈不進場
        result['trend'] = self._trend_penalty(ma_period=60)

        # 總合 penalty → entryQuality
        total_penalty = sum(v for k, v in result.items() if k != 'action' and k != 'entry_quality')
        entry_quality = max(0, min(100, 100 - total_penalty))
        result['entry_quality'] = entry_quality

        # 老大 v0 假設：≥60 可進、30-59 觀望、<30 不進
        # （等 §2.2 回測來校準這組切點）
        # 老大複審：patternScore 低於 60 時直接跳過
        if result.get('pattern_score', 0) < 0.6:
            result['action'] = '形狀不足以判斷'
        elif entry_quality >= 60:
            result['action'] = '作多（進場）'
        elif entry_quality >= 30:
            result['action'] = '觀望／等止跌'
        else:
            result['action'] = '不宜進場'

        return result

    def _calc_atr(self, period: int) -> float:
        """Average True Range（波動率單位）"""
        if len(self.df) < period + 1:
            return 1.0
        high, low, close = self.df['high'].values, self.df['low'].values, self.df['close'].values
        tr = np.maximum(high[1:] - low[1:],
                        np.maximum(np.abs(high[1:] - close[:-1]),
                                   np.abs(low[1:] - close[:-1])))
        atr = pd.Series(tr).rolling(period).mean().iloc[-1]
        return atr if pd.notna(atr) and atr > 0 else 1.0

    @staticmethod
    def _ramp(value: float, start: float, end: float, max_penalty: float) -> float:
        """
        連續斜坡函數（老大規格：取代階梯懸崖）
        - value <= start → 0
        - value >= end → max_penalty
        - 中間線性插值
        """
        if value <= start:
            return 0.0
        if value >= end:
            return float(max_penalty)
        return max_penalty * (value - start) / (end - start)

    def _detect_vol_climax(self, window: int = 5) -> float:
        """
        高檔爆量紅K→爆量黑K 派發模式偵測
        - 最近 window×2 根K棒內尋找
        - 爆量 = > 20日均量的 2x
        - 紅K隔日黑K = 典型派發
        """
        if len(self.df) < window * 2 + 20:
            return 0.0
        avg_vol = self.df['volume'].rolling(20).mean().iloc[-1]
        if avg_vol <= 0:
            return 0.0
        recent = self.df.tail(window * 2)
        climax_pairs = 0
        for i in range(len(recent) - 1):
            if recent['volume'].iloc[i] > avg_vol * 2:
                if recent['close'].iloc[i] > recent['open'].iloc[i]:
                    if recent['close'].iloc[i+1] < recent['open'].iloc[i+1]:
                        climax_pairs += 1
        return min(climax_pairs / 2.0, 1.0)

    def _detect_rsi_divergence(self) -> float:
        """
        RSI 頂背離偵測（同時指標，非領先）
        - 價格創近20根新高但 RSI 沒有
        - 只抓得到「正在頭上」時，抓不到「剛摔下來」
        """
        if 'rsi' not in self.df.columns or len(self.df) < 20:
            return 0.0
        recent = self.df.tail(20)
        price_high_idx = recent['high'].idxmax()
        rsi_high_idx = recent['rsi'].idxmax()
        last_rsi = recent['rsi'].iloc[-1]

        # 頂背離條件：價格高點在RSI高點之後，且RSI未創高
        if price_high_idx > rsi_high_idx:
            if last_rsi < 70:
                return 0.3  # 輕微背離
            else:
                return 1.0  # 明確頂背離
        return 0.0

    def _trend_penalty(self, ma_period: int = 60) -> float:
        """趨勢方向罰分：季線向下時才罰"""
        ma_col = f'ma{ma_period}'
        if ma_col not in self.df.columns:
            return 0.0
        ma_now = self.last.get(ma_col, 0)
        if ma_now == 0 or pd.isna(ma_now):
            return 0.0
        ma_ago = self.df[ma_col].iloc[-min(ma_period, len(self.df))]
        if pd.isna(ma_ago) or ma_ago == 0:
            return 0.0
        ma_slope = (ma_now - ma_ago) / abs(ma_ago)
        price_vs_ma = (self.last_close - ma_now) / ma_now

        if ma_slope < -0.01:  # 季線明顯向下
            if price_vs_ma < -0.02:  # 在季線下
                return 20.0
            else:  # 季線向下但價格在季線上
                return 10.0
        return 0.0

    def diagnose(self, pattern: PatternResult) -> str:
        """產出人類可讀的 entryQuality 診斷文字"""
        r = self.calc(pattern)
        lines = [f'入場品質: {r["entry_quality"]:.0f}/100 → {r["action"]}',
                 f'  Composite Position: {r["position"]:.0f} pts（位階延伸罰分）']
        if r.get('vol_climax', 0) > 0:
            lines.append(f'  ⚡派發量: {r["vol_climax"]:.0f} pts（高檔爆量紅轉黑）')
        if r.get('rsi_div', 0) > 0:
            lines.append(f'  📉RSI背離: {r["rsi_div"]:.0f} pts')
        if r.get('trend', 0) > 0:
            lines.append(f'  📐趨勢: {r["trend"]:.0f} pts（季線向下）')
        for k, v in r.items():
            if k.startswith('dev_'):
                lines.append(f'  {k}: {v:.0f} pts')
        return '\n'.join(lines)



def run_pattern_detection(df: pd.DataFrame, order: int = 5) -> Tuple[List[PatternResult], str]:
    """
    執行所有型態偵測，返回結果列表
    按信心排序，高信心在前
    """
    highs, lows = find_swing_points(df, order=order)

    patterns = []
    detectors = [
        detect_head_shoulders_top,
        detect_head_shoulders_bottom,
        detect_double_top,
        detect_double_bottom,
        detect_triple_top,
        detect_triple_bottom,
        detect_ascending_triangle,
        detect_descending_triangle,
        detect_wedge,
        detect_v_reversal,
        detect_cup_handle,
        detect_box_range,
        detect_rounding,
        detect_parallel_bottom,
        # detect_flag,  # 旗形較主觀，暫時關閉
    ]

    for detector in detectors:
        try:
            if detector in [detect_head_shoulders_top, detect_ascending_triangle, detect_descending_triangle]:
                result = detector(df, highs, lows)
            elif detector in [detect_head_shoulders_bottom]:
                result = detector(df, highs, lows)
            elif detector in [detect_double_top]:
                result = detector(df, highs, lows)
            elif detector in [detect_double_bottom]:
                result = detector(df, highs, lows)
            elif detector in [detect_triple_top]:
                result = detector(df, highs)
            elif detector in [detect_triple_bottom]:
                result = detector(df, lows)
            elif detector == detect_wedge:
                result = detector(df, highs, lows)
            elif detector == detect_v_reversal:
                result = detector(df)
            elif detector == detect_cup_handle:
                result = detector(df, highs, lows)
            elif detector == detect_box_range:
                result = detector(df, highs, lows)
            elif detector == detect_rounding:
                result = detector(df)
            elif detector == detect_flag:
                result = detector(df, highs, lows)
            else:
                result = detector(df, highs, lows)

            if result is not None:
                patterns.append(result)
        except Exception:
            continue

    # 🆕 K線型態偵測（老大買入/賣出型態表）
    candle_patterns = detect_candlestick_patterns(df)
    patterns.extend(candle_patterns)
    
    # 🆕 支撐/壓力偵測
    sr_patterns = detect_support_resistance(df)
    patterns.extend(sr_patterns)

    # 🆕 均線交叉偵測（老大手寫筆記框架）
    cross_patterns = detect_ma_cross(df)
    patterns.extend(cross_patterns)

    # 按信心排序
    patterns.sort(key=lambda p: p.confidence, reverse=True)

    # 🆕 成交量確認 & 確認狀態（老大整理的核心框架）
    # 突破要看量，跌破要守停損，整理時量縮較健康
    last_close = df['close'].iloc[-1]
    for pat in patterns:
        # 設定 confirmed 狀態：跌破/突破頸線才算確認
        if pat.neckline is not None:
            if pat.category == 'bullish':
                pat.confirmed = last_close > pat.neckline
            elif pat.category == 'bearish':
                pat.confirmed = last_close < pat.neckline

        if pat.confirmed:
            # 已突破/跌破頸線 → 檢查突破當天的成交量
            vol_label, vol_ratio = check_volume_confirmation(df, len(df)-1, 
                'breakout' if pat.category == 'bullish' else 'breakdown')
            pat.volume_confirm = vol_label
            pat.volume_ratio = vol_ratio
            # 成交量助攻：放量突破加信心，量不足減信心
            if '✅' in vol_label or '放量' in vol_label:
                pat.confidence = min(pat.confidence + 0.05, 0.95)
            elif '⚠️' in vol_label:
                pat.confidence = max(pat.confidence - 0.05, 0.30)
        else:
            # 未確認（觀察中）→ 檢查最近是否量縮整理
            vol_label, vol_ratio = check_volume_confirmation(df, len(df)-1, 'consolidation')
            pat.volume_confirm = vol_label
            pat.volume_ratio = vol_ratio

    # 重新排序（信心可能因成交量調整而變化）
    patterns.sort(key=lambda p: p.confidence, reverse=True)

    # 🔧 老大v2.2：時間週期權重分配 + 主結構/次級修正層級
    total_len = len(df)
    for pat in patterns:
        duration = pat.end_idx - pat.start_idx
        if duration > total_len * 0.4:
            pat.timeframe = 'long'      # 佔圖表 40%+ → 長線（週線級別）
        elif duration > total_len * 0.15:
            pat.timeframe = 'medium'    # 15%~40% → 中線（日線級別）
        else:
            pat.timeframe = 'short'     # <15% → 短線（3-5日）

        # 層級判定：長線型態為背景趨勢（主結構），中短線為次級修正
        pat.hierarchy = 'main' if pat.timeframe == 'long' else 'sub'

    # 🔧 老大v2.2：多空整合共識（時間加權）
    bullish_score = sum(
        p.confidence * p.timeframe_weight
        for p in patterns if p.category == 'bullish'
    )
    bearish_score = sum(
        p.confidence * p.timeframe_weight
        for p in patterns if p.category == 'bearish'
    )

    if bullish_score > bearish_score * 1.3:
        consensus = 'bullish'
    elif bearish_score > bullish_score * 1.3:
        consensus = 'bearish'
    else:
        consensus = 'neutral'

    # 🔧 老大v2.2：RR風暴比計算
    # 風暴比 = 預期獲利 / 預期風險，只對有 target+stop 的 pattern 計算
    last_close = df['close'].iloc[-1]
    for pat in patterns:
        if pat.target_price is not None and pat.stop_price is not None:
            if pat.category == 'bullish':
                potential_gain = abs(pat.target_price - last_close)
                potential_loss = abs(last_close - pat.stop_price)
            else:
                potential_gain = abs(last_close - pat.target_price)
                potential_loss = abs(pat.stop_price - last_close)
            if potential_loss > 0:
                pat.risk_reward = round(potential_gain / potential_loss, 2)

    # 老大v2.2：層級輸出（取代單純信心排序輸出）
    # 主結構（main background trend）放前面，次級修正（sub）放後面
    main_patterns = [p for p in patterns if p.hierarchy == 'main']
    sub_patterns = [p for p in patterns if p.hierarchy == 'sub']
    # 各自按信心排序
    main_patterns.sort(key=lambda p: p.confidence, reverse=True)
    sub_patterns.sort(key=lambda p: p.confidence, reverse=True)
    patterns = main_patterns + sub_patterns

    # 對每個 pattern 註記層級
    hierarchy_labels = {'main': '背景趨勢', 'sub': '次級修正'}
    for pat in patterns:
        hl = hierarchy_labels.get(pat.hierarchy, '')
        pat.description += f' | {hl}'

    # 最多返回 5 個
    patterns = patterns[:5]

    # 🔧 v3.0 老大規範：替每個 pattern 計算 entryQuality
    # 完全獨立於 patternScore，gate 出 action
    eq_calc = EntryQualityCalculator(df)
    for pat in patterns:
        eq_result = eq_calc.calc(pat)
        pat.entry_quality = eq_result.get('entry_quality', 50)
        pat.entry_action = eq_result.get('action', '觀望')
        pat.entry_diagnosis = eq_calc.diagnose(pat)
        # 老大複審：每個型態各自攜帶失效點
        if pat.stop_price is not None:
            pat.hard_invalidation = pat.stop_price * 0.98
        else:
            pat.hard_invalidation = df['low'].iloc[pat.start_idx:pat.end_idx+1].min() * 0.95
        # 動態 MA60：每次 build_chart 重新抓最新的，不凍結
        # 實際使用時由 build_chart 或 rendering function 重新計算
        pat.regime_break = None  # 動態值：渲染時從 df 拉最新 MA60

    return patterns, consensus


# ═══════════════════════════════════════════
# 🔴 鐵律三：Y軸 zoom-in
# ═══════════════════════════════════════════
def calc_yaxis_range(series, padding=0.05, min_range=0.08):
    s = series.dropna()
    if len(s) == 0:
        return None, None
    data_min = s.min()
    data_max = s.max()
    data_range = data_max - data_min
    if data_range == 0:
        data_range = abs(data_max) * 0.01
    y_min = data_min - data_range * padding
    y_max = data_max + data_range * padding
    min_display_range = data_range * (1 + 2 * padding) * min_range
    if (y_max - y_min) < min_display_range:
        mid = (data_max + data_min) / 2
        half = max(min_display_range * 0.5, abs(data_max) * 0.02)
        y_min = mid - half
        y_max = mid + half
    return y_min, y_max


# ═══════════════════════════════════════════
# 📊 主圖建構
# ═══════════════════════════════════════════

STOCK_NAMES = {
    '2330': '台積電', '6770': '力積電', '6191': '精成科',
    '2359': '所羅門', '4906': '正文', '2458': '義隆',
    '2324': '仁寶', '1513': '中興電', '1582': '信錦',
    '2367': '燿華', '3006': '晶豪科', '2449': '京元電',
    '2383': '台光電',
}


def fetch_stock_data(code: str, days: int = 120, source: str = 'auto'):
    """
    雙源數據拉取：
    - yfinance: 歷史數據（型態學需要 120-244日）
    - twstock: 即時報價（盤中使用）
    
    source: 'auto' | 'yfinance' | 'twstock'
    auto 優先 yfinance，失敗 fallback twstock
    """
    df = None
    used_source = None

    # ─── 優先 yfinance（歷史數據充足） ───
    if source in ('auto', 'yfinance'):
        try:
            import yfinance as yf
            # 台股代碼加 .TW
            period_map = {90: '3mo', 120: '6mo', 200: '1y', 365: '1y'}
            yf_period = period_map.get(days, '6mo')
            if days > 200:
                yf_period = '1y'
            
            ticker = yf.Ticker(f"{code}.TW")
            hist = ticker.history(period=yf_period)
            
            if len(hist) > 10:  # 至少要有足夠數據
                hist = hist.reset_index()
                df = pd.DataFrame({
                    'date': pd.to_datetime(hist['Date']),
                    'open': hist['Open'].values,
                    'high': hist['High'].values,
                    'low': hist['Low'].values,
                    'close': hist['Close'].values,
                    'volume': hist['Volume'].values / 1000,  # 轉張
                })
                df = df.sort_values('date').reset_index(drop=True)
                # 取最近 days 筆
                if len(df) > days:
                    df = df.tail(days).reset_index(drop=True)
                used_source = 'yfinance'
                print(f'  📡 yfinance 取得 {len(df)} 筆歷史數據')
        except Exception as e:
            print(f'  ⚠️ yfinance 失敗: {e}')

    # ─── Fallback twstock（即時但只有31日） ───
    if df is None and source in ('auto', 'twstock'):
        try:
            import twstock
            stock = twstock.Stock(code)
            n = min(days, len(stock.price))
            df = pd.DataFrame({
                'date': pd.to_datetime(stock.date[-n:]),
                'open': stock.open[-n:] if hasattr(stock, 'open') and stock.open else stock.price[-n:],
                'high': stock.high[-n:] if hasattr(stock, 'high') and stock.high else stock.price[-n:],
                'low': stock.low[-n:] if hasattr(stock, 'low') and stock.low else stock.price[-n:],
                'close': stock.price[-n:],
                'volume': [c / 1000 for c in stock.capacity[-n:]],
            })
            df = df.sort_values('date').reset_index(drop=True)
            used_source = 'twstock'
            print(f'  📡 twstock 取得 {len(df)} 筆數據 (僅近{n}日)')
        except Exception as e:
            print(f'  ⚠️ twstock 失敗: {e}')

    if df is None:
        raise ValueError(f'無法取得 {code} 數據，yfinance 和 twstock 都失敗')

    # ─── 盤中即時報價更新最後一日（twstock） ───
    if used_source == 'yfinance':
        try:
            import twstock
            rt = twstock.realtime.get(code)
            if rt and rt.get('realtime') and rt['realtime'].get('latest_trade_price'):
                rt_price = float(rt['realtime']['latest_trade_price'])
                rt_time = rt.get('info', {}).get('time', '')
                if rt_price > 0:
                    # 更新最後一日收盤價為即時價
                    df.at[len(df)-1, 'close'] = rt_price
                    df.at[len(df)-1, 'high'] = max(df['high'].iloc[-1], rt_price)
                    df.at[len(df)-1, 'low'] = min(df['low'].iloc[-1], rt_price)
                    print(f'  🔄 即時更新: 收盤價 → {rt_price} [twstock] ({rt_time})')
        except Exception:
            pass  # 即時更新失敗不影響

    # ─── 日期字串（kaleido 序列化用） ───
    df['date_str'] = df['date'].dt.strftime('%m/%d')

    # ─── 技術指標計算 ───
    for w in [5, 10, 20, 50, 60, 100, 200]:
        if len(df) >= w:
            df[f'ma{w}'] = df['close'].rolling(w).mean()

    if len(df) >= 15:
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0.0)
        loss = -delta.where(delta < 0, 0.0)
        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        df['rsi'] = 100 - (100 / (1 + rs))

    if len(df) >= 20:
        df['boll_mid'] = df['close'].rolling(20).mean()
        std = df['close'].rolling(20).std()
        df['boll_upper'] = df['boll_mid'] + 2 * std
        df['boll_lower'] = df['boll_mid'] - 2 * std

    # 標記數據來源
    df.attrs['source'] = used_source
    df.attrs['data_points'] = len(df)

    return df


def build_chart(df: pd.DataFrame, code: str, name: str = '',
                show_rsi: bool = False, show_bollinger: bool = False,
                patterns: List[PatternResult] = None,
                consensus: str = 'neutral',          # 🔧 整合共識方向
                mode: str = 'auto',                  # 🔧 v2.2 老大追加：交易角色
                inst_data: pd.DataFrame = None,     # 🆕 ⑤ 籌碼
                rs_data: pd.DataFrame = None,        # 🆕 ⑦ 相對強弱
                rev_data: pd.DataFrame = None):      # 🆕 ⑩ 月營收事件
    """建構 Plotly 形態學增強版股市圖 v3.0 老大sp"""
    patterns = patterns or []

    # 🔧 v2.2 老大追加：交易角色判定
    # long → 停損標下方, target標上方; short → 停損標上方, target標下方
    auto_mode = consensus
    if mode == 'auto':
        effective_mode = auto_mode  # 依整合共識
    else:
        effective_mode = mode
    # 若整合共識與交易角色矛盾，以effective_mode爲準（使用者可強制切換）
    show_target_for = effective_mode

    # 計算需要的row數
    extra_rows = sum([
        1 if inst_data is not None and not inst_data.empty else 0,  # 籌碼副圖
        1 if rs_data is not None and not rs_data.empty else 0,      # RS副圖
    ])
    rows = 2 + (1 if show_rsi else 0) + extra_rows
    
    base_heights = [0.65, 0.20] if not show_rsi else [0.55, 0.15, 0.10]
    extra_heights = [0.10] * extra_rows
    row_heights = base_heights + extra_heights
    specs = [[{"secondary_y": False}] for _ in range(rows)]
    
    # 如果事件疊圖啟動，在最上方圖疊營收標記

    fig = make_subplots(
        rows=rows, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.03,
        row_heights=row_heights,
        specs=specs,
    )

    # ─── K線 ───
    fig.add_trace(
        go.Candlestick(
            x=df['date_str'],
            open=df['open'], high=df['high'],
            low=df['low'], close=df['close'],
            increasing_line_color=THEME['green'],
            decreasing_line_color=THEME['red'],
            increasing_fillcolor=THEME['green'],
            decreasing_fillcolor=THEME['red'],
            name='K線',
            showlegend=False,
        ),
        row=1, col=1,
    )

    # ─── 均線 ───
    # ─── 短中期均線 ───
    ma_colors = {'ma5': THEME['ma5'], 'ma10': THEME['ma10'],
                 'ma20': THEME['ma20'], 'ma60': THEME['ma60']}
    for ma, color in ma_colors.items():
        if ma in df.columns:
            fig.add_trace(
                go.Scatter(x=df['date_str'], y=df[ma], mode='lines',
                           line=dict(color=color, width=1.2 if ma != 'ma60' else 0.8),
                           name=ma.upper(), legendgroup='ma'),
                row=1, col=1,
            )

    # ─── 中長期均線（MA50/100/200，交叉偵測用）───
    long_ma_colors = {'ma50': '#ff6b6b', 'ma100': '#ffd93d', 'ma200': '#6bcb77'}
    for ma, color in long_ma_colors.items():
        if ma in df.columns and df[ma].notna().sum() > 5:  # 只在有足夠數據時顯示
            fig.add_trace(
                go.Scatter(x=df['date_str'], y=df[ma], mode='lines',
                           line=dict(color=color, width=0.8, dash='dot'),
                           name=ma.upper(), legendgroup='ma_long',
                           showlegend=True),
                row=1, col=1,
            )

    # ─── 布林通道 ───
    if show_bollinger and 'boll_upper' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['date_str'], y=df['boll_upper'], mode='lines',
                       line=dict(color=THEME['bollinger_border'], width=0.8),
                       name='布林上軌', legendgroup='boll', showlegend=True),
            row=1, col=1,
        )
        fig.add_trace(
            go.Scatter(x=df['date_str'], y=df['boll_lower'], mode='lines',
                       line=dict(color=THEME['bollinger_border'], width=0.8),
                       name='布林下軌', legendgroup='boll',
                       fill='tonexty', fillcolor=THEME['bollinger_bg'], showlegend=True),
            row=1, col=1,
        )

    # 🆕 ─── 型態學標註 ───
    for pat in patterns:
        pat_color = THEME['pattern_text_bull'] if pat.category == 'bullish' else THEME['pattern_text_bear'] if pat.category == 'bearish' else THEME['pattern_text_neutral']

        # 連接關鍵點的型態線
        if len(pat.points) >= 2:
            pat_x = [df['date_str'].iloc[p[0]] for p in pat.points]
            pat_y = [p[1] for p in pat.points]
            # 延伸到最後一個點
            if pat.points[-1][0] < len(df) - 1:
                pat_x.append(df['date_str'].iloc[-1])
                pat_y.append(pat_y[-1])

            # v2.3 老大追加：預測路徑虛線使用半透明，避免誤判爲必然走勢
            pred_color = 'rgba(255,123,114,0.35)'
            
            # 🟢 老大複審：只標 structual 關鍵點（V底只標低點，不倒V標高點）
            # 找出哪個點是結構性關鍵（V底=最低, 倒V=最高）
            n_points = len(pat.points)
            key_idx = None
            if pat.category == 'bullish':
                # 多頭型態：最低點是結構關鍵
                min_y = min(p[1] for p in pat.points)
                key_idx = next(i for i, p in enumerate(pat.points) if p[1] == min_y)
            elif pat.category == 'bearish':
                # 空頭型態：最高點是結構關鍵
                max_y = max(p[1] for p in pat.points)
                key_idx = next(i for i, p in enumerate(pat.points) if p[1] == max_y)
            
            # 每個點的 marker：關鍵點用大鑽石，其他用小圓點
            marker_sizes = [4] * n_points  # default: 小圓
            marker_symbols = ['circle'] * n_points
            marker_colors = [THEME['text_muted']] * n_points  # 灰
            if key_idx is not None:
                marker_sizes[key_idx] = 10
                marker_symbols[key_idx] = 'diamond'
                marker_colors[key_idx] = pat_color
            # 如果有額外延伸的最後一根（超出 pat.points 數量），用小圓
            if len(pat_x) > n_points:
                marker_sizes.append(3)
                marker_symbols.append('circle')
                marker_colors.append(THEME['text_muted'])
            
            fig.add_trace(
                go.Scatter(
                    x=pat_x, y=pat_y,
                    mode='lines+markers',
                    line=dict(color=pred_color, width=2, dash='dash'),
                    marker=dict(size=marker_sizes, symbol=marker_symbols, color=marker_colors),
                    name=f'{pat.emoji} {pat.name_zh}',
                    legendgroup='pattern',
                ),
                row=1, col=1,
            )

        # 頸線
        if pat.neckline is not None:
            fig.add_hline(
                y=pat.neckline,
                line_dash='dot',
                line_color=THEME['pattern_neckline'],
                line_width=1.5,
                annotation_text=f'頸線 ${pat.neckline:.1f}',
                annotation_position='top left',
                annotation_font=dict(color=THEME['pattern_neckline'], size=10, family=FONT_FAMILY),
                row=1, col=1,
            )

        # 🔧 v2.2 RR濾網：風暴比 < 1.5 時不顯示目標/停損線
        rr_pass = pat.risk_reward is None or pat.risk_reward >= 1.5

        # 量度目標線（只顯示RR合格 + 方向一致者）
        if pat.target_price is not None and rr_pass:
            if show_target_for == 'neutral' or pat.category == show_target_for:
                fig.add_hline(
                    y=pat.target_price,
                    line_dash='longdash',
                    line_color=THEME['pattern_target'],
                    line_width=1.2,
                    annotation_text=f'目標 ${pat.target_price:.1f}',
                    annotation_position='bottom left',
                    annotation_font=dict(color=THEME['pattern_target'], size=10, family=FONT_FAMILY),
                    row=1, col=1,
                )

        # 停損線（只顯示RR合格 + 方向一致者）
        if pat.stop_price is not None and rr_pass:
            if show_target_for == 'neutral' or pat.category == show_target_for:
                stop_pos = 'top right' if pat.category == 'bearish' else 'bottom right'
                fig.add_hline(
                    y=pat.stop_price,
                    line_dash='dash',
                    line_color=THEME['red'] if pat.category == 'bearish' else THEME['green'],
                    line_width=1,
                    annotation_text=f'停損 ${pat.stop_price:.1f}',
                    annotation_position=stop_pos,
                    annotation_font=dict(color=THEME['text_muted'], size=9, family=FONT_FAMILY),
                    row=1, col=1,
                )

        # 型態名稱標註（v2.2 加入層級標示 + RR）
        start_date = df['date_str'].iloc[pat.start_idx] if pat.start_idx < len(df) else df['date_str'].iloc[0]
        mid_price = np.mean([p[1] for p in pat.points]) if pat.points else df['close'].iloc[-1]

        hierarchy_tag = '📐背景' if pat.hierarchy == 'main' else '📏波動'
        confidence_text = f'{pat.confidence*100:.0f}%'
        confirm_text = '✅' if pat.confirmed else '🟡'
        vol_text = f' | {pat.volume_confirm}' if pat.volume_confirm else ''
        rr_text = f' | RR {pat.risk_reward:.1f}' if pat.risk_reward is not None else ''
        fig.add_annotation(
            text=f'{hierarchy_tag} {pat.emoji} {pat.name_zh}<br><sup>{pat.name_en} ({confidence_text}) {confirm_text}{vol_text}{rr_text}</sup>',
            x=start_date,
            y=mid_price * 1.02,
            showarrow=False,
            font=dict(color=pat_color, size=12, family=FONT_FAMILY),
            bgcolor='rgba(13,17,23,0.85)',
            bordercolor=pat_color,
            borderwidth=1,
            borderpad=4,
            row=1, col=1,
        )

    # 🔧 v2.3 + 老大複審：視覺補償——每個型態各自的失效點
    # 動態 MA60（不凍結）
    dynamic_ma60 = df['ma60'].iloc[-1] if 'ma60' in df.columns else None
    invalidation_lines = []
    for pat in patterns:
        pat_inval = pat.hard_invalidation
        if pat_inval is not None:
            invalidation_lines.append(f'{pat.name_zh}💀${pat_inval:.1f}')
    if dynamic_ma60 is not None and pd.notna(dynamic_ma60):
        invalidation_lines.append(f'區間🧱${dynamic_ma60:.1f}')
    
    if invalidation_lines:
        inval_text = ' | '.join(invalidation_lines[:3])  # 最多顯示3個
        fig.add_annotation(
            text=f'💀 失效: {inval_text}',
            xref='paper', yref='paper',
            x=1.0, y=1.01,
            xanchor='right', yanchor='bottom',
            showarrow=False,
            font=dict(color=THEME['text_muted'], size=10, family=FONT_FAMILY),
            bgcolor='rgba(13,17,23,0.7)',
            bordercolor=THEME['grid'],
            borderwidth=1,
            borderpad=4,
        )

    # ─── 成交量 ───
    vol_colors = [THEME['volume_green'] if df['close'].iloc[i] >= df['open'].iloc[i]
                  else THEME['volume_red'] for i in range(len(df))]
    fig.add_trace(
        go.Bar(x=df['date_str'], y=df['volume'], marker_color=vol_colors,
               marker_line_width=0, name='成交量(張)', showlegend=False),
        row=2, col=1,
    )

    # ─── RSI ───
    rsi_row = 3 if show_rsi else None
    if show_rsi and 'rsi' in df.columns:
        fig.add_trace(
            go.Scatter(x=df['date_str'], y=df['rsi'], mode='lines',
                       line=dict(color=THEME['rsi_line'], width=1.2), name='RSI(14)'),
            row=rsi_row, col=1,
        )
        fig.add_hrect(y0=70, y1=100, fillcolor=THEME['rsi_ob'], line_width=0, row=rsi_row, col=1)
        fig.add_hrect(y0=0, y1=30, fillcolor=THEME['rsi_os'], line_width=0, row=rsi_row, col=1)
        fig.add_hline(y=70, line_dash='dot', line_color=THEME['text_muted'], line_width=0.5, row=rsi_row, col=1)
        fig.add_hline(y=30, line_dash='dot', line_color=THEME['text_muted'], line_width=0.5, row=rsi_row, col=1)
        fig.add_hline(y=50, line_dash='dot', line_color=THEME['text_muted'], line_width=0.3, row=rsi_row, col=1)

        fig.add_hline(y=50, line_dash='dot', line_color=THEME['text_muted'], line_width=0.3, row=rsi_row, col=1)

    # ─── ⑤ 籌碼：三大法人買賣超 ───
    inst_row = (rsi_row or 2) + 1  # 接在 RSI 或成交量後面
    if inst_data is not None and not inst_data.empty:
        inst_dates = inst_data['date_str'].tolist()
        # 外資買賣超（藍）
        fig.add_trace(
            go.Bar(x=inst_dates, y=inst_data['foreign_net'],
                   marker_color='#4a9eff', marker_line_width=0,
                   name='外資', legendgroup='inst'),
            row=inst_row, col=1,
        )
        # 投信買賣超（紅）
        fig.add_trace(
            go.Bar(x=inst_dates, y=inst_data['investment_net'],
                   marker_color='#ff6b6b', marker_line_width=0,
                   name='投信', legendgroup='inst'),
            row=inst_row, col=1,
        )
        # 自營商買賣超（綠）
        fig.add_trace(
            go.Bar(x=inst_dates, y=inst_data['dealer_net'],
                   marker_color='#6bcb77', marker_line_width=0,
                   name='自營商', legendgroup='inst'),
            row=inst_row, col=1,
        )
        # 零線
        fig.add_hline(y=0, line_dash='dot', line_color=THEME['text_muted'], line_width=0.5,
                      row=inst_row, col=1)
    else:
        inst_row = None

    # ─── ⑦ 相對強弱：個股/大盤 RS 線 ───
    rs_row = (inst_row or rsi_row or 2) + 1 if (rs_data is not None and not rs_data.empty) else None
    if rs_row is not None and not rs_data.empty:
        fig.add_trace(
            go.Scatter(x=rs_data['date'], y=rs_data['rs_norm'], mode='lines',
                       line=dict(color='#ffd93d', width=1.5), name='RS(個股/大盤)'),
            row=rs_row, col=1,
        )
        fig.add_hline(y=100, line_dash='dot', line_color=THEME['text_muted'], line_width=0.5,
                      row=rs_row, col=1)

    # ─── ⑩ 事件疊圖：月營收年增率標記 ───
    if rev_data is not None and not rev_data.empty:
        for _, r in rev_data.iterrows():
            # 找到對應的圖表 position（以該月15號作爲標記位置）
            month_start = r['date']
            month_mid = month_start + pd.Timedelta(days=14)
            # 在 K 線圖上標記
            label = f"{r['yoy_pct']:+.1f}%"
            color = '#6bcb77' if r['yoy_pct'] > 0 else '#ff6b6b'
            
            fig.add_annotation(
                x=month_mid.strftime('%m/%d'),
                y=df['high'].max(),
                text=label,
                font=dict(color=color, size=9),
                showarrow=False,
                yshift=10 + (hash(r['month']) % 20),
                row=1, col=1,
            )
            # 垂直線
            fig.add_vline(x=month_mid.strftime('%m/%d'),
                          line_dash='dot', line_color=color, line_width=0.5,
                          row=1, col=1)

    # ─── 樣式 ───
    close_series = df['close'].dropna()
    y_min, y_max = calc_yaxis_range(close_series)

    # 如果有型態目標價超出範圍，擴展 Y 軸
    for pat in patterns:
        if pat.target_price is not None:
            y_max = max(y_max, pat.target_price * 1.01)
        if pat.stop_price is not None:
            y_min = min(y_min, pat.stop_price * 0.99)

    latest = df['close'].iloc[-1]
    prev = df['close'].iloc[-2] if len(df) > 1 else latest
    chg = latest - prev
    chg_pct = (chg / prev * 100) if prev != 0 else 0
    arrow = '▲' if chg >= 0 else '▼'
    color = THEME['green'] if chg >= 0 else THEME['red']

    # 型態摘要標題（🔧 v2.2 層級式顯示：主結構 → 次級修正）
    # 🔧 v3.0 老大規範：entryQuality gate 取代固定模式標籤
    entry_labels = {'作多（進場）': '📗進場', '觀望／等止跌': '📘觀望', '不宜進場': '⛔不進'}
    best_entry = patterns[0].entry_action if patterns else '觀望'
    best_eq = patterns[0].entry_quality if patterns else 0
    entry_tag = entry_labels.get(best_entry, '📘')
    title_pattern = f'{name} ({code}) {entry_tag} {best_entry} ({best_eq:.0f}/100)'
    
    # 層級式顯示
    main_pats = [p for p in patterns if p.hierarchy == 'main']
    sub_pats = [p for p in patterns if p.hierarchy == 'sub']
    
    title_lines = []
    if main_pats:
        main_fmt = ' | '.join(
            f'{p.emoji} {p.name_zh} ({p.direction[:2]}, {p.confidence*100:.0f}%)'
            for p in main_pats[:2]
        )
        title_lines.append(f'大週期：{main_fmt}')
    if sub_pats:
        sub_fmt = ' | '.join(
            f'{p.emoji} {p.name_zh} ({p.direction[:2]}, {p.confidence*100:.0f}%)'
            for p in sub_pats[:1]
        )
        title_lines.append(f'當前：{sub_fmt}')
    
    if title_lines:
        title_text = f'{title_pattern}<br>' + ' → '.join(title_lines)
        # v3.0：entry_action 已內建在 title_pattern，不需重複
        pass
    else:
        title_text = f'{title_pattern}'

    fig.update_layout(
        title=dict(
            text=title_text,
            font=dict(size=16, color=THEME['text'], family=FONT_FAMILY),
            x=0.01, xanchor='left',
        ),
        paper_bgcolor=THEME['paper'],
        plot_bgcolor=THEME['bg'],
        font=dict(color=THEME['text'], family=FONT_FAMILY, size=11),
        legend=dict(
            bgcolor='rgba(13,17,23,0.85)',
            bordercolor=THEME['grid'],
            borderwidth=1,
            font=dict(size=10, color=THEME['text_muted']),
            orientation='h',
            yanchor='bottom', y=1.02,
            xanchor='right', x=1,
        ),
        margin=dict(l=60, r=30, t=80, b=30),
        xaxis_rangeslider_visible=False,
        xaxis=dict(gridcolor=THEME['grid'], linecolor=THEME['grid'],
                   tickfont=dict(color=THEME['text_muted'], size=9), type='category'),
        yaxis=dict(range=[y_min, y_max], gridcolor=THEME['grid'], linecolor=THEME['grid'],
                   tickfont=dict(color=THEME['text_muted'], size=9), side='right',
                   tickformat=',.1f' if y_max - y_min < 100 else ',.0f'),
        yaxis2=dict(gridcolor=THEME['grid'], linecolor=THEME['grid'],
                   tickfont=dict(color=THEME['text_muted'], size=9), side='right'),
        hovermode='x unified',
        dragmode='zoom',
    )

    fig.add_annotation(
        text=f'{df["date_str"].iloc[0]} ~ {df["date_str"].iloc[-1]}　　最新: <b>{latest:,.1f}</b>　{arrow} {chg:+,.1f} ({chg_pct:+.2f}%)',
        xref='paper', yref='paper', x=0.99, y=1.04,
        showarrow=False,
        font=dict(size=11, color=color, family=FONT_FAMILY),
    )

    if show_rsi and rsi_row:
        fig.update_yaxes(range=[0, 100], gridcolor=THEME['grid'], linecolor=THEME['grid'],
                         tickfont=dict(color=THEME['text_muted'], size=9),
                         title_text='RSI', title_font=dict(size=9, color=THEME['text_muted']),
                         row=rsi_row, col=1)
    
    if 'inst_row' in dir() and inst_row is not None:
        fig.update_yaxes(gridcolor=THEME['grid'], linecolor=THEME['grid'],
                         tickfont=dict(color=THEME['text_muted'], size=8),
                         title_text='法人買賣超(張)',
                         title_font=dict(size=8, color=THEME['text_muted']),
                         row=inst_row, col=1)
    
    if 'rs_row' in dir() and rs_row is not None:
        fig.update_yaxes(gridcolor=THEME['grid'], linecolor=THEME['grid'],
                         tickfont=dict(color=THEME['text_muted'], size=8),
                         title_text='RS(100)',
                         title_font=dict(size=8, color=THEME['text_muted']),
                         row=rs_row, col=1)

    return fig


def print_pattern_analysis(patterns: List[PatternResult], df: pd.DataFrame, code: str, name: str):
    """印出型態分析報告"""
    print('\n' + '='*60)
    print(f'📐 {name}({code}) 型態學分析報告')
    print('='*60)

    if not patterns:
        print('  ⚪ 未偵測到明顯型態')
        print('  建議：持續觀察，或調整時間範圍')
        return

    for i, p in enumerate(patterns, 1):
        tf_label = {'long': '長線📐', 'medium': '中線📏', 'short': '短線⚡'}
        print(f'\n  {p.emoji} 型態 {i}：{p.name_zh} ({p.name_en})')
        print(f'  方向：{p.direction}　週期: {tf_label.get(p.timeframe, p.timeframe)}　權重: ×{p.timeframe_weight}')
        print(f'  信心：{"█" * int(p.confidence * 10)}{"░" * (10 - int(p.confidence * 10))} {p.confidence*100:.0f}%')
        # 🆕 確認狀態
        confirm_str = '✅ 已確認' if p.confirmed else '🟡 觀察中'
        print(f'  確認：{confirm_str}')
        if p.volume_confirm:
            print(f'  📊 成交量：{p.volume_confirm}')
        if p.neckline:
            print(f'  頸線：${p.neckline:.1f}')
        if p.target_price:
            print(f'  🎯 量度目標：${p.target_price:.1f}')
        if p.stop_price:
            # 🔧 老大2026-06-09：停損線必須與方向一致（Blind Spot C）
            stop_note = ' (作多停損)' if p.category == 'bullish' else ' (放空停損)' if p.category == 'bearish' else ''
            print(f'  🔴 停損：${p.stop_price:.1f}{stop_note}')
        print(f'  📝 {p.description}')
        # 🔧 v3.0 老大規範：entryQuality 完全獨立於 patternScore
        print(f'  🎯 進場品質：{p.entry_quality:.0f}/100 → {p.entry_action}')
        # 老大複審：每個型態各自的失效點
        if p.hard_invalidation is not None:
            print(f'  💀 型態失效：跌破 ${p.hard_invalidation:.1f} → 此型態全失效')
        # 動態 MA60（老大2026-06-09：不凍結）
        dynamic_ma60 = df['ma60'].iloc[-1] if 'ma60' in df.columns and not df['ma60'].empty and pd.notna(df['ma60'].iloc[-1]) else None
        if dynamic_ma60 is not None:
            print(f'  🧱 區間失效：跌破 ${dynamic_ma60:.1f} → 回到大區間整理')

    # 🔧 綜合判斷（老大2026-06-09：改用時間加權共識）
    print(f'\n  ─── 綜合判斷（時間加權） ───')
    bullish_score = sum(p.confidence * p.timeframe_weight for p in patterns if p.category == 'bullish')
    bearish_score = sum(p.confidence * p.timeframe_weight for p in patterns if p.category == 'bearish')

    last_close = df['close'].iloc[-1]
    if bullish_score > bearish_score * 1.3:
        direction = f'🟢 偏多 (多{bullish_score:.1f} vs 空{bearish_score:.1f})'
    elif bearish_score > bullish_score * 1.3:
        direction = f'🔴 偏空 (空{bearish_score:.1f} vs 多{bullish_score:.1f})'
    else:
        direction = f'🟡 多空分歧 (多{bullish_score:.1f} vs 空{bearish_score:.1f})'

    max_conf = max(patterns, key=lambda p: p.confidence)
    print(f'  整合共識：{direction}')
    print(f'  最高信心型態：{max_conf.emoji} {max_conf.name_zh} ({max_conf.confidence*100:.0f}%)')
    print(f'  當前收盤：${last_close:,.1f}')


def main():
    parser = argparse.ArgumentParser(description='Plotly 形態學增強版股市圖 v3.0 老大sp (雙源版)')
    parser.add_argument('code', help='股票代碼 (e.g. 6770)')
    parser.add_argument('--name', default='', help='股票名稱')
    parser.add_argument('--days', type=int, default=120, help='天數 (default: 120, yfinance可拉更長)')
    parser.add_argument('--rsi', action='store_true', help='顯示 RSI(14)')
    parser.add_argument('--bollinger', action='store_true', help='顯示布林通道')
    parser.add_argument('--pattern', action='store_true', help='🆕 啟用型態學偵測')
    parser.add_argument('--source', default='auto', choices=['auto', 'yfinance', 'twstock'], help='數據源 (default: auto=yfinance優先)')
    parser.add_argument('--output', default='', help='輸出路徑 (default: /tmp/<code>_chart_v2.png)')
    parser.add_argument('--institutional', action='store_true', help='⑤ 顯示三大法人買賣超')
    parser.add_argument('--rs', action='store_true', help='⑦ 顯示相對強弱(個股/大盤)')
    parser.add_argument('--events', action='store_true', help='⑩ 顯示月營收年增率事件')
    parser.add_argument('--mode', default='auto', choices=['long', 'short', 'auto'],
                        help="交易角色: long(作多) / short(放空) / auto(依整合共識)")
    args = parser.parse_args()

    name = args.name or STOCK_NAMES.get(args.code, args.code)

    print(f'📊 拉取 {name}({args.code}) 近 {args.days} 日數據 (源: {args.source})...')
    df = fetch_stock_data(args.code, days=args.days, source=args.source)
    print(f'   數據源: {df.attrs.get("source", "unknown")} | {len(df)} 筆')
    print(f'   最新收盤: {df["close"].iloc[-1]:,.1f}')

    # 🆕 型態偵測（數據量越多越準）
    patterns = []
    if args.pattern:
        print(f'🔍 執行型態學偵測...')
        order = min(5, max(3, len(df)//25))
        patterns, consensus = run_pattern_detection(df, order=order)
        print(f'   偵測到 {len(patterns)} 個型態')
        consensus_labels_print = {'bullish': '🟢偏多', 'bearish': '🔴偏空', 'neutral': '🟡多空分歧'}
        print(f'   整合共識：{consensus_labels_print.get(consensus, "?")}')
        print_pattern_analysis(patterns, df, args.code, name)

    print(f'\n📈 建構圖表（RSI={args.rsi}, 布林={args.bollinger}, 型態={args.pattern}）...')
    
    # 🆕 ⑤ 籌碼、⑦ RS、⑩ 事件
    inst_data = None
    rs_data = None
    rev_data = None
    
    if args.institutional:
        from twse_data import fetch_institutional_data
        print('  📡 拉取三大法人買賣超...')
        inst_data = fetch_institutional_data(args.code)
        if inst_data.empty:
            print('  ⚠️ 法人買賣超無資料')
    
    if args.rs:
        from twse_data import fetch_market_index, compute_relative_strength
        print('  📡 計算相對強弱(個股/大盤)...')
        index_df = fetch_market_index()
        if not index_df.empty:
            rs_data = compute_relative_strength(df, index_df)
        if rs_data is None or rs_data.empty:
            print('  ⚠️ RS相對強弱無資料')
    
    if args.events:
        from twse_data import fetch_monthly_revenue
        print('  📡 拉取月營收事件...')
        rev_data = fetch_monthly_revenue(args.code)
        if rev_data.empty:
            print('  ⚠️ 月營收無資料')
    
    mode = args.mode or 'auto'
    fig = build_chart(df, args.code, name,
                     show_rsi=args.rsi, show_bollinger=args.bollinger,
                     patterns=patterns, consensus=consensus, mode=mode,
                     inst_data=inst_data, rs_data=rs_data, rev_data=rev_data)

    output_path = args.output or f'/tmp/{args.code}_chart_v2.png'
    fig.write_image(output_path, scale=2, width=1200, height=800)
    print(f'\n✅ 已存檔：{output_path}')

    html_path = output_path.replace('.png', '.html')
    fig.write_html(html_path)
    print(f'✅ HTML版：{html_path}')

    # 技術指標摘要
    latest = df.iloc[-1]
    print('\n📋 技術指標摘要:')
    print(f'   收盤: {latest["close"]:,.1f}')
    if 'ma5' in df.columns and not pd.isna(latest['ma5']):
        bias5 = (latest['close'] - latest['ma5']) / latest['ma5'] * 100
        print(f'   MA5:  {latest["ma5"]:,.1f}  乖離: {bias5:+.2f}%')
    if 'ma20' in df.columns and not pd.isna(latest['ma20']):
        bias20 = (latest['close'] - latest['ma20']) / latest['ma20'] * 100
        print(f'   MA20: {latest["ma20"]:,.1f}  乖離: {bias20:+.2f}%')
    if 'rsi' in df.columns and not pd.isna(latest.get('rsi', np.nan)):
        print(f'   RSI(14): {latest["rsi"]:.1f}')
    if 'volume' in df.columns:
        vol = latest['volume']
        avg_vol = df['volume'].rolling(5).mean().iloc[-1] if len(df) >= 5 else vol
        print(f'   成交量: {vol:,.0f} 張  (5日均量: {avg_vol:,.0f} 張)')

    # 型態交易建議
    if patterns:
        p = patterns[0]  # 最高信心
        print(f'\n🎯 型態交易建議（{p.name_zh}）:')
        print(f'   方向：{p.direction}')
        if p.neckline:
            print(f'   頸線：${p.neckline:.1f}')
        # v2.2 RR濾網
        if p.risk_reward is not None and p.risk_reward < 1.5:
            print(f'   ⚠️ 風暴比 1:{p.risk_reward:.1f} < 1.5 → 風險過高，建議觀望')
        else:
            if p.target_price:
                print(f'   🟢 目標：${p.target_price:.1f}')
            if p.stop_price:
                print(f'   🔴 停損：${p.stop_price:.1f}')
            if p.risk_reward is not None:
                print(f'   📊 風暴比：1:{p.risk_reward:.1f}  ✅')
        # 層級標示
        hierarchy_tags = {'main': '📐背景趨勢', 'sub': '📏次級修正'}
        print(f'   🏷️ {hierarchy_tags.get(p.hierarchy, "?")} ({p.timeframe})')


if __name__ == '__main__':
    main()