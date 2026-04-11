"""Phase 3：AI 結構化摘要（使用 Claude API）"""

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import anthropic
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

from litreview import config
from litreview.utils import (
    auto_relevance_score,
    classify_research_method,
    get_logger,
    save_json,
)

console = Console()

SYSTEM_PROMPT = """\
你是一位學術文獻分析專家，擅長多領域文獻的結構化摘要與評估。
請根據提供的論文全文，以繁體中文輸出結構化摘要。
輸出必須是合法的 JSON 格式，不得包含任何 JSON 以外的文字。
"""

USER_TEMPLATE = """\
研究主題背景：{topic}

請分析以下論文，輸出 JSON 格式的結構化摘要：

論文基本資訊：
- arxiv_id: {arxiv_id}
- title: {title}
- category: {category}

論文全文（可能被截斷）：
---
{text}
---

輸出格式（嚴格 JSON，所有欄位必填）：
{{
  "arxiv_id": "{arxiv_id}",
  "title": "論文完整標題",
  "category": "{category}",
  "subcategory": "子分類（方法名稱或子領域，英文）",
  "year": {year},
  "research_method": "實驗研究 | 理論 | 方法論 | 文獻回顧",
  "key_contribution": "核心貢獻（100-300 字繁體中文）",
  "methodology": "研究方法（100-300 字繁體中文）",
  "key_findings": "主要發現（100-300 字繁體中文）",
  "limitations": "局限性（50-200 字繁體中文）",
  "relevance_to_topic": 0,
  "relevance_note": "與研究主題的相關性說明（60-180 字繁體中文）",
  "score_source": "ai"
}}

相關性評分標準（0-5）：
5=與研究主題高度直接相關、4=廣泛適用的核心方法論、3=間接相關技術、
2=提供背景參考、1=方法論基礎、0=不相關

注意：JSON key "relevance_to_topic" 對應到相關性分數欄位。
"""


def _call_claude(
    client: anthropic.Anthropic,
    paper: dict,
    text: str,
    topic: str = "",
) -> dict | None:
    """呼叫 Claude API 取得結構化摘要"""
    prompt = USER_TEMPLATE.format(
        topic=topic or paper.get("search_category", ""),
        arxiv_id=paper["arxiv_id"],
        title=paper.get("title", ""),
        category=paper.get("search_category", ""),
        year=paper.get("year", 0),
        text=text[:config.TEXT_MAX_CHARS],
    )

    for attempt in range(3):
        try:
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            result = json.loads(raw)
            # 相容舊欄位名稱 relevance_to_labor_market_nlp
            if "relevance_to_topic" not in result and "relevance_to_labor_market_nlp" in result:
                result["relevance_to_topic"] = result.pop("relevance_to_labor_market_nlp")
            return result
        except json.JSONDecodeError:
            console.print(
                f"[yellow]JSON 解析失敗（{paper['arxiv_id']}），重試 {attempt+1}/3[/yellow]"
            )
            time.sleep(2 ** attempt)
        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            console.print(f"[yellow]API Rate Limit，等待 {wait}s[/yellow]")
            time.sleep(wait)
        except Exception as e:
            console.print(f"[red]API 錯誤：{e}[/red]")
            time.sleep(5)
    return None


def _fallback_summary(paper: dict, text: str) -> dict:
    """AI 失敗時以關鍵字評分作為備援摘要"""
    score, source = auto_relevance_score(text)
    research_method = classify_research_method(text)
    return {
        "arxiv_id": paper["arxiv_id"],
        "title": paper.get("title", ""),
        "category": paper.get("search_category", ""),
        "subcategory": "",
        "year": paper.get("year", 0),
        "research_method": research_method,
        "key_contribution": "",
        "methodology": "",
        "key_findings": "",
        "limitations": "",
        "relevance_to_topic": score,
        "relevance_note": "（自動評分，AI 摘要失敗）",
        "score_source": source,
    }


def _process_one_paper(
    paper: dict,
    client: anthropic.Anthropic,
    summaries_dir: Path,
    project_dir: Path,
    topic: str,
) -> dict | None:
    """處理單篇論文的摘要（給 ThreadPoolExecutor 呼叫）"""
    arxiv_id = paper["arxiv_id"]
    out_path = summaries_dir / f"{arxiv_id}.json"

    if out_path.exists():
        return json.loads(out_path.read_text("utf-8"))

    txt_path = project_dir / paper["text_path"]
    if not txt_path.exists() or txt_path.stat().st_size < 100:
        get_logger().debug(f"跳過（無全文）：{arxiv_id}")
        return None

    text = txt_path.read_text("utf-8", errors="replace")
    summary = _call_claude(client, paper, text, topic=topic)

    if summary is None:
        summary = _fallback_summary(paper, text)

    save_json(summary, out_path)
    get_logger().debug(f"摘要完成：{arxiv_id}")
    return summary


def run_summarize(
    papers: list[dict],
    project_dir: Path,
    api_key: str | None = None,
    topic: str = "",
) -> list[dict]:
    """
    對所有論文執行 AI 結構化摘要（並行）。
    每篇獨立儲存為 summaries/{arxiv_id}.json，支援增量補跑。
    """
    import os
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        console.print("[bold red]缺少 ANTHROPIC_API_KEY，跳過 Phase 3[/bold red]")
        console.print("請設定環境變數：export ANTHROPIC_API_KEY=sk-ant-...")
        return []

    logger = get_logger()
    summaries_dir = project_dir / config.SUMMARIES_SUBDIR
    summaries_dir.mkdir(exist_ok=True)

    client = anthropic.Anthropic(api_key=key)

    # 分離已完成 vs 待處理
    to_process = []
    cached_results = []
    for paper in papers:
        out_path = summaries_dir / f"{paper['arxiv_id']}.json"
        if out_path.exists():
            try:
                cached_results.append(json.loads(out_path.read_text("utf-8")))
            except Exception:
                to_process.append(paper)
        else:
            txt_path = project_dir / paper["text_path"]
            if txt_path.exists() and txt_path.stat().st_size >= 100:
                to_process.append(paper)

    console.print(
        f"待摘要：{len(to_process)} 篇，已快取：{len(cached_results)} 篇"
    )
    logger.info(f"Phase 3 開始：待處理 {len(to_process)} 篇，快取 {len(cached_results)} 篇")

    results = list(cached_results)

    if not to_process:
        return results

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]AI 摘要中...", total=len(to_process))

        with ThreadPoolExecutor(max_workers=config.SUMMARIZE_MAX_WORKERS) as pool:
            futures = {
                pool.submit(
                    _process_one_paper,
                    paper,
                    client,
                    summaries_dir,
                    project_dir,
                    topic,
                ): paper
                for paper in to_process
            }
            for future in as_completed(futures):
                summary = future.result()
                if summary:
                    results.append(summary)
                progress.advance(task)

    console.print(
        f"\n[bold green]摘要完成：{len(results)} 篇"
        f"（新增 {len(results) - len(cached_results)} 篇）[/bold green]"
    )
    logger.info(f"Phase 3 完成：共 {len(results)} 篇摘要")
    return results


def load_all_summaries(project_dir: Path) -> dict[str, dict]:
    """載入所有已完成的 summaries/{arxiv_id}.json"""
    summaries_dir = project_dir / config.SUMMARIES_SUBDIR
    result = {}
    if summaries_dir.exists():
        for f in summaries_dir.glob("*.json"):
            try:
                data = json.loads(f.read_text("utf-8"))
                result[data["arxiv_id"]] = data
            except Exception:
                pass
    return result
