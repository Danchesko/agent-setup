---
name: "exa-search"
description: "Use when the user needs web search, web sources, similar-page discovery, content extraction from URLs, cited answers, or deep research on a topic. Provides the Exa AI REST API (api.exa.ai) via curl: semantic/keyword/deep search, findSimilar, contents extraction, direct answers with citations, and async agent-style research tasks with structured output."
disable-model-invocation: true
---

# Exa Search

Web search via Exa AI: semantic search, deep search with structured output, find similar pages, answer questions, and async research tasks. Use when you need web sources, similar content, or deep research on a topic.

## Setup

```bash
# Load the key for this shell if it is not already set.
if [ -z "${EXA_API_KEY:-}" ]; then
  EXA_API_KEY=$(security find-generic-password -s "exa-api-key" -w) && export EXA_API_KEY
fi
# Dashboard & credits: https://dashboard.exa.ai
```

## Endpoints

| Endpoint | Use when |
|----------|----------|
| `/search` | Find web pages by meaning (semantic) or keywords |
| `/search` + `type=deep` | Multi-query deep search with optional structured answers |
| `/findSimilar` | Given a URL, find pages like it |
| `/contents` | Extract text/summary/highlights from known URLs |
| `/answer` | Get a direct answer to a question with citations |
| `/research` | Async deep research tasks with structured output (agent-style) |

## 1. Search

```bash
curl -s -X POST "https://api.exa.ai/search" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "query": "transformer architecture explained",
    "type": "auto",
    "numResults": 10,
    "contents": { "text": { "maxCharacters": 3000 } }
  }' | jq '.results[] | {title, url, text}'
```

### Search types

| Type | Behavior |
|------|----------|
| `auto` | Picks best method (default) |
| `neural` | Embedding-based semantic search |
| `fast` | Keyword-based, quick |
| `deep` | Comprehensive multi-query search, highest quality |
| `instant` | Low-latency neural |

### Categories (optional filter)

`company`, `research paper`, `news`, `pdf`, `tweet`, `personal site`, `financial report`, `people`

### Filters

```json
{
  "query": "climate policy 2025",
  "numResults": 20,
  "category": "research paper",
  "includeDomains": ["nature.com", "science.org"],
  "excludeDomains": ["wikipedia.org"],
  "startPublishedDate": "2025-01-01",
  "endPublishedDate": "2025-12-31",
  "includeText": ["carbon tax"],
  "excludeText": ["opinion"],
  "contents": {
    "text": { "maxCharacters": 2000 },
    "highlights": true,
    "summary": true
  }
}
```

### Content options

| Option | What it returns |
|--------|----------------|
| `text` | Full page text (set `maxCharacters`, `verbosity`: `compact`/`standard`/`full`) |
| `highlights` | Key excerpts (pass `query` to bias) |
| `summary` | AI summary (pass `query` to bias, `schema` for structured output) |

Livecrawl: `"livecrawl": "always"` fetches fresh content instead of cache.

## 2. Deep Search

Same `/search` endpoint with `type: "deep"`. Returns higher quality results through multi-query expansion and reasoning.

```bash
curl -s -X POST "https://api.exa.ai/search" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "query": "What are the latest battery breakthroughs?",
    "type": "deep",
    "numResults": 10,
    "answer": true,
    "contents": { "text": true }
  }' | jq '{answer, results: [.results[] | {title, url}]}'
```

### Deep search with structured output

```bash
curl -s -X POST "https://api.exa.ai/search" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "query": "Compare React vs Vue in 2025",
    "type": "deep",
    "answer": true,
    "effort": "max",
    "outputSchema": {
      "type": "object",
      "properties": {
        "summary": { "type": "string" },
        "react_pros": { "type": "array", "items": { "type": "string" } },
        "vue_pros": { "type": "array", "items": { "type": "string" } },
        "recommendation": { "type": "string" }
      },
      "required": ["summary"]
    },
    "contents": { "text": true }
  }' | jq '.'
```

### Effort levels

| Effort | Compute | Use case |
|--------|---------|----------|
| `lite` | Low (default) | Quick deep search |
| `base` | Medium | Expanded search + reasoning |
| `max` | High | Maximum thoroughness |

### Additional queries

Provide alternative phrasings to broaden deep search coverage:

```json
{
  "query": "autonomous vehicle safety statistics",
  "type": "deep",
  "additionalQueries": [
    "self-driving car accident rates 2024-2025",
    "waymo cruise safety data comparison",
    "NHTSA autonomous vehicle crash reports"
  ]
}
```

## 3. Find Similar

Given a URL, find semantically similar pages.

```bash
curl -s -X POST "https://api.exa.ai/findSimilar" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "url": "https://paulgraham.com/greatwork.html",
    "numResults": 10,
    "excludeSourceDomain": true,
    "contents": { "text": { "maxCharacters": 1000 } }
  }' | jq '.results[] | {title, url}'
```

Supports same filters as search: `includeDomains`, `excludeDomains`, date ranges, `category`.

## 4. Contents

Extract content from known URLs (no search needed).

```bash
curl -s -X POST "https://api.exa.ai/contents" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "urls": ["https://openai.com/research"],
    "text": true,
    "summary": true,
    "highlights": { "query": "safety research" }
  }' | jq '.'
```

Options: `subpages` (crawl N subpages), `subpageTarget` (specific paths), `extras` (`links`, `imageLinks`).

## 5. Answer

Direct answer to a question, backed by search results.

```bash
curl -s -X POST "https://api.exa.ai/answer" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "query": "What caused the 2008 financial crisis?",
    "numResults": 5
  }' | jq '{answer, citations: [.results[] | {title, url}]}'
```

Streaming:

```bash
curl -s -X POST "https://api.exa.ai/answer" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{"query": "Explain quantum computing", "stream": true}'
```

## 6. Research (Async Deep Research)

Agent-style research: Exa plans, searches, reads, reasons, and produces a structured report. Runs async — create a task, poll for results.

### Models

| Model | Speed | Depth |
|-------|-------|-------|
| `exa-research-fast` | Fast | Good for simple questions |
| `exa-research` | Medium | Balanced |
| `exa-research-pro` | Slow | Maximum depth and reasoning |

### Create a research task

```bash
curl -s -X POST "https://api.exa.ai/research" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "content-type: application/json" \
  -d '{
    "instructions": "What are the leading open-source LLMs in 2025? Compare their benchmarks, licensing, and real-world adoption.",
    "model": "exa-research",
    "outputSchema": {
      "type": "object",
      "properties": {
        "models": {
          "type": "array",
          "items": {
            "type": "object",
            "properties": {
              "name": { "type": "string" },
              "organization": { "type": "string" },
              "license": { "type": "string" },
              "benchmark_score": { "type": "string" },
              "adoption_notes": { "type": "string" }
            }
          }
        },
        "summary": { "type": "string" }
      },
      "required": ["models", "summary"]
    }
  }' | jq '{researchId: .researchId, status: .status}'
```

### Poll for results

```bash
RESEARCH_ID="your-research-id"
curl -s "https://api.exa.ai/research/$RESEARCH_ID" \
  -H "x-api-key: $EXA_API_KEY" | jq '{status, output}'
```

### Stream events (SSE)

```bash
curl -s "https://api.exa.ai/research/$RESEARCH_ID?stream=true" \
  -H "x-api-key: $EXA_API_KEY" \
  -H "accept: text/event-stream"
```

Events: `research-definition` → `plan-definition` → `plan-operation` (think/search/crawl) → `task-*` → `research-output`

### List research tasks

```bash
curl -s "https://api.exa.ai/research?limit=10" \
  -H "x-api-key: $EXA_API_KEY" | jq '.data[] | {researchId, status, instructions}'
```

## Batch Queries Pattern

Run many searches, deduplicate by URL:

```bash
QUERIES=(
  "topic A primary sources"
  "topic A academic research"
  "topic A recent news 2025"
)

for q in "${QUERIES[@]}"; do
  curl -s -X POST "https://api.exa.ai/search" \
    -H "x-api-key: $EXA_API_KEY" \
    -H "content-type: application/json" \
    -d "{
      \"query\": \"$q\",
      \"numResults\": 8,
      \"excludeDomains\": [\"wikipedia.org\"],
      \"contents\": { \"text\": { \"maxCharacters\": 2000 } }
    }" | jq -c '.results[]' >> /tmp/exa-batch.jsonl
  sleep 0.5
done

jq -s 'unique_by(.url)' /tmp/exa-batch.jsonl > /tmp/exa-deduped.json
echo "Unique: $(jq length /tmp/exa-deduped.json)"
```

## Costs

Check current rates and available credits in the [Exa dashboard](https://dashboard.exa.ai).

## Response Shape

All search endpoints return:

```json
{
  "requestId": "...",
  "results": [
    {
      "title": "...",
      "url": "...",
      "publishedDate": "...",
      "score": 0.95,
      "text": "...",
      "highlights": ["..."],
      "summary": "..."
    }
  ],
  "costDollars": { "total": 0.003 },
  "searchType": "neural",
  "answer": "..."
}
```
