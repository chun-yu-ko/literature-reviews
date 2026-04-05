"""全域設定與常數"""

from pathlib import Path

# 專案根目錄
ROOT_DIR = Path(__file__).parent.parent.parent

# 搜尋查詢清單
SEARCH_QUERIES: dict[str, list[tuple[str, int]]] = {
    "LLM": [
        ("attention mechanism transformer self-attention", 8),
        ("transformer architecture deep learning", 8),
        ("scaling laws language models neural", 8),
        ("compute optimal large language model training", 8),
        ("in-context learning large language model", 8),
        ("few-shot learning language model prompting", 8),
        ("LoRA low-rank adaptation fine-tuning", 8),
        ("parameter efficient fine-tuning language models", 8),
        ("QLoRA quantized fine-tuning", 4),
        ("large language model text classification", 8),
        ("named entity recognition transformer BERT", 8),
        ("information extraction large language model", 8),
        ("skill extraction NLP job posting", 6),
        ("chain of thought reasoning language model", 6),
        ("prompt engineering prompt tuning", 6),
        ("retrieval augmented generation language model", 8),
        ("large language model tabular data", 4),
        ("language model structured prediction", 4),
        ("large language model evaluation benchmark", 6),
        ("instruction tuning language model alignment", 8),
        ("reinforcement learning human feedback RLHF", 8),
        ("sentence embedding contrastive learning text", 6),
        ("text embedding retrieval dense", 5),
        ("BERTopic neural topic model", 6),
        ("tokenization multilingual subword language model", 4),
        ("job posting NLP text mining labor market", 8),
        ("occupation classification BERT transformer", 5),
        ("labor market natural language processing skill demand", 8),
    ],
    "Causal_Robins": [
        ("inverse probability weighting causal inference", 8),
        ("propensity score weighting matching causal", 6),
        ("doubly robust estimator causal inference", 6),
        ("augmented inverse probability weighting AIPW", 5),
        ("targeted maximum likelihood estimation TMLE causal", 6),
        ("targeted learning semiparametric", 6),
        ("marginal structural model causal time-varying", 6),
        ("g-computation g-formula causal parametric", 6),
        ("difference-in-differences causal inference", 10),
        ("staggered difference-in-differences treatment", 8),
        ("two-way fixed effects causal panel", 5),
        ("synthetic control method causal inference", 6),
        ("interrupted time series causal quasi-experimental", 5),
        ("event study design causal treatment effect", 5),
        ("causal mediation analysis direct indirect effect", 6),
        ("natural direct effect natural indirect effect mediation", 4),
        ("heterogeneous treatment effects conditional average", 6),
        ("causal forest generalized random forest treatment", 6),
        ("double machine learning debiased causal", 6),
        ("semiparametric efficiency causal inference", 4),
        ("time-varying treatment confounding longitudinal causal", 6),
        ("Heckman selection model bias causal inference", 6),
        ("selection bias causal inference correction", 4),
        ("sensitivity analysis unmeasured confounding causal", 4),
        ("E-value causal inference robustness", 3),
    ],
    "Causal_Graph": [
        ("PC algorithm causal discovery constraint-based", 8),
        ("Peter Clark algorithm conditional independence test", 4),
        ("K2 algorithm Bayesian network structure learning", 4),
        ("Bayesian network structure learning score-based", 4),
        ("FCI algorithm causal discovery latent confounders", 6),
        ("fast causal inference FCI latent variable", 4),
        ("greedy equivalence search GES causal discovery", 5),
        ("NOTEARS continuous optimization DAG structure learning", 8),
        ("differentiable structure learning directed acyclic graph", 5),
        ("LiNGAM linear non-Gaussian acyclic model causal", 6),
        ("independent component analysis causal discovery", 4),
        ("do-calculus Pearl causal inference intervention", 8),
        ("structural causal model Pearl identification", 5),
        ("causal discovery observational data algorithm", 10),
        ("causal discovery benchmark evaluation methods", 6),
        ("causal structure learning survey", 4),
        ("causal representation learning disentangled", 8),
        ("causal inference text data NLP", 8),
        ("text as treatment causal estimation", 4),
        ("causal identifiability graph identification", 5),
        ("Markov equivalence class causal DAG", 4),
        ("additive noise model causal direction", 4),
        ("Granger causality neural network deep learning", 5),
        ("causal discovery deep learning neural", 8),
        ("DAG-GNN graph neural network causal", 4),
        ("counterfactual reasoning structural causal model", 6),
        ("interventional distribution causal effect", 4),
        ("hybrid causal discovery constraint score method", 4),
    ],
}

# OpenAlex API 設定
OPENALEX_BASE_URL = "https://api.openalex.org/works"
OPENALEX_MAILTO = "research@literature-review.local"  # 建議換成真實 email
OPENALEX_REQUEST_DELAY = 1.0   # 每次請求間隔（秒）
OPENALEX_RETRY_DELAYS = [10, 20, 30]
OPENALEX_MAX_PER_PAGE = 200    # OpenAlex 上限是 200，非 300

# arXiv 下載設定（修正：降低並行數、加入延遲）
ARXIV_PDF_TIMEOUT = 60
ARXIV_HTML_TIMEOUT = 30
ARXIV_MAX_WORKERS = 2          # 修正：從 3 降為 2，避免觸發封鎖
ARXIV_DOWNLOAD_DELAY = (2, 5)  # 每次下載前隨機等待 2~5 秒
ARXIV_RETRY_BASE = 5           # 指數退避基數（秒）
ARXIV_RETRY_MAX = 300          # 最長等待 5 分鐘
ARXIV_PDF_URL = "https://arxiv.org/pdf/{arxiv_id}.pdf"
ARXIV_HTML_URL = "https://arxiv5.labs.arxiv.org/html/{arxiv_id}"

# 文字擷取設定
TEXT_MAX_CHARS = 100_000       # 全文截斷上限
TEXT_MIN_VALID_CHARS = 2_000   # 有效文字最低字元數
TEXT_CACHE_MIN_SIZE = 500      # 快取有效最低 bytes
HTML_MAX_CHARS = 100_000       # 修正：HTML 備用與 PDF 相同上限（原為 5000）

# Phase 3 AI 摘要設定
BATCH_SIZE = 47
SUMMARIES_SUBDIR = "summaries"  # 每篇 {arxiv_id}.json 單獨儲存
SUMMARIZE_MAX_WORKERS = 2       # 並行 AI 摘要 worker 數

# PubMed / NCBI E-utilities
PUBMED_SEARCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi"
PUBMED_SUMMARY_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi"
PUBMED_FETCH_URL = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi"
PUBMED_MAX_RESULTS = 200
PUBMED_DELAY = (0.4, 1.0)       # 無 API key 時每秒 ≤3 次請求

# OpenAlex 並行搜尋
SEARCH_MAX_WORKERS = 2          # 並行類別搜尋 worker 數

# 日誌
LOG_FILENAME = "run.log"

# 相關度關鍵字（用於自動評分備援）
LABOR_KEYWORDS = [
    "job", "labor", "labour", "employment", "wage", "salary",
    "occupation", "skill", "workforce", "hiring", "recruit",
    "vacancy", "job posting", "job classification", "resume",
]
NLP_KEYWORDS = [
    "text classification", "named entity", "bert", "transformer",
    "language model", "embedding", "topic model", "sentiment", "text mining",
]
CAUSAL_KEYWORDS = [
    "causal", "treatment effect", "propensity", "counterfactual",
    "difference-in-difference", "instrumental variable", "regression discontinuity",
]
