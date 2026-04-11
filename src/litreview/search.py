"""Phase 1：多來源文獻搜尋（OpenAlex arXiv + PubMed）"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
from rich.console import Console
from rich.progress import BarColumn, Progress, TaskProgressColumn, TextColumn, track

from litreview import config
from litreview.utils import extract_arxiv_id, get_logger, save_json

console = Console()


# ──────────────────────────────────────────────────────────────
#  OpenAlex helpers
# ──────────────────────────────────────────────────────────────

def _fetch_page(
    client: httpx.Client,
    query: str,
    category: str,
    max_results: int,
    cursor: str = "*",
) -> tuple[list[dict], str | None]:
    """取得單頁 OpenAlex 搜尋結果。回傳 (papers, next_cursor)。"""
    per_page = min(max_results, config.OPENALEX_MAX_PER_PAGE)
    params = {
        "search": query,
        "filter": "from_publication_date:2016-01-01,open_access.is_oa:true",
        "per_page": per_page,
        "cursor": cursor,
        "select": ",".join([
            "id", "title", "authorships", "publication_year",
            "doi", "locations", "primary_topic", "cited_by_count",
        ]),
        "sort": "relevance_score:desc",
        "mailto": config.OPENALEX_MAILTO,
    }

    for attempt, delay in enumerate([0, *config.OPENALEX_RETRY_DELAYS]):
        if delay:
            time.sleep(delay)
        try:
            r = client.get(config.OPENALEX_BASE_URL, params=params, timeout=30)
            if r.status_code == 429:
                idx = min(attempt, len(config.OPENALEX_RETRY_DELAYS) - 1)
                wait = config.OPENALEX_RETRY_DELAYS[idx]
                console.print(f"[yellow]429 Too Many Requests，等待 {wait}s[/yellow]")
                time.sleep(wait)
                continue
            r.raise_for_status()
            data = r.json()
            results = data.get("results", [])
            next_cursor = data.get("meta", {}).get("next_cursor")
            return results, next_cursor
        except httpx.HTTPError as e:
            if attempt == len(config.OPENALEX_RETRY_DELAYS):
                raise
            console.print(f"[red]HTTP error: {e}，重試中...[/red]")

    return [], None


def _parse_openalex_paper(raw: dict, category: str, query: str) -> dict | None:
    """解析單筆 OpenAlex 結果為標準格式"""
    arxiv_id = None
    for loc in raw.get("locations", []):
        url = loc.get("landing_page_url") or ""
        arxiv_id = extract_arxiv_id(url)
        if arxiv_id:
            break
    if not arxiv_id:
        return None

    authors = "; ".join(filter(None, [
        a.get("author", {}).get("display_name", "")
        for a in raw.get("authorships", [])[:6]
    ]))
    year = raw.get("publication_year") or 0
    primary_topic = (raw.get("primary_topic") or {}).get("display_name", "")
    field = ((raw.get("primary_topic") or {}).get("field") or {}).get("display_name", "")

    return {
        "arxiv_id": arxiv_id,
        "title": raw.get("title", ""),
        "authors": authors,
        "published": str(year),
        "year": year,
        "doi": raw.get("doi") or "",
        "pdf_url": f"https://arxiv.org/pdf/{arxiv_id}.pdf",
        "html_url": f"https://arxiv5.labs.arxiv.org/html/{arxiv_id}",
        "cited_by": raw.get("cited_by_count", 0),
        "topic": primary_topic,
        "field": field,
        "openalex_id": raw.get("id", ""),
        "search_category": category,
        "search_query": query,
        "all_categories": [category],
        "text_path": f"texts/{arxiv_id}.txt",
        "content_source": "",
        "text_length": 0,
        "abstract": "",
        "source": "arxiv",
    }


def _search_one_category(
    category: str,
    queries: list[tuple[str, int]],
    client: httpx.Client,
) -> list[dict]:
    """執行單一類別的所有查詢，回傳去重後的論文列表"""
    seen: dict[str, dict] = {}

    for query, max_results in track(queries, description=f"[cyan]搜尋 {category}[/cyan]"):
        collected = 0
        cursor = "*"

        while collected < max_results:
            remain = max_results - collected
            raw_results, next_cursor = _fetch_page(client, query, category, remain, cursor)

            for raw in raw_results:
                paper = _parse_openalex_paper(raw, category, query)
                if paper is None:
                    continue
                aid = paper["arxiv_id"]
                if aid not in seen:
                    seen[aid] = paper
                else:
                    if category not in seen[aid]["all_categories"]:
                        seen[aid]["all_categories"].append(category)
                collected += 1

            time.sleep(config.OPENALEX_REQUEST_DELAY)
            if not next_cursor or len(raw_results) == 0:
                break
            cursor = next_cursor

    return list(seen.values())


def _search_free_topic(
    topic: str,
    max_results: int,
    client: httpx.Client,
) -> list[dict]:
    """以自由主題直接搜尋 OpenAlex（不使用預設類別查詢）"""
    seen: dict[str, dict] = {}
    collected = 0
    cursor = "*"
    category = topic

    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(f"[cyan]OpenAlex 搜尋：{topic}", total=max_results)

        while collected < max_results:
            remain = max_results - collected
            raw_results, next_cursor = _fetch_page(client, topic, category, remain, cursor)

            for raw in raw_results:
                paper = _parse_openalex_paper(raw, category, topic)
                if paper is None:
                    continue
                if paper["arxiv_id"] not in seen:
                    seen[paper["arxiv_id"]] = paper
                    collected += 1
                    progress.advance(task)

            time.sleep(config.OPENALEX_REQUEST_DELAY)
            if not next_cursor or len(raw_results) == 0:
                break
            cursor = next_cursor

    return list(seen.values())


# ──────────────────────────────────────────────────────────────
#  Main entry point
# ──────────────────────────────────────────────────────────────

def run_search(
    project_dir: Path,
    topic: str = "",
    categories: list[str] | None = None,
    sources: list[str] | None = None,
    max_results_per_query: int = 200,
    ncbi_api_key: str | None = None,
) -> list[dict]:
    """
    執行多來源文獻搜尋。

    模式：
    - categories 指定 → 使用 SEARCH_QUERIES 預設查詢集（向下相容）
    - categories 未指定 → 以 topic 直接搜尋

    sources: ["arxiv"] | ["pubmed"] | ["arxiv", "pubmed"]（預設 ["arxiv"]）
    """
    logger = get_logger()
    sources = sources or ["arxiv"]
    all_papers: list[dict] = []
    global_seen: dict[str, dict] = {}

    def _merge(papers: list[dict]) -> None:
        for p in papers:
            aid = p["arxiv_id"]
            if aid not in global_seen:
                global_seen[aid] = p
                all_papers.append(p)
            else:
                for cat in p.get("all_categories", []):
                    if cat not in global_seen[aid]["all_categories"]:
                        global_seen[aid]["all_categories"].append(cat)

    # ── OpenAlex / arXiv ──
    if "arxiv" in sources or "all" in sources:
        with httpx.Client(
            headers={
                "User-Agent": f"LiteratureReview/1.0 (mailto:{config.OPENALEX_MAILTO})",
            }
        ) as client:
            if categories:
                # 並行多類別搜尋
                cats_to_search = [c for c in categories if c in config.SEARCH_QUERIES]
                unknown = [c for c in categories if c not in config.SEARCH_QUERIES]
                if unknown:
                    console.print(f"[yellow]未知類別（跳過）：{unknown}[/yellow]")

                with ThreadPoolExecutor(max_workers=config.SEARCH_MAX_WORKERS) as pool:
                    futures = {
                        pool.submit(
                            _search_one_category,
                            cat,
                            config.SEARCH_QUERIES[cat],
                            client,
                        ): cat
                        for cat in cats_to_search
                    }
                    for future in as_completed(futures):
                        cat = futures[future]
                        papers = future.result()
                        _merge(papers)
                        console.print(
                            f"[green]類別 {cat}：{len(papers)} 篇"
                            f"（累計 {len(all_papers)}）[/green]"
                        )
                        logger.info(f"OpenAlex 類別 {cat} 完成：{len(papers)} 篇")
            else:
                # 自由主題搜尋
                papers = _search_free_topic(topic, max_results_per_query, client)
                _merge(papers)
                logger.info(f"OpenAlex 自由搜尋 '{topic}'：{len(papers)} 篇")

    # ── PubMed ──
    if "pubmed" in sources or "all" in sources:
        from litreview.pubmed import search_pubmed

        search_term = topic or (categories[0] if categories else "")
        if search_term:
            pubmed_papers = search_pubmed(
                search_term,
                project_dir,
                max_results=max_results_per_query,
                ncbi_api_key=ncbi_api_key,
            )
            _merge(pubmed_papers)
            logger.info(f"PubMed 搜尋完成：{len(pubmed_papers)} 篇")
        else:
            console.print("[yellow]未指定主題，跳過 PubMed 搜尋[/yellow]")

    # ── 儲存結果 ──
    meta_path = project_dir / "articles_metadata.json"
    save_json(all_papers, meta_path)
    console.print(f"\n[bold]已儲存 {len(all_papers)} 篇元數據 → {meta_path}[/bold]")
    logger.info(f"搜尋完成，共 {len(all_papers)} 篇，已儲存至 {meta_path}")

    _save_batches(all_papers, project_dir)

    return all_papers


def _save_batches(papers: list[dict], project_dir: Path) -> None:
    """依來源類別分批儲存 batch_{n}.json"""
    # 依 search_category 分組，保持穩定順序
    by_cat: dict[str, list] = {}
    for p in papers:
        cat = p["search_category"]
        by_cat.setdefault(cat, []).append(p)

    # 先排預設類別，再排其餘
    preferred = ["LLM", "Causal_Robins", "Causal_Graph"]
    ordered: list[dict] = []
    for cat in preferred:
        ordered.extend(by_cat.pop(cat, []))
    for ps in by_cat.values():
        ordered.extend(ps)

    batch_n = 0
    for i in range(0, len(ordered), config.BATCH_SIZE):
        batch = ordered[i : i + config.BATCH_SIZE]
        save_json(batch, project_dir / f"batch_{batch_n}.json")
        batch_n += 1

    console.print(f"[dim]已分成 {batch_n} 批（每批 ≤{config.BATCH_SIZE} 筆）[/dim]")
