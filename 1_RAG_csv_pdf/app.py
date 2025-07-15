import streamlit as st
import os
import json
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import re
from typing import Dict, List, Any
from langchain_groq import ChatGroq
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader, CSVLoader
from langgraph.graph import StateGraph, END
from pydantic import BaseModel

# === Directories ===
BASE_DIR = "rag_app_data"
FAISS_DIR = os.path.join(BASE_DIR, "faiss_index")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_docs")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(FAISS_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# === Environment ===
load_dotenv()
if not os.getenv("OPENAI_API_KEY") or not os.getenv("GROQ_API_KEY"):
    st.error("API keys missing. Please set OPENAI_API_KEY and GROQ_API_KEY in .env file.")
    st.stop()

os.environ['OPENAI_API_KEY'] = os.getenv("OPENAI_API_KEY")
os.environ['GROQ_API_KEY'] = os.getenv("GROQ_API_KEY")

# === LLM & Embeddings ===
llm = ChatGroq(groq_api_key=os.environ['GROQ_API_KEY'], model_name="Llama3-8b-8192")
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

# === Auto-load existing vectorstore ===
faiss_index_path = os.path.join(FAISS_DIR, "index.faiss")
faiss_meta_path = os.path.join(FAISS_DIR, "index.pkl")
if os.path.exists(faiss_index_path) and os.path.exists(faiss_meta_path):
    st.session_state.vectors = FAISS.load_local(FAISS_DIR, embedder, allow_dangerous_deserialization=True)

# === State Schema for LangGraph ===
class AgentState(BaseModel):
    query: str
    documents: List[Any] = []
    csv_dataframes: Dict[str, pd.DataFrame] = {}
    csv_result: str = ""
    pdf_context: str = ""
    final_answer: str = ""

# === Agent Functions ===
def file_processor_agent(state: AgentState) -> AgentState:
    """Processes uploaded files and updates state with documents and DataFrames."""
    all_docs = []
    for file in st.session_state.get("uploaded_files", []):
        path = os.path.join(UPLOAD_DIR, file.name)
        with open(path, "wb") as f:
            f.write(file.read())
        if file.name.endswith(".pdf"):
            loader = PyPDFLoader(path)
            all_docs.extend(loader.load())
        elif file.name.endswith(".csv"):
            loader = CSVLoader(file_path=path, encoding="utf-8")
            all_docs.extend(loader.load())
            try:
                df = pd.read_csv(path)
                state.csv_dataframes[file.name] = df
                st.session_state.csv_dataframes[file.name] = df
                with st.expander(f"📊 Summary of `{file.name}`"):
                    st.dataframe(df.describe(include='all').transpose())
            except Exception as e:
                st.warning(f"Unable to summarize {file.name}: {e}")
    if all_docs:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        state.documents = splitter.split_documents(all_docs)
        new_index = FAISS.from_documents(state.documents, embedder)
        if st.session_state.vectors:
            st.session_state.vectors.merge_from(new_index)
        else:
            st.session_state.vectors = new_index
        st.session_state.vectors.save_local(FAISS_DIR)
        st.success("✅ Documents processed and indexed.")
    return state

def csv_query_agent(state: AgentState) -> AgentState:
    """Handles CSV-related queries using pandas."""
    state.csv_result = ""
    for name, df in state.csv_dataframes.items():
        cols_lower = [col.lower() for col in df.columns]
        if any(re.search(col, state.query.lower()) for col in cols_lower):
            try:
                if "sum" in state.query.lower():
                    result = df.sum(numeric_only=True)
                elif "average" in state.query.lower() or "mean" in state.query.lower():
                    result = df.mean(numeric_only=True)
                elif "count" in state.query.lower():
                    result = df.count()
                else:
                    result = df.describe(include='all').transpose()
                state.csv_result = f"From `{name}`:\n{result.to_string()}"
                return state
            except Exception as e:
                state.csv_result = f"Error parsing CSV with pandas: {e}"
                return state
    return state

def pdf_retrieval_agent(state: AgentState) -> AgentState:
    """Retrieves relevant PDF context using FAISS."""
    state.pdf_context = ""
    if st.session_state.vectors and not state.csv_result:
        chain = create_stuff_documents_chain(llm, prompt)
        retriever = st.session_state.vectors.as_retriever()
        retrieval_chain = create_retrieval_chain(retriever, chain)
        with st.spinner("Searching documents..."):
            result = retrieval_chain.invoke({"input": state.query})
            state.pdf_context = result.get("context", "")
            state.final_answer = result.get("answer", "")
        return state
    return state

def response_generator_agent(state: AgentState) -> AgentState:
    """Generates final response using LLM if needed."""
    if state.csv_result:
        state.final_answer = state.csv_result
    elif state.pdf_context:
        # Already set in pdf_retrieval_agent
        pass
    else:
        with st.spinner("Using LLM without document context..."):
            result = llm.invoke(state.query)
            state.final_answer = result.content if hasattr(result, "content") else str(result)
    return state

def supervisor_agent(state: AgentState) -> str:
    """Routes query to appropriate agent or END."""
    if state.csv_dataframes and any(
        re.search(col, state.query.lower()) for df in state.csv_dataframes.values() for col in df.columns
    ):
        return "csv_query_agent"
    elif st.session_state.vectors:
        return "pdf_retrieval_agent"
    else:
        return "response_generator_agent"

# === LangGraph Workflow ===
workflow = StateGraph(AgentState)
workflow.add_node("file_processor_agent", file_processor_agent)
workflow.add_node("csv_query_agent", csv_query_agent)
workflow.add_node("pdf_retrieval_agent", pdf_retrieval_agent)
workflow.add_node("response_generator_agent", response_generator_agent)

workflow.add_conditional_edges(
    "file_processor_agent",
    lambda state: "csv_query_agent" if state.csv_dataframes else "pdf_retrieval_agent",
    {"csv_query_agent": "csv_query_agent", "pdf_retrieval_agent": "pdf_retrieval_agent"}
)
workflow.add_conditional_edges(
    "csv_query_agent",
    lambda state: "response_generator_agent" if state.csv_result else "pdf_retrieval_agent",
    {"response_generator_agent": "response_generator_agent", "pdf_retrieval_agent": "pdf_retrieval_agent"}
)
workflow.add_edge("pdf_retrieval_agent", "response_generator_agent")
workflow.add_edge("response_generator_agent", END)

workflow.set_entry_point("file_processor_agent")
app = workflow.compile()

# === Streamlit Page ===
st.set_page_config(page_title="Multi-Agent RAG Chatbot | PDF + CSV", layout="wide")
st.title("📄 Multi-Agent RAG Chatbot | CSV + PDF | Upload + Summarize + Chat")

# === Sidebar with file listing and delete buttons ===
with st.sidebar:
    st.markdown("### 📂 Uploaded Files")
    existing_files = sorted(f for f in os.listdir(UPLOAD_DIR) if f.endswith((".csv", ".pdf")))
    if existing_files:
        for file in existing_files:
            file_path = os.path.join(UPLOAD_DIR, file)
            with st.form(key=f"delete_form_{file}"):
                st.markdown(f"- `{file}`")
                delete = st.form_submit_button("❌ Delete")
                if delete:
                    os.remove(file_path)
                    st.success(f"{file} deleted.")
                    st.experimental_rerun()
    else:
        st.info("No uploaded files found.")

# === Upload Section ===
st.markdown("<style>.upload-icon { position: absolute; top: 20px; right: 20px; }</style>", unsafe_allow_html=True)
with st.expander("➕ Upload Files", expanded=False):
    uploaded = st.file_uploader("", type=["pdf", "csv"], accept_multiple_files=True, label_visibility="collapsed")
    if uploaded:
        st.session_state.uploaded_files = uploaded
        initial_state = AgentState(query="", csv_dataframes=st.session_state.csv_dataframes)
        app.invoke(initial_state)

# === Chat Input ===
user_input = st.chat_input("Ask a question about your uploaded documents")
if user_input:
    state = AgentState(query=user_input, csv_dataframes=st.session_state.csv_dataframes)
    with st.spinner("Processing query..."):
        result = app.invoke(state)
    answer = result.final_answer
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.chat_history.append({
        "timestamp": timestamp,
        "question": user_input,
        "answer": answer
    })

# === Display Chat ===
for idx, msg in enumerate(st.session_state.chat_history):
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
with col2:
    if st.session_state.chat_history:
        json_data = json.dumps(st.session_state.chat_history, indent=2)
        st.download_button("⬇️ Download Chat Log", json_data, file_name="chat_history.json")