"""一次性脚本：筛选 A 股中所有涉及"存储"概念的股票.

策略:
1) 通过 akshare stock_board_concept_name_em 找名字带"存储/芯片/半导体/DRAM/NAND/内存/SSD/数据"的概念板块
2) 拉每个板块的成分股,合并去重
3) 补充: 用关键词在股票名称上二次扫描(防止漏网之鱼)
4) 与 dump_all_stocks 生成的 storage_result.json 交叉对照,补全行情/估值数据
5) 输出 data/storage_concept_stocks.json

运行:
    python -m src.scripts.filter_storage_stocks
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


# 概念板块名关键词
CONCEPT_KEYWORDS = [
    "存储", "存储器", "存储芯片", "DRAM", "NAND", "闪存", "内存条", "内存",
    "SSD", "固态硬盘", "硬盘", "磁盘", "云存储", "数据存储", "存储设备",
    "半导体", "芯片", "集成电路", "IC 设计", "IC 制造", "封装测试",
    "国产芯片", "国产替代", "信创", "数字经济", "数据中心", "数据要素",
    "服务器", "光模块", "CPO",
]

# 股票名称关键词（防漏）
NAME_KEYWORDS = [
    "存储", "存储", "闪存", "内存", "存储芯片", "DRAM", "NAND",
    "兆易", "紫光", "长江存储", "佰维", "江波龙", "朗科", "深科技",
    "香农芯创", "德明利", "恒烁", "东芯", "普冉", "聚辰", "北京君正",
    "同有科技", "海量数据", "中科曙光", "易华录", "同方", "中国长城",
    "澜起", "聚辰", "复旦微电", "宏杉", "宏图",
    "SSD", "固态", "硬盘",
    # 半导体设备/材料
    "北方华创", "中微", "长川", "华峰测控", "精测", "拓荆", "芯源",
    "安集", "沪硅", "立昂微", "雅克", "江丰", "有研",
    # IC 设计/制造
    "中芯", "华虹", "晶合", "士兰微", "华润微", "扬杰", "闻泰", "韦尔",
    "卓胜微", "圣邦", "思瑞浦", "纳芯微", "艾为", "力芯微",
    "长电", "通富", "华天", "晶方",
    # 服务器/数据中心
    "浪潮", "紫光股份", "中科曙光", "宝信", "光环", "数据港",
]

CONCEPT_PATTERN = re.compile("|".join(re.escape(k) for k in CONCEPT_KEYWORDS), re.IGNORECASE)
NAME_PATTERN = re.compile("|".join(re.escape(k) for k in NAME_KEYWORDS), re.IGNORECASE)


def _sf(v) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if pd.isna(f):
            return None
        return round(f, 4)
    except (TypeError, ValueError):
        return None


def fetch_storage_concept_codes() -> dict[str, list[str]]:
    """Return {code: [concept_name, ...]} for all storage-related concepts."""
    print("[1/3] 拉取概念板块列表...")
    try:
        df = ak.stock_board_concept_name_em()
    except Exception as e:
        print(f"    失败: {e}")
        return {}

    matched = df[df["板块名称"].str.contains(CONCEPT_PATTERN, na=False)]
    concepts = matched["板块名称"].tolist()
    print(f"    命中概念板块: {len(concepts)} 个")
    for c in concepts[:15]:
        print(f"      - {c}")
    if len(concepts) > 15:
        print(f"      ... 共 {len(concepts)} 个")

    code2concepts: dict[str, list[str]] = {}
    for i, c in enumerate(concepts, 1):
        try:
            cons = ak.stock_board_concept_cons_em(symbol=c)
            for code in cons["代码"].astype(str).str.zfill(6):
                code2concepts.setdefault(code, []).append(c)
            print(f"    [{i:>3d}/{len(concepts)}] {c:<20s} -> {len(cons):>3d} 只")
        except Exception as e:
            print(f"    [{i:>3d}/{len(concepts)}] {c} 失败: {e}")
        time.sleep(0.15)
    return code2concepts


def expand_by_name(code2concepts: dict[str, list[str]]) -> dict[str, list[str]]:
    """二次扫描: 拉全 A 名称, 用 NAME_PATTERN 命中补充."""
    print("\n[2/3] 名称关键词二次扫描...")
    try:
        df = ak.stock_info_a_code_name()
    except Exception as e:
        print(f"    失败: {e}")
        return code2concepts
    df["code"] = df["代码"].astype(str).str.zfill(6)
    df["name"] = df["名称"].astype(str)
    hits = df[df["name"].str.contains(NAME_PATTERN, na=False)]
    added = 0
    for _, r in hits.iterrows():
        code = r["code"]
        if code not in code2concepts:
            code2concepts[code] = ["(name_keyword_match)"]
            added += 1
    print(f"    名称扫描补充: {added} 只 (总 {len(code2concepts)} 只)")
    return code2concepts


def enrich_with_quotes(code2concepts: dict[str, list[str]]) -> list[dict]:
    """交叉 storage_result.json 补全行情/估值数据."""
    print("\n[3/3] 补全行情数据...")
    storage_path = config.DATA_DIR / "storage_result.json"
    spot_lookup: dict[str, dict] = {}
    if storage_path.exists():
        full = json.loads(storage_path.read_text())
        spot_lookup = {s["code"]: s for s in full.get("stocks", [])}
        print(f"    命中 storage_result.json: {len(spot_lookup)} 只行情")
    else:
        print("    [WARN] storage_result.json 不存在, 请先跑 dump_all_stocks")
        # 兜底直接拉
        try:
            df = ak.stock_zh_a_spot_em()
            df["code"] = df["代码"].astype(str).str.zfill(6)
            for _, r in df.iterrows():
                spot_lookup[r["code"]] = {"name": r["名称"]}
        except Exception as e:
            print(f"    兜底拉取也失败: {e}")

    results = []
    for code, concepts in code2concepts.items():
        s = spot_lookup.get(code, {})
        mcap = s.get("total_mcap_yi")
        results.append({
            "code": code,
            "name": s.get("name", ""),
            "price": s.get("price"),
            "change_pct": s.get("change_pct"),
            "change_pct_disp": s.get("change_pct_disp"),
            "pe": s.get("pe"),
            "pb": s.get("pb"),
            "turnover_pct": s.get("turnover_pct"),
            "total_mcap_yi": mcap,
            "total_mcap_disp": s.get("total_mcap_disp"),
            "amount_disp": s.get("amount_disp"),
            "mcap_rank": s.get("mcap_rank"),
            "concepts": concepts,
        })

    # 排序: 有市值的优先
    results.sort(key=lambda r: (r.get("total_mcap_yi") is None, -(r.get("total_mcap_yi") or 0)))
    return results


def main():
    config.ensure_dirs()
    t0 = time.time()
    code2concepts = fetch_storage_concept_codes()
    code2concepts = expand_by_name(code2concepts)
    rows = enrich_with_quotes(code2concepts)

    # 分类
    has_mcap = [r for r in rows if r.get("total_mcap_yi") is not None]
    no_mcap = [r for r in rows if r.get("total_mcap_yi") is None]

    output = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "strategy": "概念板块匹配 + 名称关键词二次扫描",
        "matched_concepts": sorted(set(c for cs in code2concepts.values() for c in cs)),
        "counts": {
            "total": len(rows),
            "with_quote": len(has_mcap),
            "without_quote": len(no_mcap),
        },
        "stocks": rows,
        "top_lists": {
            "by_total_mcap": [
                {
                    "rank": i + 1,
                    "code": r["code"],
                    "name": r["name"],
                    "total_mcap_disp": r["total_mcap_disp"],
                    "pe": r["pe"],
                    "change_pct_disp": r["change_pct_disp"],
                    "concepts": r["concepts"][:3],  # 最多展示 3 个概念
                }
                for i, r in enumerate([x for x in has_mcap][:30])
            ],
        },
    }

    out_path = config.DATA_DIR / "storage_concept_stocks.json"
    out_path.write_text(json.dumps(output, ensure_ascii=False, indent=2))
    size_mb = out_path.stat().st_size / 1024 / 1024
    print(f"\n✓ 写入 {out_path} ({size_mb:.2f} MB)")
    print(f"   总数: {len(rows)} 只 | 含行情: {len(has_mcap)} | 缺行情(停牌/退市): {len(no_mcap)}")
    print(f"\n[存储概念 Top 30 按市值]")
    for r in output["top_lists"]["by_total_mcap"][:30]:
        concepts_short = ", ".join(r["concepts"][:2])
        print(f"  {r['rank']:>3d}. {r['code']} {r['name']:<10s} "
              f"市值 {r['total_mcap_disp']:>10s} | "
              f"PE {r['pe'] or '-':>7} | "
              f"涨跌 {r['change_pct_disp'] or '-':>7s} | "
              f"[{concepts_short}]")
    print(f"\n耗时 {time.time() - t0:.1f}s")


if __name__ == "__main__":
    main()
