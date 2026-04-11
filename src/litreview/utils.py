"""共用工具函式"""

import json
import logging
import re
import time
from pathlib import Path


def safe_resolve(base_dir: Path, untrusted_path: str) -> Path:
    """Resolve *untrusted_path* relative to *base_dir* and ensure it stays inside.

    Raises ``ValueError`` if the resolved path escapes *base_dir*.
    """
    resolved = (base_dir / untrusted_path).resolve()
    base_resolved = base_dir.resolve()
    base_str = str(base_resolved) + "/"
    if not (resolved == base_resolved or str(resolved).startswith(base_str)):
        raise ValueError(
            f"Path traversal detected: '{untrusted_path}' resolves outside "
            f"project directory '{base_resolved}'"
        )
    return resolved


def slugify(text: str) -> str:
    """將字串轉為適合目錄名稱的 slug"""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "_", text)
    return text[:60]


def make_project_dir(topic: str, base_dir: Path) -> Path:
    """為每個搜尋主題建立獨立專案目錄（需求 6）"""
    from datetime import date
    today = date.today().strftime("%Y%m%d")
    folder_name = f"{today}_{slugify(topic)}"
    project_dir = base_dir / "projects" / folder_name
    for sub in ["articles", "texts", "summaries"]:
        (project_dir / sub).mkdir(parents=True, exist_ok=True)
    return project_dir


def load_json(path: Path) -> list | dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def save_json(data: list | dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def extract_arxiv_id(url: str) -> str | None:
    """從 URL 提取 arXiv ID，支援多種格式"""
    patterns = [
        r"arxiv\.org/(?:abs|pdf)/(\d{4}\.\d{4,5})(?:v\d+)?",   # 新格式
        r"arxiv\.org/(?:abs|pdf)/([a-z\-]+/\d{7})(?:v\d+)?",   # 舊格式 cs/0612056
    ]
    for pat in patterns:
        m = re.search(pat, url, re.IGNORECASE)
        if m:
            return m.group(1)
    return None


def auto_relevance_score(text: str) -> tuple[int, str]:
    """
    關鍵字自動相關度評分（備援，當 AI 摘要缺失時使用）
    回傳 (score, source) 其中 source = "keyword"
    """
    from litreview.config import CAUSAL_KEYWORDS, LABOR_KEYWORDS, NLP_KEYWORDS

    tl = text.lower()
    labor_hits = sum(1 for kw in LABOR_KEYWORDS if kw in tl)
    nlp_hits = sum(1 for kw in NLP_KEYWORDS if kw in tl)
    causal_hits = sum(1 for kw in CAUSAL_KEYWORDS if kw in tl)

    score = 1
    if labor_hits >= 2:
        score += 2
    elif nlp_hits >= 5:
        score += 1
    if nlp_hits >= 2:
        score += 1
    if causal_hits >= 2:
        score += 1
    return min(score, 5), "keyword"


def classify_research_method(text: str) -> str:
    """研究方法自動分類（修正版：使用 any() 避免 Python truthy bug）"""
    tl = text.lower()
    if any(kw in tl for kw in ["survey", "review", "taxonomy", "literature review"]):
        return "文獻回顧"
    if any(kw in tl for kw in ["theorem", "proof", "lemma", "proposition"]):
        return "理論"
    if any(kw in tl for kw in ["experiment", "empirical", "benchmark", "evaluation", "dataset"]):
        return "實驗研究"
    return "方法論"


def exponential_backoff(attempt: int, base: float = 5.0, cap: float = 300.0) -> float:
    """指數退避等待時間"""
    wait = min(base * (2 ** attempt), cap)
    return wait


def retry_with_backoff(fn, max_attempts: int = 4, base: float = 5.0):
    """對函式進行指數退避重試"""
    last_exc = None
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < max_attempts - 1:
                wait = exponential_backoff(attempt, base)
                time.sleep(wait)
    raise last_exc


def setup_logging(project_dir: Path) -> logging.Logger:
    """設定日誌輸出至專案目錄 run.log，同時保留 console 輸出"""
    from litreview.config import LOG_FILENAME

    log_path = project_dir / LOG_FILENAME
    logger = logging.getLogger("litreview")
    logger.setLevel(logging.DEBUG)

    # 避免重複加 handler（多次呼叫時）
    if not logger.handlers:
        fh = logging.FileHandler(log_path, encoding="utf-8")
        fh.setLevel(logging.DEBUG)
        fmt = logging.Formatter(
            "%(asctime)s [%(levelname)-8s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def get_logger() -> logging.Logger:
    """取得全域 litreview logger"""
    return logging.getLogger("litreview")
