"""AKShare data fetchers — quotes, fundamentals, fund flow, technicals."""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Optional

import akshare as ak
import pandas as pd

from .config import config


# ============================================================
# Real-time quotes (batch)
# ============================================================
def fetch_spot_quote(codes: list[str]) -> pd.DataFrame:
    """实时行情: 拉全 A 一张快照再过滤 — 比逐只调快 N 倍."""
    df = ak.stock_zh_a_spot_em()
    df = df.rename(columns={
        "代码": "code",
        "名称": "name",
        "最新价": "price",
        "涨跌幅": "change_pct",
        "成交量": "volume",
        "成交额": "amount",
        "换手率": "turnover",
        "市盈率-动态": "pe",
        "市净率": "pb",
    })
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df[df["code"].isin(codes)].copy()


# ============================================================
# Historical K-line for technical factors
# ============================================================
def fetch_kline(code: str, days: int = 120) -> Optional[pd.DataFrame]:
    """日 K 线."""
    try:
        end = pd.Timestamp.today().strftime("%Y%m%d")
        start = (pd.Timestamp.today() - pd.Timedelta(days=days * 2)).strftime("%Y%m%d")
        df = ak.stock_zh_a_hist(
            symbol=code, period="daily",
            start_date=start, end_date=end, adjust="qfq",
        )
        if df is None or df.empty:
            return None
        df = df.rename(columns={
            "日期": "date", "开盘": "open", "收盘": "close",
            "最高": "high", "最低": "low",
            "成交量": "volume", "成交额": "amount",
            "涨跌幅": "change_pct",
        })
        return df.tail(days).reset_index(drop=True)
    except Exception as e:
        print(f"[kline] {code} failed: {e}")
        return None


# ============================================================
# Fund flow (北向/主力)
# ============================================================
def fetch_fund_flow(code: str) -> Optional[dict]:
    """个股资金流（最近一日 + 5 日累计）."""
    try:
        df = ak.stock_individual_fund_flow(stock=code, market="sh" if code.startswith("6") else "sz")
        if df is None or df.empty:
            return None
        latest = df.iloc[-1]
        return {
            "main_net_inflow": float(latest.get("主力净流入-净额", 0) or 0),
            "super_large_net": float(latest.get("超大单净流入-净额", 0) or 0),
            "large_net": float(latest.get("大单净流入-净额", 0) or 0),
            "medium_net": float(latest.get("中单净流入-净额", 0) or 0),
            "small_net": float(latest.get("小单净流入-净额", 0) or 0),
        }
    except Exception as e:
        print(f"[fund_flow] {code} failed: {e}")
        return None


# ============================================================
# News / sentiment
# ============================================================
def fetch_news(code: str, max_n: int = 5) -> list[dict]:
    """个股最近新闻."""
    try:
        df = ak.stock_news_em(symbol=code)
        if df is None or df.empty:
            return []
        return df.head(max_n).to_dict("records")
    except Exception as e:
        print(f"[news] {code} failed: {e}")
        return []


# ============================================================
# Batch fetchers (parallel)
# ============================================================
def fetch_klines_parallel(codes: list[str], days: int = 120, max_workers: int = 8) -> dict[str, pd.DataFrame]:
    """Parallel K-line fetch."""
    out: dict[str, pd.DataFrame] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_kline, code, days): code for code in codes}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                df = fut.result()
                if df is not None:
                    out[code] = df
            except Exception as e:
                print(f"[kline-parallel] {code}: {e}")
    return out


def fetch_fund_flow_parallel(codes: list[str], max_workers: int = 8) -> dict[str, dict]:
    out: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(fetch_fund_flow, code): code for code in codes}
        for fut in as_completed(futures):
            code = futures[fut]
            try:
                v = fut.result()
                if v:
                    out[code] = v
            except Exception as e:
                print(f"[fund-flow-parallel] {code}: {e}")
    return out
