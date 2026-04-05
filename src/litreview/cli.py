"""CLI 入口：litreview 指令"""

import os
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel

from litreview.utils import make_project_dir, setup_logging

console = Console()
ROOT_DIR = Path(__file__).parent.parent.parent


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
def run(
    topic: str,
    categories: str,
    source: str,
    max_results: int,
    skip_download: bool,
    skip_summarize: bool,
    suggest: bool,
    api_key: str,
    ncbi_api_key: str,
):
    """
    執行完整文獻回顧流程，並自動建立新專案目錄。

    TOPIC：研究主題名稱（例如：\"Causal Inference\" 或 \"NLP job market\"）

    範例：
      litreview run "Causal Inference" --source arxiv,pubmed --suggest
      litreview run bert_finetune --categories LLM --skip-summarize
      litreview run "drug discovery" --source pubmed --ncbi-api-key $NCBI_KEY
    """
    from litreview.build_csv import run_build_csv
    from litreview.download import run_download
    from litreview.report import run_report
    from litreview.search import run_search
    from litreview.utils import load_json

    # 建立專案目錄
    project_dir = make_project_dir(topic, ROOT_DIR)

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
def summarize(project_dir: Path, api_key: str, topic: str, suggest: bool):
    """對已下載的論文補跑 Phase 3 AI 摘要"""
    from litreview.summarize import load_all_summaries, run_summarize
    from litreview.utils import load_json

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
