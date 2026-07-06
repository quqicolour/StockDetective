# StockDetective

基于 DeepSeek 的 A 股智能选股系统。

## 功能（Phase 1）
- AKShare 拉取沪深 300 实时行情 + 基本面
- 多因子量化打分（动量/估值/质量/资金流）
- DeepSeek LLM 综合分析，给出 Top N 推荐 + 理由
- CLI 输出 + JSON/Markdown 报告落盘

## 快速开始

```bash
# 1. 装依赖
uv venv --python 3.12
source .venv/bin/activate
uv pip install akshare pandas requests python-dotenv rich

# 2. 配 key
cp .env.example .env
# 编辑 .env 填入 DEEPSEEK_API_KEY

# 3. 跑
python -m src.main
```

## 输出
- 控制台 Top 10 推荐表
- `reports/YYYYMMDD_HHMMSS.json` 完整数据
- `reports/YYYYMMDD_HHMMSS.md` 人类可读报告
