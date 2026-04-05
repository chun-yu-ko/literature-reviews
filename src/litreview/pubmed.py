"""PubMed / NCBI E-utilities 文獻搜尋模組"""

import random
import time
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn

from litreview.config import (
    PUBMED_DELAY,
    PUBMED_FETCH_URL,
    PUBMED_MAX_RESULTS,
    PUBMED_SEARCH_URL,
    PUBMED_SUMMARY_URL,
)
from litreview.utils import get_logger, save_json

console = Console()


def _esearch(
    client: httpx.Client,
    query: str,
    max_results: int,
    api_key: str | None,
) -> list[str]:
    """NCBI esearch：回傳 PMID 列表"""
    params: dict = {
        "db": "pubmed",
        "term": query,
        "retmax": min(max_results, 9999),
        "retmode": "json",
        "sort": "relevance",
    }
    if api_key:
        params["api_key"] = api_key

    for attempt in range(3):
        try:
            r = client.get(PUBMED_SEARCH_URL, params=params, timeout=30)
            if r.status_code == 200:
                data = r.json()
                return data.get("esearchresult", {}).get("idlist", [])
            if r.status_code == 429:
                time.sleep(5 * (attempt + 1))
                continue
        except Exception as e:
            get_logger().warning(f"PubMed esearch 失敗（{attempt+1}/3）：{e}")
        time.sleep(random.uniform(*PUBMED_DELAY))
    return []


def _esummary_batch(
    client: httpx.Client,
    pmids: list[str],
    api_key: str | None,
) -> dict:
    """NCBI esummary：批次取得論文摘要元數據"""
    params: dict = {
        "db": "pubmed",
        "id": ",".join(pmids),
        "retmode": "json",
    }
    if api_key:
        params["api_key"] = api_key

    for attempt in range(3):
        try:
            r = client.get(PUBMED_SUMMARY_URL, params=params, timeout=30)
            if r.status_code == 200:
                return r.json().get("result", {})
        except Exception as e:
            get_logger().warning(f"PubMed esummary 失敗：{e}")
        time.sleep(random.uniform(*PUBMED_DELAY))
    return {}


def _efetch_abstract(
    client: httpx.Client,
    pmid: str,
    api_key: str | None,
) -> str:
    """NCBI efetch：取得單篇論文摘要全文（純文字）"""
    params: dict = {
        "db": "pubmed",
        "id": pmid,
        "rettype": "abstract",
        "retmode": "text",
    }
    if api_key:
        params["api_key"] = api_key

    try:
        r = client.get(PUBMED_FETCH_URL, params=params, timeout=30)
        if r.status_code == 200:
            return r.text.strip()
    except Exception:
        pass
    return ""


def _parse_doc(pmid: str, doc: dict, query: str) -> dict | None:
    """將 esummary 結果轉為標準論文 dict"""
    try:
        title = doc.get("title", "").rstrip(".")
        pub_date = doc.get("pubdate", "")
        year = int(pub_date[:4]) if len(pub_date) >= 4 and pub_date[:4].isdigit() else 0

        authors_list = doc.get("authors", [])
        authors = "; ".join(a.get("name", "") for a in authors_list[:6])

        doi = ""
        pmc_id = ""
        for id_obj in doc.get("articleids", []):
            id_type = id_obj.get("idtype", "")
            if id_type == "doi":
                doi = id_obj.get("value", "")
            elif id_type == "pmc":
                pmc_id = id_obj.get("value", "")

        journal = doc.get("fulljournalname", doc.get("source", ""))
        uid = f"pmid_{pmid}"

        return {
            "arxiv_id": uid,
            "title": title,
            "authors": authors,
            "published": str(year),
            "year": year,
            "doi": doi,
            "pdf_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "html_url": f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/",
            "cited_by": 0,
            "topic": query,
            "field": journal,
            "openalex_id": "",
            "search_category": "pubmed",
            "search_query": query,
            "all_categories": ["pubmed"],
            "text_path": f"texts/{uid}.txt",
            "content_source": "",
            "text_length": 0,
            "abstract": "",
            "pmc_id": pmc_id,
            "source": "pubmed",
        }
    except Exception as e:
        get_logger().warning(f"PubMed 解析 PMID {pmid} 失敗：{e}")
        return None


def search_pubmed(
    query: str,
    project_dir: Path,
    max_results: int = PUBMED_MAX_RESULTS,
    ncbi_api_key: str | None = None,
) -> list[dict]:
    """
    搜尋 PubMed，取得元數據並預先儲存摘要文字（作為 Phase 2 替代）。
    回傳標準論文 dict 列表。
    """
    console.print(f"[cyan]PubMed 搜尋：{query}（最多 {max_results} 篇）[/cyan]")
    get_logger().info(f"PubMed 搜尋開始：{query}")

    with httpx.Client(
        headers={"User-Agent": "LiteratureReview/1.0 (academic research)"},
        timeout=30,
    ) as client:
        # Step 1: 取得 PMID 列表
        pmids = _esearch(client, query, max_results, ncbi_api_key)
        if not pmids:
            console.print("[yellow]PubMed 無搜尋結果[/yellow]")
            return []

        console.print(f"[green]PubMed 命中 {len(pmids)} 篇，取得元數據中...[/green]")

        # Step 2: 批次取得元數據
        all_docs: dict = {}
        batch_size = 200
        for i in range(0, len(pmids), batch_size):
            batch = pmids[i : i + batch_size]
            time.sleep(random.uniform(*PUBMED_DELAY))
            docs = _esummary_batch(client, batch, ncbi_api_key)
            all_docs.update(docs)

        papers = []
        for pmid in pmids:
            if pmid == "uids":
                continue
            doc = all_docs.get(pmid)
            if not doc:
                continue
            paper = _parse_doc(pmid, doc, query)
            if paper:
                papers.append(paper)

        # Step 3: 預先擷取摘要文字並儲存（讓 Phase 2 直接略過）
        texts_dir = project_dir / "texts"
        texts_dir.mkdir(parents=True, exist_ok=True)

        with Progress(
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("[cyan]取得 PubMed 摘要...", total=len(papers))
            for paper in papers:
                pmid = paper["arxiv_id"].replace("pmid_", "")
                txt_path = project_dir / paper["text_path"]

                if not txt_path.exists():
                    time.sleep(random.uniform(*PUBMED_DELAY))
                    abstract = _efetch_abstract(client, pmid, ncbi_api_key)
                    if abstract:
                        txt_path.write_text(abstract, encoding="utf-8")
                        paper["content_source"] = "abstract"
                        paper["text_length"] = len(abstract)
                    else:
                        paper["content_source"] = "failed"
                else:
                    paper["content_source"] = "cached"
                    paper["text_length"] = txt_path.stat().st_size

                progress.advance(task)

    console.print(f"[bold green]PubMed 搜尋完成：{len(papers)} 篇[/bold green]")
    get_logger().info(f"PubMed 搜尋完成：{len(papers)} 篇")
    return papers
