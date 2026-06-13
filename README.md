# ArgusAI — Privacy-Preserving Agentic BI Pipeline

ArgusAI is an agentic business intelligence pipeline that transforms raw CSV data into executive-grade reports and interactive dashboards — with privacy built in at the core.

![ArgusAI Pipeline](architecture.png)

---

## What It Does

Drop in any business CSV. ArgusAI autonomously:

- Profiles the dataset (nulls, skew, encoding, cardinality)
- Detects the business domain (retail, HR, finance, logistics, etc.)
- **Anonymizes PII via Fernet encryption before any data touches an LLM**
- Runs 8 statistical analyses (outliers, trends, correlation, segmentation, Pareto)
- Augments findings with targeted web search (DuckDuckGo)
- Performs causal reasoning cross-referencing internal data + external evidence
- Generates a 1500+ word executive PDF report with human-in-the-loop approval
- Builds an interactive Plotly HTML dashboard with human-in-the-loop chart approval
- Decrypts anonymized identifiers back to real values in final outputs

---

## Architecture

11-node LangGraph pipeline · Cerebras (primary LLM) + Groq (fallback) · MemorySaver checkpointing · LangSmith tracing

---

## Eval Framework

ArgusAI includes a custom 6-dimension evaluation framework:

| Dimension | What It Checks |
|-----------|----------------|
| Domain Detection | Valid domain, confidence score, metric-direction alignment |
| Faithfulness | No invented numbers in report vs. statistical findings |
| Chart Validity | No duplicate x/y pairs, valid chart-type constraints |
| Anonymization | No PII leakage, all values replaced with `ID-` tokens |
| Causal Reasoning | Variance decomposition sums, verdict validity, evidence presence |
| Report Structure | Required sections present, action count, minimum word count |

---

## Stack

`LangGraph` · `LangChain` · `Cerebras` · `Groq` · `Plotly` · `WeasyPrint` · `Fernet` · `DuckDuckGo` · `LangSmith`

---

## Status

> ⚠️ Currently implemented as a Kaggle notebook. Deployment (API + UI) in progress.

Tested on: IBM HR Attrition dataset

---

## Run It

1. Clone the repo
2. Add your API keys as Kaggle Secrets: `CEREBRAS_API_KEY`, `GROQ_API_KEY`, `LANGCHAIN_API_KEY`
3. Upload your CSV to Kaggle input
4. Run all cells
