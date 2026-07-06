"""Main pipeline: load universe -> fetch data -> score -> LLM -> report."""
from __future__ import annotations

import json
import time
from datetime import datetime
from pathlib import Path

import pandas as pd
from rich.console import Console
from rich.table import Table
from rich.progress import Progress

from .config import config
from .universe import get_universe
from .data import (
    fetch_spot_quote,
    fetch_klines_parallel,
    fetch_fund_flow_parallel,
    fetch_news,
)
from .factors import (
    score_momentum,
    score_technical,
    score_volatility,
    score_value,
    score_fund_flow,
    score_turnover,
    compute_total_score,
)
from .llm import analyze_stock


console = Console()


def run():
    config.ensure_dirs()
    if not config.DEEPSEEK_API_KEY or config.DEEPSEEK_API_KEY == "***":
        console.print("[red]请先在 .env 填入 DEEPSEEK_API_KEY[/red]")
        return

    t0 = time.time()
    console.print(f"[bold cyan]StockDetective[/bold cyan] 启动 | Universe: {config.STOCK_UNIVERSE}")

    # 1) Universe
    with console.status("[cyan]加载股票池...[/cyan]"):
        universe = get_universe()
    console.print(f"[green]✓[/green] 股票池: {len(universe)} 只")

    codes = universe["code"].tolist()

    # 2) Spot quotes (single batch call)
    with console.status("[cyan]拉取实时行情...[/cyan]"):
        spot = fetch_spot_quote(codes)
    console.print(f"[green]✓[/green] 行情: {len(spot)} 只")

    # 3) K-lines (parallel, this is the slow part)
    with console.status("[cyan]拉取 K 线 (并行)...[/cyan]"):
        klines = fetch_klines_parallel(codes, days=120, max_workers=10)
    console.print(f"[green]✓[/green] K线: {len(klines)} 只")

    # 4) Fund flow
    with console.status("[cyan]拉取资金流...[/cyan]"):
        flows = fetch_fund_flow_parallel(codes, max_workers=10)
    console.print(f"[green]✓[/green] 资金流: {len(flows)} 只")

    # 5) Compute factors
    pe_pool = spot["pe"].dropna()
    pb_pool = spot["pb"].dropna()

    rows: list[dict] = []
    for _, r in spot.iterrows():
        code = r["code"]
        kl = klines.get(code)
        if kl is None or len(kl) < 60:
            continue
        flow = flows.get(code, {})
        close = kl["close"]

        factors = {
            "f_momentum": score_momentum(close),
            "f_technical": score_technical(close),
            "f_volatility": score_volatility(close),
            "f_value": score_value(r.get("pe"), r.get("pb"), pe_pool, pb_pool),
            "f_fund_flow": score_fund_flow(flow, r.get("amount", 1)),
            "f_turnover": score_turnover(r.get("turnover", 0)),
        }
        score = compute_total_score({**factors})
        row = {
            "code": code,
            "name": r["name"],
            "price": r.get("price"),
            "change_pct": r.get("change_pct"),
            "pe": r.get("pe"),
            "pb": r.get("pb"),
            "turnover": r.get("turnover"),
            "amount": r.get("amount", 0),
            "main_net_inflow": flow.get("main_net_inflow", 0),
            **factors,
            "score": score["total"],
            "factor_breakdown": score["breakdown"],
        }
        rows.append(row)

    df = pd.DataFrame(rows).sort_values("score", ascending=False)
    console.print(f"[green]✓[/green] 因子计算完成: {len(df)} 只")

    # 6) Pre-filter top candidates for LLM
    pre_top = df.head(config.TOP_N * 2)  # 2x to allow LLM to filter further
    candidates = pre_top.to_dict("records")

    # 7) LLM deep analysis
    console.print(f"[cyan]DeepSeek 分析 {len(candidates)} 只候选...[/cyan]")
    enriched: list[dict] = []
    with Progress() as progress:
        task = progress.add_task("[cyan]LLM 分析中...", total=len(candidates))
        for c in candidates:
            news = fetch_news(c["code"], max_n=5)
            analysis = analyze_stock(c, news)
            c.update(analysis)
            enriched.append(c)
            progress.advance(task)
            time.sleep(0.3)  # rate limit politeness

    # 8) Final ranking by LLM score
    enriched.sort(key=lambda x: x.get("score", 0), reverse=True)
    final = enriched[: config.TOP_N]

    # 9) Display
    _print_report(final)
    # 10) Persist
    _save_report(final, df)

    console.print(f"\n[bold green]完成[/bold green] | 耗时 {time.time() - t0:.1f}s")
    console.print(f"报告路径: {config.REPORTS_DIR}")


def _print_report(rows: list[dict]):
    table = Table(title=f"🏆 Top {len(rows)} 推荐 (LLM 综合判断)", show_lines=False)
    table.add_column("排名", justify="right", style="cyan", no_wrap=True)
    table.add_column("代码", style="magenta")
    table.add_column("名称", style="bold")
    table.add_column("现价", justify="right")
    table.add_column("涨跌%", justify="right")
    table.add_column("PE", justify="right")
    table.add_column("量分", justify="right")
    table.add_column("LLM分", justify="right", style="bold yellow")
    table.add_column("操作", style="bold green")
    table.add_column("理由摘要", style="dim")

    for i, r in enumerate(rows, 1):
        action_color = {"买入": "green", "持有": "cyan", "观望": "yellow", "卖出": "red"}.get(
            r.get("action", ""), "white"
        )
        bd = r.get("factor_breakdown", {})
        reason = r.get("reason", "")[:60] + ("..." if len(r.get("reason", "")) > 60 else "")
        table.add_row(
            str(i),
            r["code"],
            r["name"],
            f"{r.get('price', 0):.2f}",
            f"{r.get('change_pct', 0):+.2f}",
            f"{r.get('pe', 0):.1f}" if pd.notna(r.get("pe")) else "-",
            f"{bd.get('fund_flow', 0):.0f}",
            f"{r.get('score', 0):.0f}",
            f"[{action_color}]{r.get('action', '?')}[/{action_color}]",
            reason,
        )
    console.print(table)


def _save_report(top: list[dict], all_df: pd.DataFrame):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = config.REPORTS_DIR / f"{ts}.json"
    md_path = config.REPORTS_DIR / f"{ts}.md"

    payload = {
        "generated_at": datetime.now().isoformat(),
        "universe": config.STOCK_UNIVERSE,
        "screened_count": len(all_df),
        "top": top,
    }
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str))

    md = [f"# StockDetective 推荐报告\n",
          f"- 生成时间: {payload['generated_at']}",
          f"- 股票池: {config.STOCK_UNIVERSE} ({len(all_df)} 只可分析)",
          f"\n## Top {len(top)} 推荐\n"]
    for i, r in enumerate(top, 1):
        bd = r.get("factor_breakdown", {})
        md.append(f"\n### {i}. {r['name']} ({r['code']}) — {r.get('action', '')}")
        md.append(f"- 现价: {r.get('price')} ({r.get('change_pct'):+.2f}%)")
        md.append(f"- PE: {r.get('pe', 'N/A')}, PB: {r.get('pb', 'N/A')}")
        md.append(f"- 因子: 动量{bd.get('momentum', 0):.0f} 技术{bd.get('technical', 0):.0f} 估值{bd.get('value', 0):.0f} 资金{bd.get('fund_flow', 0):.0f}")
        md.append(f"- LLM 分: **{r.get('score', 0):.0f}/100**")
        md.append(f"- 理由: {r.get('reason', '')}")
        risks = r.get("risks", [])
        if risks:
            md.append(f"- 风险: {', '.join(risks)}")
    md_path.write_text("\n".join(md))


if __name__ == "__main__":
    run()
