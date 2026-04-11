"""Phase 4：建構 study.csv + articles.csv"""

import csv
from pathlib import Path

import pandas as pd
from rich.console import Console

from litreview.summarize import load_all_summaries
from litreview.utils import (
    auto_relevance_score,
    classify_research_method,
    load_json,
    safe_resolve,
)

console = Console()

STUDY_COLS = [
    "arxiv_id", "title", "category", "subcategory", "year",
    "research_method", "key_contribution", "methodology",
    "key_findings", "limitations", "relevance_score", "relevance_note",
    "score_source",
]

ARTICLES_COLS = [
    "arxiv_id", "title", "authors", "year", "cited_by",
    "search_category", "all_categories", "search_query",
    "topic", "field", "doi", "pdf_url", "text_length",
    "subcategory", "research_method", "relevance_score", "relevance_note",
    "key_contribution",
]


def _merge_paper(meta: dict, summary: dict | None, project_dir: Path) -> dict:
    """合併元數據 + AI 摘要，產生完整欄位"""
    arxiv_id = meta["arxiv_id"]

    # 讀取全文用於自動評分備援
    txt_path = safe_resolve(project_dir, meta.get("text_path", f"texts/{arxiv_id}.txt"))
    text_snippet = ""
    if txt_path.exists():
        text_snippet = txt_path.read_text("utf-8", errors="replace")[:5000]

    if summary:
        # 優先採用 AI 摘要（相容新舊欄位名稱）
        score = int(
            summary.get("relevance_to_topic")
            or summary.get("relevance_to_labor_market_nlp")
            or 0
        )
        score_source = summary.get("score_source", "ai")
        research_method = summary.get("research_method") or classify_research_method(text_snippet)
    else:
        # 備援：關鍵字自動評分
        score, score_source = auto_relevance_score(text_snippet)
        research_method = classify_research_method(text_snippet)

    return {
        # 基本元數據
        "arxiv_id": arxiv_id,
        "title": meta.get("title", ""),
        "authors": meta.get("authors", ""),
        "year": meta.get("year", 0),
        "cited_by": meta.get("cited_by", 0),
        "search_category": meta.get("search_category", ""),
        "all_categories": ", ".join(meta.get("all_categories", [meta.get("search_category", "")])),
        "search_query": meta.get("search_query", ""),
        "topic": meta.get("topic", ""),
        "field": meta.get("field", ""),
        "doi": meta.get("doi", ""),
        "pdf_url": meta.get("pdf_url", ""),
        "text_length": meta.get("text_length", 0),
        # AI 摘要欄位
        "category": summary.get("category", meta.get("search_category", "")) if summary else meta.get("search_category", ""),
        "subcategory": summary.get("subcategory", "") if summary else "",
        "research_method": research_method,
        "key_contribution": (summary.get("key_contribution", "") if summary else "")[:600],
        "methodology": summary.get("methodology", "") if summary else "",
        "key_findings": summary.get("key_findings", "") if summary else "",
        "limitations": summary.get("limitations", "") if summary else "",
        "relevance_score": str(score),
        "relevance_note": summary.get("relevance_note", "") if summary else "",
        "score_source": score_source,
    }


def run_build_csv(project_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    合併 articles_metadata.json + summaries/*.json → study.csv + articles.csv
    """
    meta_path = project_dir / "articles_metadata.json"
    if not meta_path.exists():
        console.print("[red]找不到 articles_metadata.json，請先執行 Phase 1+2[/red]")
        return pd.DataFrame(), pd.DataFrame()

    papers = load_json(meta_path)
    summaries = load_all_summaries(project_dir)

    console.print(f"論文數：{len(papers)}，已有 AI 摘要：{len(summaries)}")

    rows = []
    for meta in papers:
        arxiv_id = meta["arxiv_id"]
        summary = summaries.get(arxiv_id)
        row = _merge_paper(meta, summary, project_dir)
        rows.append(row)

    df_all = pd.DataFrame(rows)

    # study.csv（12+1 欄：含 score_source 追蹤欄）
    df_study = df_all[[c for c in STUDY_COLS if c in df_all.columns]].copy()
    study_path = project_dir / "study.csv"
    df_study.to_csv(study_path, index=False, encoding="utf-8-sig")

    # articles.csv（17+1 欄）
    df_articles = df_all[[c for c in ARTICLES_COLS if c in df_all.columns]].copy()
    articles_path = project_dir / "articles.csv"
    df_articles.to_csv(articles_path, index=False, encoding="utf-8-sig")

    # Excel 版（方便直接開啟）
    excel_path = project_dir / "articles.xlsx"
    with pd.ExcelWriter(excel_path, engine="openpyxl") as writer:
        df_study.to_excel(writer, sheet_name="study", index=False)
        df_articles.to_excel(writer, sheet_name="articles", index=False)

    console.print(f"[bold green]已輸出：[/bold green]")
    console.print(f"  study.csv    → {len(df_study)} 筆 × {len(df_study.columns)} 欄")
    console.print(f"  articles.csv → {len(df_articles)} 筆 × {len(df_articles.columns)} 欄")
    console.print(f"  articles.xlsx（雙 sheet）")

    return df_study, df_articles
