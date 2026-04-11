"""CLI 入口：litreview 指令"""

import os
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from litreview import config
from litreview.utils import make_project_dir, setup_logging

console = Console()
ROOT_DIR = Path(__file__).parent.parent.parent


def _apply_config_overrides(**overrides: object) -> None:
    """將 CLI 傳入的非 None 值寫入 config 模組，覆蓋預設值。"""
    mapping: dict[str, str] = {
        "batch_size": "BATCH_SIZE",
        "download_workers": "ARXIV_MAX_WORKERS",
        "summarize_workers": "SUMMARIZE_MAX_WORKERS",
        "search_workers": "SEARCH_MAX_WORKERS",
        "openalex_mailto": "OPENALEX_MAILTO",
        "pdf_timeout": "ARXIV_PDF_TIMEOUT",
        "html_timeout": "ARXIV_HTML_TIMEOUT",
        "text_max_chars": "TEXT_MAX_CHARS",
    }
    applied: list[str] = []
    for cli_name, config_attr in mapping.items():
        value = overrides.get(cli_name)
        if value is not None:
            setattr(config, config_attr, value)
            applied.append(f"{config_attr}={value}")
    if applied:
        console.print(f"[dim]Config overrides: {', '.join(applied)}[/dim]")


@click.group()
def main():
    """文獻回顧自動化工具 — 支援 arXiv / PubMed 多來源搜尋"""
    pass


@main.command()
@click.argument("topic")
@click.option(
    "--categories", "-c", default=None,
    help="使用預設查詢集（逗號分隔，如 LLM,Causal_Robins）；未指定時以 TOPIC 直接搜尋",
)
@click.option(
    "--source", "-s", default="arxiv",
    show_default=True,
    help="搜尋來源：arxiv | pubmed | all（逗號分隔可多選，如 arxiv,pubmed）",
)
@click.option("--max-results", default=200, show_default=True, help="每個查詢最多取得篇數")
@click.option("--skip-download", is_flag=True, help="跳過 Phase 2 下載（只搜尋）")
@click.option("--skip-summarize", is_flag=True, help="跳過 Phase 3 AI 摘要")
@click.option("--suggest", is_flag=True, help="執行 Phase 3.5 延伸關鍵字建議")
@click.option("--api-key", default=None, envvar="ANTHROPIC_API_KEY", help="Claude API Key")
@click.option("--ncbi-api-key", default=None, envvar="NCBI_API_KEY", help="NCBI API Key（提高 PubMed 速率限制）")
@click.option(
    "--output-dir", type=click.Path(path_type=Path),
    default=None, help="專案輸出基礎目錄（預設：程式根目錄）",
)
@click.option(
    "--batch-size", type=int, default=None,
    help=f"分批儲存筆數（預設：{config.BATCH_SIZE}）",
)
@click.option(
    "--download-workers", type=int, default=None,
    help=f"PDF 下載並行 worker 數（預設：{config.ARXIV_MAX_WORKERS}）",
)
@click.option(
    "--summarize-workers", type=int, default=None,
    help=f"AI 摘要並行 worker 數（預設：{config.SUMMARIZE_MAX_WORKERS}）",
)
@click.option(
    "--search-workers", type=int, default=None,
    help=f"搜尋並行 worker 數（預設：{config.SEARCH_MAX_WORKERS}）",
)
@click.option(
    "--openalex-mailto", default=None,
    help="OpenAlex API mailto 參數",
)
@click.option(
    "--pdf-timeout", type=int, default=None,
    help=f"PDF 下載逾時秒數（預設：{config.ARXIV_PDF_TIMEOUT}）",
)
@click.option(
    "--html-timeout", type=int, default=None,
    help=f"HTML 下載逾時秒數（預設：{config.ARXIV_HTML_TIMEOUT}）",
)
@click.option(
    "--text-max-chars", type=int, default=None,
    help=f"全文截斷上限字元數（預設：{config.TEXT_MAX_CHARS}）",
)
def run(
    topic: str,
    categories: str | None,
    source: str,
    max_results: int,
    skip_download: bool,
    skip_summarize: bool,
    suggest: bool,
    api_key: str | None,
    ncbi_api_key: str | None,
    output_dir: Path | None,
    batch_size: int | None,
    download_workers: int | None,
    summarize_workers: int | None,
    search_workers: int | None,
    openalex_mailto: str | None,
    pdf_timeout: int | None,
    html_timeout: int | None,
    text_max_chars: int | None,
):
    """
    執行完整文獻回顧流程，並自動建立新專案目錄。

    TOPIC：研究主題名稱（例如：\"Causal Inference\" 或 \"NLP job market\"）

    範例：
      litreview run "Causal Inference" --source arxiv,pubmed --suggest
      litreview run bert_finetune --categories LLM --skip-summarize
      litreview run "drug discovery" --source pubmed --ncbi-api-key $NCBI_KEY
      litreview run "AI safety" --download-workers 4 --batch-size 100
    """
    from litreview.build_csv import run_build_csv
    from litreview.download import run_download
    from litreview.report import run_report
    from litreview.search import run_search
    from litreview.utils import load_json

    # Security: warn if API keys passed via CLI
    if api_key:
        import sys
        if "--api-key" in sys.argv:
            console.print(
                "[bold yellow]Warning:[/bold yellow] passing API keys via "
                "CLI arguments exposes them in process listings (ps aux). "
                "Prefer: export ANTHROPIC_API_KEY=...",
            )
    if ncbi_api_key:
        import sys
        if "--ncbi-api-key" in sys.argv:
            console.print(
                "[bold yellow]Warning:[/bold yellow] passing API keys via "
                "CLI arguments exposes them in process listings (ps aux). "
                "Prefer: export NCBI_API_KEY=...",
            )

    # 套用 config 覆寫
    _apply_config_overrides(
        batch_size=batch_size,
        download_workers=download_workers,
        summarize_workers=summarize_workers,
        search_workers=search_workers,
        openalex_mailto=openalex_mailto,
        pdf_timeout=pdf_timeout,
        html_timeout=html_timeout,
        text_max_chars=text_max_chars,
    )

    # 建立專案目錄
    base_dir = output_dir if output_dir is not None else ROOT_DIR
    project_dir = make_project_dir(topic, base_dir)

    # 設定 logging（寫入 run.log）
    logger = setup_logging(project_dir)
    logger.info(f"litreview run 開始：topic={topic}, source={source}, categories={categories}")

    console.print(Panel(
        f"[bold cyan]專案目錄：{project_dir}[/bold cyan]\n"
        f"主題：{topic}  |  來源：{source}",
        title="LiteratureReview",
    ))

    # 解析參數
    cat_list = [c.strip() for c in categories.split(",")] if categories else None
    source_list = [s.strip() for s in source.split(",")]

    # Phase 1：搜尋
    console.rule("[bold green]Phase 1：文獻搜尋")
    papers = run_search(
        project_dir,
        topic=topic,
        categories=cat_list,
        sources=source_list,
        max_results_per_query=max_results,
        ncbi_api_key=ncbi_api_key,
    )

    if not papers:
        console.print("[red]搜尋結果為空，結束[/red]")
        logger.warning("搜尋結果為空，流程終止")
        return

    # Phase 2：下載
    if not skip_download:
        console.rule("[bold green]Phase 2：PDF 下載與文字提取")
        papers = run_download(papers, project_dir)
    else:
        console.print("[yellow]跳過 Phase 2[/yellow]")
        logger.info("跳過 Phase 2（--skip-download）")

    # Phase 3：AI 摘要
    summaries: dict = {}
    if not skip_summarize:
        console.rule("[bold green]Phase 3：AI 結構化摘要")
        summaries_list = _run_summarize(papers, project_dir, api_key, topic)
        summaries = {s["arxiv_id"]: s for s in summaries_list}
    else:
        console.print("[yellow]跳過 Phase 3[/yellow]")
        logger.info("跳過 Phase 3（--skip-summarize）")

    # Phase 3.5：延伸關鍵字建議
    if suggest:
        console.rule("[bold green]Phase 3.5：延伸搜尋關鍵字建議")
        _run_suggest(papers, summaries, topic, project_dir, api_key)

    # Phase 4：建構 CSV
    console.rule("[bold green]Phase 4：建構結構化資料表")
    run_build_csv(project_dir)

    # Phase 5：生成報告
    console.rule("[bold green]Phase 5：生成綜合報告")
    run_report(project_dir, topic)

    console.print(Panel(
        f"[bold green]全流程完成！[/bold green]\n"
        f"輸出目錄：{project_dir}\n"
        f"日誌：{project_dir / 'run.log'}",
        title="完成",
    ))
    logger.info("litreview run 全流程完成")


def _run_summarize(papers, project_dir, api_key, topic):
    from litreview.summarize import run_summarize
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        console.print("[yellow]未設定 ANTHROPIC_API_KEY，跳過 Phase 3[/yellow]")
        return []
    return run_summarize(papers, project_dir, key, topic=topic)


def _run_suggest(papers, summaries, topic, project_dir, api_key):
    from litreview.suggest import run_suggest
    key = api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        console.print("[yellow]未設定 ANTHROPIC_API_KEY，跳過關鍵字建議[/yellow]")
        return
    run_suggest(papers, summaries, topic, project_dir, api_key=key)


@main.command()
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--api-key", default=None, envvar="ANTHROPIC_API_KEY")
@click.option("--topic", default="", help="研究主題（用於摘要上下文）")
@click.option("--suggest", is_flag=True, help="摘要完成後執行關鍵字建議")
@click.option(
    "--summarize-workers", type=int, default=None,
    help=f"AI 摘要並行 worker 數（預設：{config.SUMMARIZE_MAX_WORKERS}）",
)
@click.option(
    "--text-max-chars", type=int, default=None,
    help=f"全文截斷上限字元數（預設：{config.TEXT_MAX_CHARS}）",
)
def summarize(
    project_dir: Path,
    api_key: str | None,
    topic: str,
    suggest: bool,
    summarize_workers: int | None,
    text_max_chars: int | None,
):
    """對已下載的論文補跑 Phase 3 AI 摘要"""
    from litreview.summarize import load_all_summaries, run_summarize
    from litreview.utils import load_json

    _apply_config_overrides(
        summarize_workers=summarize_workers,
        text_max_chars=text_max_chars,
    )
    setup_logging(project_dir)
    meta_path = project_dir / "articles_metadata.json"
    if not meta_path.exists():
        console.print("[red]找不到 articles_metadata.json[/red]")
        return
    papers = load_json(meta_path)
    summaries_list = run_summarize(papers, project_dir, api_key, topic=topic)

    if suggest:
        summaries = {s["arxiv_id"]: s for s in summaries_list}
        _run_suggest(papers, summaries, topic or project_dir.name, project_dir, api_key)


@main.command()
@click.argument("project_dir", type=click.Path(exists=True, path_type=Path))
@click.option("--topic", default="", help="研究主題（用於報告標題）")
def build(project_dir: Path, topic: str):
    """對指定專案目錄執行 Phase 4+5（建 CSV + 報告）"""
    from litreview.build_csv import run_build_csv
    from litreview.report import run_report

    setup_logging(project_dir)
    run_build_csv(project_dir)
    run_report(project_dir, topic or project_dir.name)


@main.command()
def list_projects():
    """列出所有已建立的專案目錄"""
    projects_dir = ROOT_DIR / "projects"
    if not projects_dir.exists():
        console.print("[yellow]尚無任何專案[/yellow]")
        return

    dirs = sorted(projects_dir.iterdir(), reverse=True)
    console.print(f"[bold]找到 {len(dirs)} 個專案：[/bold]")
    for d in dirs:
        if d.is_dir():
            meta = d / "articles_metadata.json"
            count = ""
            if meta.exists():
                import json
                try:
                    data = json.loads(meta.read_text("utf-8"))
                    count = f" [{len(data)} 篇]"
                except Exception:
                    pass
            log_exists = " [有日誌]" if (d / "run.log").exists() else ""
            console.print(f"  {d.name}{count}{log_exists}")


if __name__ == "__main__":
    main()
