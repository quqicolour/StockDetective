"""一次性脚本：拉取全部 A 股 + 行业/概念标签 + 格式化展示，输出 storage_result.json

运行:
    python -m src.scripts.dump_all_stocks

输出: data/storage_result.json
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path

import akshare as ak
import pandas as pd

from ..config import config


# ============================================================
# Number formatting
# ============================================================
def fmt_money_yi(value: float | None) -> str | None:
    """Format 亿 with unit suffix. 1234.56 -> '1234.56 亿'."""
    if value is None or pd.isna(value):
        return None
    v = float(value)
    if abs(v) >= 10000:
        return f"{v / 10000:.2f} 万亿"
    return f"{v:.2f} 亿"


def fmt_pct(value: float | None, signed: bool = False) -> str | None:
    if value is None or pd.isna(value):
        return None
    v = float(value)
    return f"{v:+.2f}%" if signed else f"{v:.2f}%"


def fmt_num(value: float | None, decimals: int = 2) -> str | None:
    if value is None or pd.isna(value):
        return None
    return f"{float(value):,.{decimals}f}"


def fmt_volume(value: float | None) -> str | None:
    """成交量 -> 万手/亿手."""
    if value is None or pd.isna(value):
        return None
    v = float(value)
    # akshare 成交量单位是"手"（1 手 = 100 股）
    hands = v
    if hands >= 1e8:
        return f"{hands / 1e8:.2f} 亿手"
    if hands >= 1e4:
        return f"{hands / 1e4:.2f} 万手"
    return f"{hands:.0f} 手"


# ============================================================
# Code -> exchange prefix helper
# ============================================================
def exchange_prefix(code: str) -> str:
    """Determine market from stock code."""
    code = str(code).zfill(6)
    if code.startswith(("60", "68", "90")):
        return "沪"
    if code.startswith(("00", "30", "20")):
        return "深"
    if code.startswith(("43", "83", "87", "88")):
        return "北"
    return "?"


# ============================================================
# Industry & concept lookup
# ============================================================
INDUSTRY_CACHE_PATH = config.CACHE_DIR / "stock_industry_map.json"
CONCEPT_CACHE_PATH = config.CACHE_DIR / "stock_concept_map.json"


def fetch_industry_map() -> dict[str, str]:
    """code -> 所属行业 (e.g. '半导体'). Pulls once, caches to disk."""
    if INDUSTRY_CACHE_PATH.exists():
        try:
            return json.loads(INDUSTRY_CACHE_PATH.read_text())
        except Exception:
            pass

    print("    [industry] 拉取行业分类映射...")
    out: dict[str, str] = {}
    # stock_info_industry_dict 实际不存在；用 stock_board_industry_cons_em 逐板块拉再汇总太慢
    # 折中：直接用 stock_individual_info_em 不行（限频），用东方财富个股主营接口也慢
    # 实战做法：akshare 提供 stock_profit_forecast / stock_zyjs_ths 主营介绍。 这里跳过行业，只跑概念
    print("    [industry] 跳过（个股级行业数据接口需逐只调用，几千只太慢）")
    INDUSTRY_CACHE_PATH.write_text(json.dumps(out))
    return out


def fetch_concept_map(extra_concepts: list[str] | None = None) -> dict[str, list[str]]:
    """code -> 涉及的概念板块列表.

    Strategy:
    1) 拉取概念板块列表
    2) 筛选与存储/芯片/半导体/数字 相关的板块
    3) 拉每个板块的成分股，构建反向索引
    """
    if CONCEPT_CACHE_PATH.exists():
        try:
            cache = json.loads(CONCEPT_CACHE_PATH.read_text())
            if cache.get("concepts"):  # 简单校验非空
                print(f"    [concept] 命中缓存 ({len(cache.get('map', {}))} 只)")
                return cache["map"]
        except Exception:
            pass

    print("    [concept] 拉取概念板块列表...")
    try:
        df = ak.stock_board_concept_name_em()
    except Exception as e:
        print(f"    [concept] 失败: {e}")
        return {}

    # 板块名关键词（覆盖半导体存储全产业链）
    KEYWORDS = [
        "存储", "存储器", "存储芯片", "DRAM", "NAND", "闪存", "内存",
        "SSD", "硬盘", "磁盘", "云存储", "数据存储", "存储设备",
        "半导体", "芯片", "集成电路", "IC", "国产芯片", "国产替代",
        "数字经济", "数据中心", "数据要素", "信创", "服务器", "光模块",
    ]
    pattern = re.compile("|".join(re.escape(k) for k in KEYWORDS), re.IGNORECASE)
    matched_concepts = df[df["板块名称"].str.contains(pattern, na=False)]["板块名称"].tolist()
    print(f"    [concept] 命中板块: {len(matched_concepts)} 个 -> {matched_concepts[:8]}...")

    # 拉每个板块成分股
    code_to_concepts: dict[str, list[str]] = {}
    for concept in matched_concepts:
        try:
            cons = ak.stock_board_concept_cons_em(symbol=concept)
            for code in cons["代码"].astype(str).str.zfill(6):
                code_to_concepts.setdefault(code, []).append(concept)
            time.sleep(0.2)  # 限频
        except Exception as e:
            print(f"    [concept] 板块 {concept} 失败: {e}")

    # 缓存
    CONCEPT_CACHE_PATH.write_text(json.dumps({
        "concepts": matched_concepts,
        "map": code_to_concepts,
    }, ensure_ascii=False))
    print(f"    [concept] 写入缓存: {len(code_to_concepts)} 只")
    return code_to_concepts


# ============================================================
# Main
# ============================================================
def main():
    config.ensure_dirs()

    out: dict = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": "akshare",
        "summary": {},
        "stocks": [],
    }

    # 1) 全 A 股代码 + 名称
    print("[1/5] 拉取全 A 股代码列表...")
    df_code = ak.stock_info_a_code_name()
    df_code = df_code.rename(columns={"代码": "code", "名称": "name"})
    df_code["code"] = df_code["code"].astype(str).str.zfill(6)
    print(f"      拿到 {len(df_code)} 只")

    # 2) 实时行情
    print("[2/5] 拉取实时行情...")
    df_spot = ak.stock_zh_a_spot_em()
    df_spot = df_spot.rename(columns={
        "代码": "code", "名称": "name", "最新价": "price", "涨跌幅": "change_pct",
        "成交量": "volume", "成交额": "amount", "换手率": "turnover",
        "市盈率-动态": "pe", "市净率": "pb", "总市值": "total_mcap", "流通市值": "circ_mcap",
        "最高": "high", "最低": "low", "今开": "open", "昨收": "prev_close",
        "60日涨跌幅": "chg_60d", "年初至今涨跌幅": "chg_ytd",
        "振幅": "amplitude", "量比": "volume_ratio",
    })
    keep = [c for c in [
        "code", "name", "price", "change_pct", "volume", "amount", "turnover",
        "pe", "pb", "total_mcap", "circ_mcap",
        "open", "high", "low", "prev_close", "amplitude", "volume_ratio",
        "chg_60d", "chg_ytd",
    ] if c in df_spot.columns]
    df_spot = df_spot[keep].copy()
    df_spot["code"] = df_spot["code"].astype(str).str.zfill(6)
    print(f"      拿到 {len(df_spot)} 条")

    # 3) 行业 / 概念标签
    print("[3/5] 拉取行业 / 概念标签...")
    industry_map = fetch_industry_map()
    concept_map = fetch_concept_map()

    # 4) 组装结构化 + 展示友好输出
    print("[4/5] 组装输出...")
    stocks = []
    for _, row in df_spot.iterrows():
        code = str(row["code"])
        price = row.get("price")
        change_pct = row.get("change_pct")
        total_mcap_yi = (row.get("total_mcap") or 0) / 1e8
        circ_mcap_yi = (row.get("circ_mcap") or 0) / 1e8
        amount_yi = (row.get("amount") or 0) / 1e8

        stocks.append({
            # Identity
            "code": code,
            "name": str(row.get("name", "")),
            "market": exchange_prefix(code),
            # Quote
            "price": _sf(price),
            "change_pct": _sf(change_pct),
            "change_pct_disp": fmt_pct(change_pct, signed=True),
            "amplitude_pct": _sf(row.get("amplitude")),
            "volume_ratio": _sf(row.get("volume_ratio")),
            "turnover_pct": _sf(row.get("turnover")),
            # OHLC
            "open": _sf(row.get("open")),
            "high": _sf(row.get("high")),
            "low": _sf(row.get("low")),
            "prev_close": _sf(row.get("prev_close")),
            # Money (raw + display)
            "amount_yi": _sf(amount_yi),
            "amount_disp": fmt_money_yi(amount_yi),
            "total_mcap_yi": _sf(total_mcap_yi),
            "total_mcap_disp": fmt_money_yi(total_mcap_yi),
            "circ_mcap_yi": _sf(circ_mcap_yi),
            "circ_mcap_disp": fmt_money_yi(circ_mcap_yi),
            "volume_hands": _sf(row.get("volume")),
            "volume_disp": fmt_volume(row.get("volume")),
            # Valuation
            "pe": _sf(row.get("pe")),
            "pb": _sf(row.get("pb")),
            # Performance
            "chg_60d_pct": _sf(row.get("chg_60d")),
            "chg_ytd_pct": _sf(row.get("chg_ytd")),
            # Tags
            "industry": industry_map.get(code, ""),
            "concepts": concept_map.get(code, []),
        })

    # 市值排序 + 排名
    stocks.sort(key=lambda s: s.get("total_mcap_yi") or 0, reverse=True)
    for i, s in enumerate(stocks, 1):
        s["mcap_rank"] = i

    # 5) Summary
    print("[5/5] 写入 summary + 落盘...")
    valid_pe = [s["pe"] for s in stocks if s["pe"] is not None and s["pe"] > 0]
    valid_change = [s["change_pct"] for s in stocks if s["change_pct"] is not None]
    up = sum(1 for c in valid_change if c > 0)
    down = sum(1 for c in valid_change if c < 0)
    flat = len(valid_change) - up - down

    out["summary"] = {
        "total_stocks": len(stocks),
        "up": up,
        "down": down,
        "flat": flat,
        "limit_up": sum(1 for s in stocks if s.get("change_pct") and s["change_pct"] >= 9.9),
        "limit_down": sum(1 for s in stocks if s.get("change_pct") and s["change_pct"] <= -9.9),
        "median_pe": round(float(pd.Series(valid_pe).median()), 2) if valid_pe else None,
        "total_mcap_yi": round(sum(s.get("total_mcap_yi") or 0 for s in stocks), 2),
        "total_mcap_disp": fmt_money_yi(sum(s.get("total_mcap_yi") or 0 for s in stocks)),
    }
    out["stocks"] = stocks

    # Top 列表（多维度）
    out["top_lists"] = {
        "by_total_mcap": _top(stocks, "total_mcap_yi", 20, fmt_money_yi),
        "by_change_pct_up": _top(stocks, "change_pct", 20, lambda v: fmt_pct(v, signed=True)),
        "by_change_pct_down": _top(stocks, "change_pct", 20, lambda v: fmt_pct(v, signed=True), reverse=False),
        "by_turnover": _top(stocks, "turnover_pct", 20, lambda v: fmt_pct(v)),
        "by_pe_low": [  # 最低 PE（正数）
            s for s in sorted(stocks, key=lambda s: s.get("pe") or 1e9)
            if s.get("pe") is not None and s["pe"] > 0
        ][:20],
    }

    out_path = config.DATA_DIR / "storage_result.json"
    out_path.write_text(json.dumps(out, ensure_ascii=False, indent=2))
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n✓ 写入 {out_path} ({size_mb:.2f} MB, {len(stocks)} 只)")
    print(f"\n[行情概览] 总市值 {out['summary']['total_mcap_disp']} | "
          f"涨 {up} / 跌 {down} / 平 {flat} | "
          f"涨停 {out['summary']['limit_up']} / 跌停 {out['summary']['limit_down']} | "
          f"中位 PE {out['summary']['median_pe']}")

    print("\n[市值 Top 10]")
    for s in out["top_lists"]["by_total_mcap"][:10]:
        print(f"  {s['mcap_rank']:>4d}. {s['code']} {s['name']:<10s} "
              f"价 {s['change_pct_disp']:>8s} | "
              f"市值 {s['total_mcap_disp']:>10s} | "
              f"PE {s['pe'] or '-':>7} | "
              f"换手 {s['turnover_pct'] or 0:>5.2f}%")


def _top(stocks: list[dict], key: str, n: int, fmt, reverse: bool = True) -> list[dict]:
    valid = [s for s in stocks if s.get(key) is not None]
    valid.sort(key=lambda s: s[key], reverse=reverse)
    out = []
    for s in valid[:n]:
        s2 = {
            "rank": len(out) + 1,
            "code": s["code"], "name": s["name"],
            "market": s["market"],
            key: s[key],
            f"{key}_disp": fmt(s[key]),
            "price": s.get("price"),
            "change_pct_disp": s.get("change_pct_disp"),
        }
        out.append(s2)
    return out


def _sf(v) -> float | None:
    """safe float."""
    if v is None:
        return None
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


if __name__ == "__main__":
    t0 = time.time()
    main()
    print(f"\n耗时 {time.time() - t0:.1f}s")
