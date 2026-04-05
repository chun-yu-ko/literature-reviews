"""Phase 5：生成綜合文獻回顧報告"""

from pathlib import Path

import pandas as pd
from rich.console import Console

from litreview.utils import get_logger

console = Console()

REPORT_TEMPLATE = """\
# 文獻回顧綜合報告：{topic}

> 生成日期：{date}
> 搜尋來源：OpenAlex (arXiv) / PubMed

---

## 一、研究背景與目標

本次文獻回顧主題：**{topic}**

---

## 二、文獻統計摘要

{stats_table}

---

## 三、各類別高相關文獻（relevance ≥ 4）

{high_rel_tables}

---

## 四、研究方法分佈

{method_table}

---

## 五、年份趨勢

{year_table}

---

## 六、重點論文摘要

{key_summaries}

---

## 七、延伸搜尋建議

{keyword_suggestions}

---

*此報告由 LiteratureReview 自動生成，建議人工審閱確認引用正確性。*
"""


def _stats_table(df_study: pd.DataFrame, df_articles: pd.DataFrame) -> str:
    cat_counts = df_articles["search_category"].value_counts().to_dict()
    total = len(df_articles)
    ai_done = (df_study["score_source"] == "ai").sum() if "score_source" in df_study.columns else 0

    lines = [
        "| 項目 | 數值 |",
        "|------|------|",
        f"| 總論文數 | {total} |",
    ]
    for cat, cnt in sorted(cat_counts.items(), key=lambda x: -x[1]):
        lines.append(f"| {cat} | {cnt} |")
    lines += [
        f"| AI 摘要完成 | {ai_done} / {total} |",
        f"| 高相關（score≥4） | {(df_study['relevance_score'].astype(float) >= 4).sum()} |",
    ]
    return "\n".join(lines)


def _high_rel_tables(df_study: pd.DataFrame) -> str:
    df = df_study.copy()
    df["relevance_score"] = pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0)
    high = df[df["relevance_score"] >= 4].sort_values("relevance_score", ascending=False)

    if high.empty:
        return "_（暫無高相關文獻）_"

    lines = ["| 標題 | 類別 | 分數 | 相關性說明 |", "|------|------|------|----------|"]
    for _, row in high.head(20).iterrows():
        title = str(row.get("title", ""))[:60]
        cat = row.get("category", "")
        score = int(row.get("relevance_score", 0))
        note = str(row.get("relevance_note", ""))[:80]
        lines.append(f"| {title} | {cat} | {score} | {note} |")
    return "\n".join(lines)


def _method_table(df_study: pd.DataFrame) -> str:
    counts = df_study["research_method"].value_counts()
    lines = ["| 研究方法 | 篇數 |", "|---------|------|"]
    for method, count in counts.items():
        lines.append(f"| {method} | {count} |")
    return "\n".join(lines)


def _year_table(df_articles: pd.DataFrame) -> str:
    counts = df_articles["year"].value_counts().sort_index()
    lines = ["| 年份 | 篇數 |", "|------|------|"]
    for year, count in counts.items():
        lines.append(f"| {year} | {count} |")
    return "\n".join(lines)


def _key_summaries(df_study: pd.DataFrame) -> str:
    df = df_study.copy()
    df["relevance_score"] = pd.to_numeric(df["relevance_score"], errors="coerce").fillna(0)
    top = df[df["score_source"] == "ai"].nlargest(10, "relevance_score")

    if top.empty:
        return "_（AI 摘要尚未完成，此節待補）_"

    blocks = []
    for _, row in top.iterrows():
        block = f"""### {row.get('title', '')[:80]}

- **ID**：{row.get('arxiv_id', '')}
- **類別**：{row.get('category', '')} / {row.get('subcategory', '')}
- **研究方法**：{row.get('research_method', '')}
- **核心貢獻**：{str(row.get('key_contribution', ''))[:300]}
- **主要發現**：{str(row.get('key_findings', ''))[:300]}
- **相關性**（{row.get('relevance_score', 0)}）：{str(row.get('relevance_note', ''))[:150]}
"""
        blocks.append(block)
    return "\n---\n".join(blocks)


def _keyword_suggestions(project_dir: Path) -> str:
    """載入 keyword_suggestions.md 內容（若存在）"""
    md_path = project_dir / "keyword_suggestions.md"
    if not md_path.exists():
        return "_（尚未執行關鍵字建議分析，可加上 `--suggest` 選項執行）_"

    # 擷取建議關鍵字表格部分
    text = md_path.read_text(encoding="utf-8")
    lines = text.split("\n")
    # 找到 "建議搜尋關鍵字" 到 "研究空白" 之間的內容
    start = next((i for i, l in enumerate(lines) if "建議搜尋關鍵字" in l), None)
    end = next((i for i, l in enumerate(lines) if "研究空白" in l and i > (start or 0)), None)

    if start and end:
        return "\n".join(lines[start:end]).strip()
    return text[:800]  # fallback: 前 800 字元


def run_report(project_dir: Path, topic: str = "文獻回顧") -> Path:
    """生成 literature_review_synthesis.md"""
    from datetime import date

    logger = get_logger()
    study_path = project_dir / "study.csv"
    articles_path = project_dir / "articles.csv"

    if not study_path.exists() or not articles_path.exists():
        console.print("[red]請先執行 Phase 4 生成 CSV 檔案[/red]")
        return project_dir / "literature_review_synthesis.md"

    df_study = pd.read_csv(study_path, encoding="utf-8-sig")
    df_articles = pd.read_csv(articles_path, encoding="utf-8-sig")

    content = REPORT_TEMPLATE.format(
        topic=topic,
        date=date.today().isoformat(),
        stats_table=_stats_table(df_study, df_articles),
        high_rel_tables=_high_rel_tables(df_study),
        method_table=_method_table(df_study),
        year_table=_year_table(df_articles),
        key_summaries=_key_summaries(df_study),
        keyword_suggestions=_keyword_suggestions(project_dir),
    )

    out_path = project_dir / "literature_review_synthesis.md"
    out_path.write_text(content, encoding="utf-8")
    console.print(f"[bold green]報告已生成：{out_path}[/bold green]")
    logger.info(f"Phase 5 完成：報告儲存至 {out_path}")
    return out_path
