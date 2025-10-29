# OneDrive Document Search System

A comprehensive document search system that syncs PDF files from OneDrive, performs OCR extraction, generates AI-powered summaries, and enables semantic search with a user-friendly Streamlit interface.

## 🌟 Features

- **Automatic OneDrive Sync** - Scheduled synchronization of PDF documents from OneDrive/SharePoint
- **OCR Processing** - Advanced text extraction from PDF files via external OCR service
- **AI Summarization** - Automatic document summaries using Google Gemini or OpenRouter
- **Hybrid Search** - Combines semantic (vector) and keyword (BM25) search for better results
- **Hierarchical Storage** - Document and chunk-level vectors for precise retrieval
- **Web Interface** - Clean Streamlit UI for searching and browsing documents
- **Real-time Updates** - Detects new and modified files automatically

## 🏗️ Architecture

The system consists of five main components:

```
                    ┌──────────────┐
                    │  OCR Service │ ← External PDF Text Extraction
                    └──────▲───────┘
                           │
┌─────────────────┐        │
│  Streamlit App  │ ← User Interface (Port 8501)
└────────┬────────┘        │
         │                 │
┌────────▼────────┐        │
│ Search Service  │ ← FastAPI Search API (Port 8000)
└────────┬────────┘        │
         │                 │
┌────────▼─────────┐       │
│     Qdrant       │ ← Vector Database (Port 6333)
└──────────────────┘       │
         ▲                 │
         │                 │
┌────────┴─────────┐       │
│ Ingestion Service│ ──────┘ OneDrive Sync & Processing (Port 8001)
└──────────────────┘
```

### Services

1. **OCR Service** (External) - Extracts text from PDF files page by page
2. **Ingestion Service** - Syncs files from OneDrive, processes PDFs with OCR, generates embeddings and summaries, stores in Qdrant
3. **Search Service** - Provides search API with hybrid dense + sparse vector search
4. **Streamlit App** - Web UI for searching documents and viewing results
5. **Qdrant** - Vector database storing document and chunk embeddings with BM25 sparse vectors

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- Google Gemini API key ([Get one here](https://aistudio.google.com/app/apikey))
- Azure AD app with Microsoft Graph API permissions (Files.Read.All)
- OCR service running (see setup below)

### Setup

1. **Set up OCR Service (Required)**
   
   The document search system requires a separate OCR service for PDF text extraction.
   
   ```bash
   git clone https://github.com/naobyprawira/OneDrive-Document-Search.git
   cd OneDrive-Document-Search
   ```

3. **Configure environment variables**
   ```bash
   cp .env.example .env
   # Edit .env with your credentials and OCR service URL
   ```

4. **Start the services**
   ```bash
   docker-compose up -d
   ```

5. **Access the application**
   - Streamlit UI: http://localhost:8501
   - Search API: http://localhost:8000
   - Ingestion API: http://localhost:8001
   - Qdrant UI: http://localhost:6333/dashboard

## 📝 Configuration

Key environment variables in `.env`:

| Variable | Description | Default |
|----------|-------------|---------|
| `GEMINI_API_KEY` | Google Gemini API key | Required |
| `MS_TENANT_ID` | Azure AD tenant ID | Required |
| `MS_CLIENT_ID` | Azure AD client ID | Required |
| `MS_CLIENT_SECRET` | Azure AD client secret | Required |
| `ONEDRIVE_DRIVE_ID` | OneDrive drive ID | Required |
| `ONEDRIVE_ROOT_PATH` | Folder path to sync | `AI/Document Filing` |
| `OCR_SERVICE_URL` | OCR endpoint URL | Required |
| `EMBED_DIM` | Embedding dimension | `3072` |
| `CHUNK_SIZE` | Text chunk size (chars) | `2000` |
| `SCHEDULE_CRON` | Sync schedule | `0 0 * * *` (daily) |

See `.env.example` for complete list of configuration options.

## 🔧 Usage

### Manual Ingestion

Trigger immediate ingestion via API:

```bash
curl -X POST http://localhost:8001/admin/ingest-now
```

### Search via API

```bash
curl "http://localhost:8000/search?query=laporan+keuangan&top_k=5"
```

### Search via UI

1. Open http://localhost:8501
2. Enter your search query
3. Adjust parameters in sidebar (number of results, chunk candidates)
4. Click "Search" or press Enter
5. View results with summaries and links to OneDrive

## 📂 Project Structure

```
OneDrive-Document-Search/
├── ingestion_service/     # OneDrive sync and document processing
│   ├── main.py           # FastAPI app with scheduler
│   ├── pipeline.py       # Document processing pipeline
│   ├── graph.py          # Microsoft Graph API integration
│   ├── ocr.py            # OCR service integration
│   ├── embeddings.py     # Gemini embedding & summarization
│   ├── storage.py        # Qdrant operations
│   └── config.py         # Configuration
├── search_service/        # Search API
│   └── main.py           # FastAPI search endpoint
├── streamlit_app/         # Web UI
│   └── app.py            # Streamlit interface
├── docker-compose.yml     # Service orchestration
├── .env.example          # Environment template
└── README.md             # This file
```

## 🔍 How It Works

### Ingestion Pipeline

1. **Discovery** - Lists all PDF files from OneDrive recursively
2. **Change Detection** - Compares with local inventory, identifies new/modified files
3. **Download** - Downloads files to temp directory
4. **OCR** - Extracts text from PDF pages in parallel
5. **Summarization** - Generates document summary using AI
6. **Chunking** - Splits text into overlapping chunks
7. **Embedding** - Creates dense vectors (semantic) and sparse vectors (BM25)
8. **Storage** - Stores documents and chunks with vectors in Qdrant

### Search Pipeline

1. **Query Processing** - User enters search query
2. **Dual Embedding** - Generates both semantic and BM25 vectors
3. **Hybrid Search** - Searches chunks using RRF (Reciprocal Rank Fusion)
4. **Deduplication** - Groups chunks by document, keeps best match per document
5. **Document Retrieval** - Fetches document metadata
6. **Ranking** - Sorts by relevance score
7. **Results** - Returns top K documents with summaries and snippets

## 🛠️ Development

### Rebuild a service

```bash
docker-compose up -d --build <service-name>
```

Example:
```bash
docker-compose up -d --build ingestion-service
```

### View logs

```bash
docker logs -f <container-name>
```

Example:
```bash
docker logs -f ingestion-service
```

### Stop services

```bash
docker-compose down
```

## 📊 Collections

The system uses two Qdrant collections:

- **documents** - Document-level vectors and metadata
- **chunks** - Chunk-level vectors for fine-grained search

Both collections use:
- Dense vectors (3072-dim) for semantic search
- Sparse vectors (BM25) for keyword search

## 🐛 Troubleshooting

**Ingestion not processing files:**
- Check ingestion service logs: `docker logs -f ingestion-service`
- Verify OCR service is accessible
- Check OneDrive credentials and permissions

**Search returns no results:**
- Ensure ingestion has completed successfully
- Check Qdrant UI to verify documents exist
- Verify search service can connect to Qdrant

**"v_bm25 not found" error:**
- Collections need BM25 support
- Ensure using `documents` and `chunks` collections
- These were created with sparse vector configuration
