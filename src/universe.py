"""Stock universe — define the pool we screen."""
from __future__ import annotations

import akshare as ak
import pandas as pd

from .config import config


# Mapping of universe alias -> AKShare index symbol
UNIVERSE_MAP = {
    "hs300": "sh000300",
    "sz50": "sh000016",
    "zz500": "sh000905",
    "csi1000": "sh000852",
    "all_a": None,  # use full A-share list
}


def load_hs300_constituents() -> pd.DataFrame:
    """沪深300成分股: code, name."""
    df = ak.index_stock_cons_weight_csindex(symbol="000300")
    return df.rename(columns={
        "成分券代码": "code",
        "成分券名称": "name",
    })[["code", "name"]].copy()


def load_all_a() -> pd.DataFrame:
    """全 A 股（剔除 ST/北交所），code, name."""
    df = ak.stock_info_a_code_name()
    return df.rename(columns={"code": "code", "name": "name"})[["code", "name"]].copy()


def get_universe() -> pd.DataFrame:
    """Return (code, name) DataFrame for configured universe."""
    universe = config.STOCK_UNIVERSE.lower()
    if universe == "all_a":
        df = load_all_a()
    elif universe in UNIVERSE_MAP and UNIVERSE_MAP[universe]:
        df = load_hs300_constituents() if universe == "hs300" else None
        if df is None:
            raise NotImplementedError(f"Universe '{universe}' not wired up yet, use hs300")
    else:
        raise ValueError(f"Unknown universe: {config.STOCK_UNIVERSE}")

    # Normalize codes: AKShare sometimes uses 6-digit, sometimes with sh/sz prefix
    df["code"] = df["code"].astype(str).str.zfill(6)
    return df.reset_index(drop=True)


if __name__ == "__main__":
    u = get_universe()
    print(f"Universe: {config.STOCK_UNIVERSE} | stocks: {len(u)}")
    print(u.head())
