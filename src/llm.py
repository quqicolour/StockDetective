"""DeepSeek LLM client for stock analysis."""
from __future__ import annotations

import json
import re
import time
from typing import Optional

import requests

from .config import config


SYSTEM_PROMPT = """你是 StockDetective，一个资深 A 股量化分析师。
你的任务是基于提供的多因子数据和近期新闻，给出专业、谨慎、可执行的投资建议。

要求：
1. 客观解读数据，避免幻觉和过度乐观
2. 明确指出风险点（高 PE/超买/资金流出/负面新闻）
3. 给出明确的"买入/持有/观望/卖出"评级之一
4. 评分范围 0-100（综合信心度）
5. 200 字以内简洁有力
6. 用中文输出"""


def analyze_stock(stock_data: dict, news: list[dict]) -> dict:
    """Send one stock's data to DeepSeek for analysis.

    Returns: {action, score, reason, risks}
    """
    user_prompt = _build_prompt(stock_data, news)

    payload = {
        "model": config.DEEPSEEK_MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ],
        "temperature": 0.3,
        "max_tokens": 800,
        "response_format": {"type": "json_object"},
    }

    headers = {
        "Authorization": f"Bearer {config.DEEPSEEK_API_KEY}",
        "Content-Type": "application/json",
    }

    url = f"{config.DEEPSEEK_BASE}/v1/chat/completions"

    for attempt in range(3):
        try:
            r = requests.post(url, json=payload, headers=headers, timeout=config.HTTP_TIMEOUT)
            if r.status_code == 429:
                time.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            content = r.json()["choices"][0]["message"]["content"]
            return _parse_llm_response(content)
        except Exception as e:
            print(f"[llm] {stock_data.get('code')} attempt {attempt+1} failed: {e}")
            if attempt == 2:
                return {
                    "action": "观望",
                    "score": 50,
                    "reason": f"分析失败: {e}",
                    "risks": ["LLM 不可用"],
                }
    return {"action": "观望", "score": 50, "reason": "rate-limited", "risks": []}


def _build_prompt(d: dict, news: list[dict]) -> str:
    bd = d.get("factor_breakdown", {})
    news_txt = "\n".join([
        f"- {n.get('发布时间', '')}: {n.get('新闻标题', '')}"
        for n in news[:5]
    ]) or "（无近期新闻）"

    return f"""股票: {d.get('name')} ({d.get('code')})
现价: {d.get('price')} 元  涨跌: {d.get('change_pct')}%
PE(动): {d.get('pe', 'N/A')}  PB: {d.get('pb', 'N/A')}  换手率: {d.get('turnover', 'N/A')}%
量能: 成交额 {d.get('amount', 0) / 1e8:.2f} 亿

量化因子评分 (0-100):
- 动量: {bd.get('momentum', 50)}
- 技术面: {bd.get('technical', 50)}
- 波动率: {bd.get('volatility', 50)}
- 估值: {bd.get('value', 50)}
- 资金流: {bd.get('fund_flow', 50)}
- 换手: {bd.get('turnover', 50)}
- 综合分: {d.get('score', 0)}

主力净流入: {d.get('main_net_inflow', 0) / 1e8:.3f} 亿

近期新闻:
{news_txt}

请输出 JSON:
{{
  "action": "买入" | "持有" | "观望" | "卖出",
  "score": 0-100 的综合信心分,
  "reason": "核心推荐理由（2-3 句话）",
  "risks": ["风险点1", "风险点2"]
}}"""


def _parse_llm_response(content: str) -> dict:
    """Parse JSON from LLM, fallback to regex extraction."""
    try:
        return json.loads(content)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", content, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                pass
        return {
            "action": "观望",
            "score": 50,
            "reason": content[:200],
            "risks": ["解析失败"],
        }
