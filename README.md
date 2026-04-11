# Literature Reviews — 文獻回顧自動化工具

支援 arXiv（via OpenAlex）與 PubMed 多來源文獻搜尋、下載、AI 結構化摘要、CSV/Excel 輸出與綜合報告。

## 快速開始

```bash
uv sync
export ANTHROPIC_API_KEY=sk-ant-...

# 自由主題搜尋（arXiv）
litreview run "Causal Inference" --skip-summarize

# 同時搜尋 arXiv + PubMed
litreview run "drug discovery deep learning" --source arxiv,pubmed

# 使用預設查詢集
litreview run my_topic --categories LLM,Causal_Robins

# 完整流程 + 延伸關鍵字建議
litreview run "transformer architecture" --suggest

# PubMed 搜尋（可加 NCBI API Key 提高速率）
litreview run "collagen supplement" --source pubmed --ncbi-api-key $NCBI_KEY

# 覆寫設定參數
litreview run "AI safety" --download-workers 4 --batch-size 100
litreview run "NLP" --pdf-timeout 120 --text-max-chars 200000
litreview run "ML" --output-dir /tmp/my_reviews --search-workers 4

# 補跑摘要（可覆寫設定） / 重建報告
litreview summarize projects/20260405_causal_inference/ --summarize-workers 4
litreview build projects/20260405_causal_inference/
litreview list-projects
```

## 完整流程

```
Phase 1    文獻搜尋      →  articles_metadata.json + batch_{n}.json
Phase 2    PDF/HTML 下載  →  articles/*.pdf + texts/*.txt
Phase 3    AI 摘要        →  summaries/{id}.json
Phase 3.5  關鍵字建議     →  keyword_suggestions.md（--suggest）
Phase 4    建構 CSV       →  study.csv + articles.csv + articles.xlsx
Phase 5    綜合報告        →  literature_review_synthesis.md
```

## 每個主題的專案目錄

```
projects/20260405_causal_inference/
├── articles_metadata.json
├── batch_{0-N}.json
├── study.csv / articles.csv / articles.xlsx
├── literature_review_synthesis.md
├── keyword_suggestions.md     ← 延伸搜尋建議（--suggest）
├── run.log                    ← 執行日誌
├── articles/                  ← PDF
├── texts/                     ← 全文純文字 / PubMed 摘要
└── summaries/                 ← AI 摘要（一篇一 JSON）
```

## 搜尋來源

| 來源 | 說明 |
|------|------|
| `arxiv`（預設） | OpenAlex API，篩選 open access arXiv 論文 |
| `pubmed` | NCBI E-utilities，取得摘要作為全文替代 |
| `arxiv,pubmed` | 同時搜尋兩個來源並去重 |

## CLI 設定覆寫參數

所有設定參數皆可透過命令列選項覆寫，無需修改 `config.py`：

| 選項 | 適用指令 | 說明 |
|------|----------|------|
| `--output-dir` | `run` | 專案輸出基礎目錄（預設：程式根目錄） |
| `--batch-size` | `run` | 分批儲存筆數 |
| `--download-workers` | `run` | PDF 下載並行 worker 數 |
| `--summarize-workers` | `run`, `summarize` | AI 摘要並行 worker 數 |
| `--search-workers` | `run` | 搜尋並行 worker 數 |
| `--openalex-mailto` | `run` | OpenAlex API mailto 參數 |
| `--pdf-timeout` | `run` | PDF 下載逾時秒數 |
| `--html-timeout` | `run` | HTML 下載逾時秒數 |
| `--text-max-chars` | `run`, `summarize` | 全文截斷上限字元數 |

## 環境變數

| 變數 | 說明 |
|------|------|
| `ANTHROPIC_API_KEY` | Claude API Key（Phase 3 + 3.5 必須） |
| `NCBI_API_KEY` | NCBI API Key（選填，提高 PubMed 速率至 10 req/s） |
