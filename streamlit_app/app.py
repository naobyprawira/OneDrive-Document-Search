import os
import requests
import streamlit as st

# Configuration
SEARCH_API_URL = os.getenv("SEARCH_API_URL", "http://localhost:8000/search")

st.set_page_config(
    page_title="Document Search",
    page_icon="🔍",
    layout="wide",
)

# Title and description
st.title("🔍 Document Search")
st.markdown("Search through accounting documents using semantic search powered by vector embeddings.")

# Sidebar for search parameters
with st.sidebar:
    st.header("Search Parameters")
    top_k = st.slider("Number of results", min_value=1, max_value=50, value=5, help="Number of top results to return")
    chunk_candidates = st.slider(
        "Chunk candidates", 
        min_value=1, 
        max_value=200, 
        value=50, 
        help="Number of chunks to search before deduplication"
    )

# Search input
query = st.text_input(
    "Enter your search query:",
    placeholder="e.g., perjanjian kredit, laporan keuangan, perpajakan...",
    help="Enter keywords or questions in Indonesian or English"
)

# Search button
if st.button("🔍 Search", type="primary", use_container_width=True) or query:
    if not query.strip():
        st.warning("Please enter a search query.")
    else:
        with st.spinner("Searching documents..."):
            try:
                # Call search API
                response = requests.get(
                    SEARCH_API_URL,
                    params={
                        "query": query,
                        "top_k": top_k,
                        "chunk_candidates": chunk_candidates,
                    },
                    timeout=30,
                )
                response.raise_for_status()
                data = response.json()
                results = data.get("results", [])
                
                if not results:
                    st.info("No results found. Try different keywords.")
                else:
                    st.success(f"Found {len(results)} results")
                    
                    # Display results
                    for idx, result in enumerate(results, 1):
                        with st.container():
                            st.markdown(f"### {idx}. {result.get('fileName', 'Untitled')}")
                            
                            # Web URL buttons - file and folder
                            web_url = result.get("webUrl")
                            if web_url:
                                col_btn1, col_btn2 = st.columns(2)
                                with col_btn1:
                                    st.link_button("📃 Open File", web_url, use_container_width=True)
                                with col_btn2:
                                    # Get folder URL by removing the filename from the path
                                    file_name = result.get('fileName', '')
                                    if file_name and file_name in web_url:
                                        folder_url = web_url.rsplit('/' + file_name, 1)[0]
                                    else:
                                        # Fallback: remove last segment after last slash
                                        folder_url = web_url.rsplit('/', 1)[0]
                                    st.link_button("📂 Open Folder", folder_url, use_container_width=True)
                            
                            # Summary
                            summary = result.get("summary", "No summary available")
                            with st.expander("📄 Summary", expanded=False):
                                st.markdown(summary)
                            
                            st.divider()
            
            except requests.exceptions.RequestException as e:
                st.error(f"Error connecting to search service: {e}")
                st.info(f"Make sure the search service is running at {SEARCH_API_URL}")
            except Exception as e:
                st.error(f"An error occurred: {e}")

# Footer
st.markdown("---")
st.markdown(
    """
    <div style='text-align: center; color: gray;'>
    <small>Document Search Stack v2.0 | Powered by Qdrant + Google Gemini</small>
    </div>
    """,
    unsafe_allow_html=True,
)
