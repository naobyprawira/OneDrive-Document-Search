# Streamlit Document Search UI

A simple web interface for searching accounting documents using semantic search.

## Features

- 🔍 **Semantic Search**: Search documents using natural language queries in Indonesian or English
- 📊 **Relevance Scoring**: Results ranked by semantic similarity
- 📄 **Document Summaries**: View AI-generated summaries for each document
- 🔗 **OneDrive Integration**: Direct links to open documents in OneDrive
- ⚙️ **Configurable Parameters**: Adjust number of results and search depth

## Architecture

The Streamlit app is a simple frontend that communicates with the search-service:

```
User Query → Streamlit UI → search-service API → Qdrant (vector search) → Results
```

## Running the App

### With Docker Compose (Recommended)

```bash
# Start all services including Streamlit
docker-compose up -d

# Access the UI at http://localhost:8501
```

### Standalone (Development)

```bash
# Install dependencies
pip install -r requirements.txt

# Set environment variable
export SEARCH_API_URL=http://localhost:8000/search

# Run the app
streamlit run app.py
```

## Configuration

Environment variables:

- `SEARCH_API_URL`: URL of the search service API (default: `http://localhost:8000/search`)

Search parameters (configurable in UI):

- `top_k`: Number of results to return (1-50)
- `chunk_candidates`: Number of chunks to search before deduplication (1-200)

## Usage

1. Enter your search query in Indonesian or English
2. Adjust search parameters in the sidebar if needed
3. Click "Search" or press Enter
4. Browse results with relevance scores
5. Click "Open in OneDrive" to view the full document

## Example Queries

- "perjanjian kredit" (credit agreements)
- "laporan keuangan 2022" (financial reports 2022)
- "perpajakan SPT" (tax returns)
- "audit BIG" (audit reports for BIG)
