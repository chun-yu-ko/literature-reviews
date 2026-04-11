"""Phase 3.5：根據現有文獻自動建議延伸搜尋關鍵字"""

import json
import time
from pathlib import Path

import anthropic
from rich.console import Console

from litreview.utils import get_logger

console = Console()


def _extract_json_block(text: str) -> str:
    """從可能包含 markdown code block 的文字中提取 JSON 內容"""
    stripped = text.strip()
    if stripped.startswith("```"):
        first_newline = stripped.find("\n")
        if first_newline == -1:
            return stripped
        last_fence = stripped.rfind("```", first_newline)
        if last_fence > first_newline:
            return stripped[first_newline + 1:last_fence].strip()
        return stripped[first_newline + 1:].strip()
    return stripped


_SYSTEM_PROMPT = """\
你是一位學術文獻分析專家，擅長識別研究主題的知識空白與延伸方向。
根據提供的文獻資訊，分析其中反覆出現的方法、概念與術語，提出應補充搜尋的關鍵字。
輸出必須是合法 JSON 格式，不含任何 JSON 以外的文字。
"""

_USER_TEMPLATE = """\
研究主題：{topic}

以下是目前已收集到的 {n_papers} 篇文獻的標題與子分類：
---
{paper_list}
---

請分析上述文獻，找出：
1. 反覆出現的核心方法或術語
2. 文獻中提及但尚未覆蓋的相關主題
3. 可能遺漏的重要子領域

輸出 JSON 格式：
{{
  "observed_themes": ["主題1", "主題2", ...],
  "suggested_queries": [
    {{"query": "搜尋關鍵字（英文）", "reason": "原因說明（中文）", "priority": "high|medium|low"}},
    ...
  ],
  "coverage_gaps": ["空白領域1", "空白領域2", ...]
}}

suggested_queries 請給出 5-10 個英文搜尋關鍵字，優先考慮可直接用於 OpenAlex 或 PubMed 的術語。
"""


def run_suggest(
    papers: list[dict],
    summaries: dict[str, dict],
    topic: str,
    project_dir: Path,
    api_key: str | None = None,
) -> dict:
    """
    分析現有文獻，建議延伸搜尋關鍵字。
    回傳結果 dict，同時儲存至 keyword_suggestions.json 與 keyword_suggestions.md。
    """
    import os
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        console.print("[yellow]未設定 ANTHROPIC_API_KEY，跳過關鍵字建議[/yellow]")
        return {}

    logger = get_logger()
    logger.info("Phase 3.5：關鍵字建議分析開始")

    # 整理文獻清單（優先使用有 AI 摘要的，最多 80 筆）
    paper_lines = []
    for p in papers[:80]:
        aid = p["arxiv_id"]
        title = p.get("title", "")[:80]
        summary = summaries.get(aid, {})
        subcat = summary.get("subcategory", "") if summary else ""
        method = summary.get("research_method", "") if summary else ""
        line = f"- {title}"
        if subcat:
            line += f"  [子分類: {subcat}]"
        if method:
            line += f"  [方法: {method}]"
        paper_lines.append(line)

    paper_list = "\n".join(paper_lines)
    prompt = _USER_TEMPLATE.format(
        topic=topic,
        n_papers=len(paper_lines),
        paper_list=paper_list,
    )

    client = anthropic.Anthropic(api_key=key)
    result = None

    for attempt in range(3):
        try:
            msg = client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=_SYSTEM_PROMPT,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = msg.content[0].text.strip()
            raw = _extract_json_block(raw)
            result = json.loads(raw)
            break
        except json.JSONDecodeError:
            console.print(f"[yellow]關鍵字建議 JSON 解析失敗（{attempt+1}/3）[/yellow]")
            time.sleep(2 ** attempt)
        except anthropic.RateLimitError:
            wait = 60 * (attempt + 1)
            console.print(f"[yellow]Rate Limit，等待 {wait}s[/yellow]")
            time.sleep(wait)
        except Exception as e:
            console.print(f"[red]關鍵字建議 API 錯誤：{e}[/red]")
            time.sleep(5)

    if result is None:
        logger.warning("關鍵字建議失敗，回傳空結果")
        return {}

    # 儲存 JSON
    json_path = project_dir / "keyword_suggestions.json"
    json_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # 儲存易讀的 Markdown
    md_path = project_dir / "keyword_suggestions.md"
    _write_md(result, topic, md_path)

    # Console 輸出
    console.print("\n[bold cyan]── 延伸搜尋關鍵字建議 ──[/bold cyan]")
    suggested = result.get("suggested_queries", [])
    for item in suggested:
        priority = item.get("priority", "medium")
        color = {"high": "red", "medium": "yellow", "low": "dim"}.get(priority, "white")
        console.print(
            f"  [{color}][{priority.upper()}][/{color}] "
            f"[bold]{item.get('query', '')}[/bold]  "
            f"→ {item.get('reason', '')}"
        )

    gaps = result.get("coverage_gaps", [])
    if gaps:
        console.print(f"\n[dim]研究空白：{', '.join(gaps)}[/dim]")

    console.print(f"\n[green]建議已儲存：{md_path}[/green]")
    logger.info(f"關鍵字建議完成，共 {len(suggested)} 條，儲存至 {md_path}")
    return result


def _write_md(result: dict, topic: str, path: Path) -> None:
    """將建議結果寫成 Markdown"""
    from datetime import date

    lines = [
        f"# 延伸搜尋關鍵字建議：{topic}",
        f"\n> 生成日期：{date.today().isoformat()}",
        "\n---\n",
        "## 觀察到的核心主題\n",
    ]
    for theme in result.get("observed_themes", []):
        lines.append(f"- {theme}")

    lines += ["\n---\n", "## 建議搜尋關鍵字\n",
              "| 優先級 | 搜尋關鍵字 | 建議原因 |",
              "|--------|------------|----------|"]
    for item in result.get("suggested_queries", []):
        priority_map = {"high": "🔴 高", "medium": "🟡 中", "low": "🟢 低"}
        p_label = priority_map.get(item.get("priority", "medium"), "中")
        lines.append(
            f"| {p_label} | `{item.get('query', '')}` | {item.get('reason', '')} |"
        )

    lines += ["\n---\n", "## 研究空白\n"]
    for gap in result.get("coverage_gaps", []):
        lines.append(f"- {gap}")

    path.write_text("\n".join(lines), encoding="utf-8")
