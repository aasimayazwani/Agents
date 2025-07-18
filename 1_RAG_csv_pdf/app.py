import streamlit as st
from typing import Union           # ⬅️ make sure this import is already at the top once
from langchain_core.documents import Document  # ⬅️ place with your other imports
import os
import json
import pandas as pd
from datetime import datetime
import re
from typing import List, Any
from langchain_groq import ChatGroq
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain.chains.retrieval import create_retrieval_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader, CSVLoader
from langgraph.graph import StateGraph, END
from pydantic import BaseModel, ValidationError

# === Directories ===
BASE_DIR = "rag_app_data"
FAISS_DIR = os.path.join(BASE_DIR, "faiss_index")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_docs")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(FAISS_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# === Environment ===
if not os.environ.get("OPENAI_API_KEY") or not os.environ.get("GROQ_API_KEY"):
    st.error("API keys missing. Please set OPENAI_API_KEY and GROQ_API_KEY in Streamlit Cloud secrets.")
    st.stop()

# === LLM & Embeddings ===
llm = ChatGroq(groq_api_key=os.environ['GROQ_API_KEY'], model_name="llama3-8b-8192")
embedder = OpenAIEmbeddings()
prompt = ChatPromptTemplate.from_template("""
Answer the questions based on the provided context only.
<context>
{context}
</context>
Question: {input}
""")

# === Session State ===
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "vectors" not in st.session_state:
    st.session_state.vectors = None
if "csv_dataframes" not in st.session_state:
    st.session_state.csv_dataframes = {}
if "uploaded_files" not in st.session_state:
    st.session_state.uploaded_files = []
if "pending_answer" not in st.session_state:
    st.session_state.pending_answer = None
if "pending_query" not in st.session_state:
    st.session_state.pending_query = None

# === Auto-load existing vectorstore ===
try:
    faiss_index_path = os.path.join(FAISS_DIR, "index.faiss")
    faiss_meta_path = os.path.join(FAISS_DIR, "index.pkl")
    if os.path.exists(faiss_index_path) and os.path.exists(faiss_meta_path):
        st.session_state.vectors = FAISS.load_local(FAISS_DIR, embedder, allow_dangerous_deserialization=True)
except Exception as e:
    st.warning(f"Could not load existing vector store: {e}")

# === State Schema for LangGraph ===
class AgentState(BaseModel):
    query: str
    documents: List[Any] = []
    csv_result: str = ""
    pdf_context: Union[str, List[Document]] = ""
    final_answer: str = ""

    class Config:
        arbitrary_types_allowed = True

# === Agent Functions ===
def file_processor_agent(state: AgentState) -> AgentState:
    """Processes uploaded files and updates state with documents."""
    all_docs = []
    
    # Process files from session state
    for file in st.session_state.get("uploaded_files", []):
        try:
            path = os.path.join(UPLOAD_DIR, file.name)
            
            # Write file to disk
            with open(path, "wb") as f:
                f.write(file.getvalue())  # Use getvalue() instead of read()
            
            if file.name.endswith(".pdf"):
                loader = PyPDFLoader(path)
                docs = loader.load()
                all_docs.extend(docs)
                
            elif file.name.endswith(".csv"):
                loader = CSVLoader(file_path=path, encoding="utf-8")
                docs = loader.load()
                all_docs.extend(docs)
                
                # Load DataFrame for CSV analysis
                try:
                    df = pd.read_csv(path)
                    st.session_state.csv_dataframes[file.name] = df
                    with st.expander(f"📊 Summary of `{file.name}`"):
                        st.dataframe(df.describe(include='all').transpose())
                except Exception as e:
                    st.warning(f"Unable to summarize {file.name}: {e}")
                    
        except Exception as e:
            st.error(f"Error processing {file.name}: {e}")
            continue
    
    # Process documents if any were loaded
    if all_docs:
        try:
            splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
            state.documents = splitter.split_documents(all_docs)
            
            # Create new index
            new_index = FAISS.from_documents(state.documents, embedder)
            
            # Merge with existing or create new
            if st.session_state.vectors:
                st.session_state.vectors.merge_from(new_index)
            else:
                st.session_state.vectors = new_index
            
            # Save to disk
            st.session_state.vectors.save_local(FAISS_DIR)
            st.success("✅ Documents processed and indexed.")
            
        except Exception as e:
            st.error(f"Error creating vector index: {e}")
    
    return state

def csv_query_agent(state: AgentState) -> AgentState:
    """Handles CSV-related queries using pandas."""
    state.csv_result = ""
    
    if not st.session_state.csv_dataframes:
        return state
    
    for name, df in st.session_state.csv_dataframes.items():
        try:
            # Check if query relates to this CSV
            cols_lower = [col.lower() for col in df.columns]
            query_lower = state.query.lower()
            
            # More robust column matching
            relevant_cols = [col for col in cols_lower if col in query_lower]
            
            if relevant_cols or any(keyword in query_lower for keyword in ['sum', 'average', 'mean', 'count', 'describe']):
                try:
                    if "sum" in query_lower:
                        result = df.sum(numeric_only=True)
                    elif "average" in query_lower or "mean" in query_lower:
                        result = df.mean(numeric_only=True)
                    elif "count" in query_lower:
                        result = df.count()
                    else:
                        result = df.describe(include='all').transpose()
                    
                    state.csv_result = f"From `{name}`:\n{result.to_string()}"
                    return state
                    
                except Exception as e:
                    state.csv_result = f"Error analyzing CSV {name}: {e}"
                    return state
        except Exception as e:
            st.error(f"Error processing CSV {name}: {e}")
            continue
    
    return state

def pdf_retrieval_agent(state: AgentState) -> AgentState:
    """Retrieves relevant PDF context using FAISS."""
    state.pdf_context = ""
    
    # Only proceed if we have vectors and no CSV result
    if st.session_state.vectors and not state.csv_result:
        try:
            chain = create_stuff_documents_chain(llm, prompt)
            retriever = st.session_state.vectors.as_retriever()
            retrieval_chain = create_retrieval_chain(retriever, chain)
            
            with st.spinner("Searching documents..."):
                result = retrieval_chain.invoke({"input": state.query})
                #state.pdf_context = result.get("context", "")
                #state.final_answer = result.get("answer", "")
                ctx = result.get("context", "")
                if isinstance(ctx, list):                      # flatten list of Documents
                    ctx = "\n\n".join(
                        [d.page_content for d in ctx if hasattr(d, "page_content")]
                    )
                state.pdf_context = ctx
                state.final_answer = result.get("answer", "")
                
        except Exception as e:
            st.error(f"Error during PDF retrieval: {e}")
            state.final_answer = f"Error retrieving information: {e}"
    
    return state

def response_generator_agent(state: AgentState) -> AgentState:
    """Generates final response using LLM if needed."""
    if state.csv_result:
        state.final_answer = state.csv_result
    elif state.pdf_context and state.final_answer:
        # Already set in pdf_retrieval_agent
        pass
    else:
        try:
            with st.spinner("Generating response..."):
                result = llm.invoke(state.query)
                state.final_answer = result.content if hasattr(result, "content") else str(result)
        except Exception as e:
            st.error(f"Error generating response: {e}")
            state.final_answer = f"I apologize, but I encountered an error: {e}"
    
    return state

def supervisor_agent(state: AgentState) -> str:
    """Routes query to appropriate agent or END."""
    try:
        # Check if query is CSV-related
        if st.session_state.csv_dataframes:
            query_lower = state.query.lower()
            for df in st.session_state.csv_dataframes.values():
                cols_lower = [col.lower() for col in df.columns]
                if any(col in query_lower for col in cols_lower) or any(keyword in query_lower for keyword in ['sum', 'average', 'mean', 'count', 'describe']):
                    return "csv_query_agent"
        
        # Check if we have PDF vectors
        if st.session_state.vectors:
            return "pdf_retrieval_agent"
        else:
            return "response_generator_agent"
            
    except Exception as e:
        st.error(f"Error in supervisor routing: {e}")
        return "response_generator_agent"

# === LangGraph Workflow ===
workflow = StateGraph(AgentState)
workflow.add_node("file_processor_agent", file_processor_agent)
workflow.add_node("csv_query_agent", csv_query_agent)
workflow.add_node("pdf_retrieval_agent", pdf_retrieval_agent)
workflow.add_node("response_generator_agent", response_generator_agent)

# Set entry point
workflow.set_entry_point("file_processor_agent")

# Add conditional edges with proper routing
workflow.add_conditional_edges(
    "file_processor_agent",
    supervisor_agent,
    {
        "csv_query_agent": "csv_query_agent",
        "pdf_retrieval_agent": "pdf_retrieval_agent",
        "response_generator_agent": "response_generator_agent"
    }
)

workflow.add_conditional_edges(
    "csv_query_agent",
    lambda state: "response_generator_agent" if state.csv_result else "pdf_retrieval_agent",
    {
        "response_generator_agent": "response_generator_agent",
        "pdf_retrieval_agent": "pdf_retrieval_agent"
    }
)

workflow.add_edge("pdf_retrieval_agent", "response_generator_agent")
workflow.add_edge("response_generator_agent", END)

try:
    app = workflow.compile()
except Exception as e:
    st.error(f"Error compiling workflow: {e}")
    st.stop()

# === Streamlit Page ===
st.set_page_config(page_title="Multi-Agent RAG Chatbot | PDF + CSV", layout="wide")
st.title("📄 Multi-Agent RAG Chatbot | CSV + PDF | Upload + Summarize + Chat")

# === Sidebar with file listing and delete buttons ===
with st.sidebar:
    st.markdown("### 📂 Uploaded Files")
    try:
        existing_files = sorted(f for f in os.listdir(UPLOAD_DIR) if f.endswith((".csv", ".pdf")))
        if existing_files:
            for file in existing_files:
                file_path = os.path.join(UPLOAD_DIR, file)
                col1, col2 = st.columns([3, 1])
                with col1:
                    st.markdown(f"📄 `{file}`")
                with col2:
                    if st.button("❌", key=f"delete_{file}"):
                        try:
                            os.remove(file_path)
                            st.success(f"{file} deleted.")
                            st.rerun()
                        except Exception as e:
                            st.error(f"Error deleting {file}: {e}")
        else:
            st.info("No uploaded files found.")
    except Exception as e:
        st.error(f"Error listing files: {e}")

# === Upload Section ===
with st.expander("➕ Upload Files", expanded=False):
    uploaded = st.file_uploader("Select PDF or CSV files", type=["pdf", "csv"], accept_multiple_files=True)
    if uploaded:
        st.session_state.uploaded_files = uploaded
        try:
            initial_state = AgentState(query="")
            app.invoke(initial_state)
        except Exception as e:
            st.error(f"Error processing uploaded files: {e}")

# === Chat Input ===
user_input = st.chat_input("Ask a question about your uploaded documents")
if user_input:
    try:
        state = AgentState(query=user_input)
        with st.spinner("Processing query..."):
            result = app.invoke(state)
        answer = result.get("final_answer", "⚠️ No response was generated.")

        # Store pending result for human review
        st.session_state.pending_query = user_input
        st.session_state.pending_answer = answer

    except Exception as e:
        st.error(f"Error processing your query: {e}")

# === Human-in-the-loop Review Section ===
if st.session_state.pending_answer is not None:
    st.subheader("🧑‍🔬 Review and Edit the Response")
    edited_answer = st.text_area("LLM-generated answer:", value=st.session_state.pending_answer, height=200)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("✅ Approve & Save to History"):
            st.session_state.chat_history.append({
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "question": st.session_state.pending_query,
                "answer": edited_answer,
            })
            st.session_state.pending_answer = None
            st.session_state.pending_query = None
            st.success("Saved to history.")
            st.rerun()

    with col2:
        if st.button("🗑️ Discard"):
            st.session_state.pending_answer = None
            st.session_state.pending_query = None
            st.info("Response discarded.")
            st.rerun()

# === Display Chat ===
for msg in reversed(st.session_state.chat_history):
    with st.chat_message("user"):
        st.markdown(f"**You ({msg['timestamp']}):** {msg['question']}")
    with st.chat_message("assistant"):
        st.markdown(f"**Bot:** {msg['answer']}")



# === Utilities ===
col1, col2 = st.columns([1, 1])
with col1:
    if st.button("🧹 Clear Chat History"):
        st.session_state.chat_history = []
        st.success("Chat history cleared.")
        st.rerun()

with col2:
    if st.session_state.chat_history:
        json_data = json.dumps(st.session_state.chat_history, indent=2)
        st.download_button("⬇️ Download Chat Log", json_data, file_name="chat_history.json")