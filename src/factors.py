"""Multi-factor scoring engine.

Factors (each returns 0-100, higher = better):
- momentum: 20d/60d price momentum, with mean reversion penalty
- value: inverse PE/PB percentile
- quality: ROE proxy from PE + 涨跌幅 (clean data hard to get free)
- fund_flow: 主力净流入 vs 流通市值
- technical: MA20/MA60 trend + RSI
- volatility_penalty: lower 20d vol = better
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def _percentile_rank(series: pd.Series, value: float, invert: bool = False) -> float:
    """Returns 0-100 percentile. invert=True means lower value = higher score."""
    if series.empty or pd.isna(value):
        return 50.0
    pct = (series.dropna() < value).sum() / len(series.dropna()) * 100
    if invert:
        pct = 100 - pct
    return float(np.clip(pct, 0, 100))


def score_momentum(close: pd.Series) -> float:
    """20d + 60d momentum with reversal penalty."""
    if len(close) < 60:
        return 50.0
    ret_20 = (close.iloc[-1] / close.iloc[-20] - 1) * 100
    ret_60 = (close.iloc[-1] / close.iloc[-60] - 1) * 100
    # Overextended is bad: penalize 1-month > 30%
    if ret_20 > 30:
        ret_20 = 30 - (ret_20 - 30) * 0.5
    score = 50 + ret_20 * 1.5 + ret_60 * 0.5
    return float(np.clip(score, 0, 100))


def score_technical(close: pd.Series) -> float:
    """MA trend + RSI(14)."""
    if len(close) < 60:
        return 50.0
    ma20 = close.rolling(20).mean().iloc[-1]
    ma60 = close.rolling(60).mean().iloc[-1]
    last = close.iloc[-1]

    # Trend score
    trend = 50
    if last > ma20 > ma60:
        trend = 90
    elif last > ma20:
        trend = 65
    elif last < ma20 < ma60:
        trend = 15
    elif last < ma20:
        trend = 35

    # RSI
    delta = close.diff()
    gain = delta.where(delta > 0, 0).rolling(14).mean().iloc[-1]
    loss = (-delta.where(delta < 0, 0)).rolling(14).mean().iloc[-1]
    if loss == 0:
        rsi = 100
    else:
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))
    # Sweet spot 50-70
    if 50 <= rsi <= 70:
        rsi_score = 90
    elif 40 <= rsi < 50 or 70 < rsi <= 80:
        rsi_score = 65
    else:
        rsi_score = 35

    return float((trend * 0.6 + rsi_score * 0.4))


def score_volatility(close: pd.Series) -> float:
    """Lower 20d annualized vol = better (more stable)."""
    if len(close) < 20:
        return 50.0
    rets = close.pct_change().dropna().tail(20)
    vol = rets.std() * np.sqrt(252) * 100
    # < 20% vol = 90, > 60% = 10
    if vol < 20:
        return 90.0
    if vol > 60:
        return 10.0
    return 90 - (vol - 20) * 2


def score_value(pe: float, pb: float, pe_pool: pd.Series, pb_pool: pd.Series) -> float:
    """Inverse percentile of PE and PB."""
    pe_score = _percentile_rank(pe_pool, pe, invert=True) if pd.notna(pe) and pe > 0 else 50.0
    pb_score = _percentile_rank(pb_pool, pb, invert=True) if pd.notna(pb) and pb > 0 else 50.0
    return (pe_score * 0.5 + pb_score * 0.5)


def score_fund_flow(flow: dict, mkt_cap: float) -> float:
    """主力净流入占流通市值比例."""
    if not flow or mkt_cap <= 0:
        return 50.0
    main = flow.get("main_net_inflow", 0)
    ratio = (main / mkt_cap) * 100
    # 0.5% inflow = 90, -0.5% outflow = 10
    score = 50 + ratio * 80
    return float(np.clip(score, 0, 100))


def score_turnover(turnover: float) -> float:
    """Active but not over-the-top. 1-5% ideal."""
    if pd.isna(turnover):
        return 50.0
    if 1 <= turnover <= 5:
        return 90.0
    if 0.5 <= turnover < 1 or 5 < turnover <= 8:
        return 65.0
    if turnover > 15:
        return 20.0
    return 40.0


def compute_total_score(row: dict, weights: dict | None = None) -> dict:
    """Combine factors with weights. Returns {total, breakdown}."""
    if weights is None:
        weights = {
            "momentum": 0.20,
            "technical": 0.20,
            "volatility": 0.10,
            "value": 0.15,
            "fund_flow": 0.20,
            "turnover": 0.15,
        }
    factors = {
        "momentum": row.get("f_momentum", 50),
        "technical": row.get("f_technical", 50),
        "volatility": row.get("f_volatility", 50),
        "value": row.get("f_value", 50),
        "fund_flow": row.get("f_fund_flow", 50),
        "turnover": row.get("f_turnover", 50),
    }
    total = sum(factors[k] * w for k, w in weights.items())
    return {"total": round(total, 2), "breakdown": {k: round(v, 1) for k, v in factors.items()}}
