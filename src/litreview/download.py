"""Phase 2：PDF / HTML 下載與文字提取"""

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz  # PyMuPDF
import httpx
from bs4 import BeautifulSoup
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

from litreview.config import (
    ARXIV_DOWNLOAD_DELAY,
    ARXIV_HTML_TIMEOUT,
    ARXIV_HTML_URL,
    ARXIV_MAX_WORKERS,
    ARXIV_PDF_TIMEOUT,
    ARXIV_PDF_URL,
    ARXIV_RETRY_BASE,
    ARXIV_RETRY_MAX,
    HTML_MAX_CHARS,
    TEXT_CACHE_MIN_SIZE,
    TEXT_MAX_CHARS,
    TEXT_MIN_VALID_CHARS,
)
from litreview.utils import exponential_backoff, safe_resolve, save_json

console = Console()


def _download_pdf(client: httpx.Client, arxiv_id: str, dest: Path) -> bool:
    """下載 PDF，失敗時回傳 False"""
    url = ARXIV_PDF_URL.format(arxiv_id=arxiv_id)
    for attempt in range(4):
        if attempt > 0:
            wait = exponential_backoff(attempt - 1, ARXIV_RETRY_BASE, ARXIV_RETRY_MAX)
            time.sleep(wait)
        try:
            r = client.get(url, timeout=ARXIV_PDF_TIMEOUT, follow_redirects=True)
            if r.status_code == 429:
                wait = exponential_backoff(attempt, ARXIV_RETRY_BASE, ARXIV_RETRY_MAX)
                time.sleep(wait)
                continue
            if r.status_code != 200:
                return False
            if len(r.content) < 128:
                return False
            dest.write_bytes(r.content)
            return True
        except Exception:
            pass
    return False


def _extract_pdf_text(pdf_path: Path) -> str:
    """用 PyMuPDF 提取 PDF 文字"""
    try:
        doc = fitz.open(pdf_path)
        pages = [page.get_text() for page in doc]
        doc.close()
        text = "\n".join(pages)
        if len(text) > TEXT_MAX_CHARS:
            text = text[:TEXT_MAX_CHARS] + "\n[truncated]"
        return text
    except Exception:
        return ""


def _download_html_text(client: httpx.Client, arxiv_id: str) -> str:
    """下載 arXiv HTML 並提取文字（備選方案，修正：上限與 PDF 相同）"""
    url = ARXIV_HTML_URL.format(arxiv_id=arxiv_id)
    for attempt in range(3):
        if attempt > 0:
            time.sleep(exponential_backoff(attempt - 1, 3.0, 60.0))
        try:
            r = client.get(url, timeout=ARXIV_HTML_TIMEOUT, follow_redirects=True)
            if r.status_code != 200:
                return ""
            soup = BeautifulSoup(r.text, "lxml")
            # 移除 script / style
            for tag in soup(["script", "style", "nav", "footer"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            if len(text) > HTML_MAX_CHARS:
                text = text[:HTML_MAX_CHARS] + "\n[truncated]"
            return text
        except Exception:
            pass
    return ""


def _process_one(paper: dict, project_dir: Path) -> dict:
    """
    處理單篇論文：下載 PDF → 提取文字 → 若不足再試 HTML。
    PubMed 論文（pmid_ 前綴）已在 Phase 1 取得摘要，直接略過。
    加入隨機延遲避免觸發 arXiv 封鎖。
    """
    arxiv_id = paper["arxiv_id"]
    txt_path = safe_resolve(project_dir, paper["text_path"])
    pdf_path = safe_resolve(project_dir, f"articles/{arxiv_id}.pdf")

    # PubMed 論文不走 arXiv 下載流程
    if arxiv_id.startswith("pmid_"):
        if txt_path.exists() and txt_path.stat().st_size > 0:
            paper["content_source"] = paper.get("content_source", "abstract")
            paper["text_length"] = txt_path.stat().st_size
        else:
            paper["content_source"] = "failed"
            paper["text_length"] = 0
        return paper

    # 快取命中：略過已完成的論文
    if txt_path.exists() and txt_path.stat().st_size > TEXT_CACHE_MIN_SIZE:
        paper["content_source"] = "cached"
        paper["text_length"] = txt_path.stat().st_size
        return paper

    # 隨機延遲（修正：避免同時發送大量請求）
    time.sleep(random.uniform(*ARXIV_DOWNLOAD_DELAY))

    with httpx.Client(
        headers={"User-Agent": "LiteratureReview/1.0 (academic research)"},
        http2=True,
    ) as client:
        # 嘗試 PDF
        pdf_ok = _download_pdf(client, arxiv_id, pdf_path)
        text = ""
        source = "failed"

        if pdf_ok:
            text = _extract_pdf_text(pdf_path)
            if len(text) >= TEXT_MIN_VALID_CHARS:
                source = "pdf"

        # PDF 不足時嘗試 HTML
        if len(text) < TEXT_MIN_VALID_CHARS:
            html_text = _download_html_text(client, arxiv_id)
            if len(html_text) > len(text):
                text = html_text
                source = "html" if html_text else "failed"

        if text:
            txt_path.parent.mkdir(parents=True, exist_ok=True)
            txt_path.write_text(text, encoding="utf-8")
            paper["content_source"] = source
            paper["text_length"] = len(text)
        else:
            paper["content_source"] = "failed"
            paper["text_length"] = 0

    return paper


def run_download(papers: list[dict], project_dir: Path) -> list[dict]:
    """
    並行下載所有論文（max_workers=2，含隨機延遲）。
    完成後更新並回存 articles_metadata.json。
    """
    updated = []
    failed = []

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]下載論文...", total=len(papers))

        with ThreadPoolExecutor(max_workers=ARXIV_MAX_WORKERS) as pool:
            futures = {pool.submit(_process_one, p, project_dir): p for p in papers}
            for future in as_completed(futures):
                result = future.result()
                updated.append(result)
                if result["content_source"] == "failed":
                    failed.append(result["arxiv_id"])
                progress.advance(task)

    # 回存更新後的元數據
    save_json(updated, project_dir / "articles_metadata.json")

    ok = len(updated) - len(failed)
    console.print(f"\n[bold green]下載完成：{ok}/{len(papers)} 成功，{len(failed)} 失敗[/bold green]")
    if failed:
        console.print(f"[yellow]失敗論文：{', '.join(failed[:10])}{'...' if len(failed) > 10 else ''}[/yellow]")

    return updated
