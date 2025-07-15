import streamlit as st
import os
import json
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv
import re

from langchain_groq import ChatGroq
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains import create_retrieval_chain
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader, CSVLoader, JSONLoader

# === Directories ===
BASE_DIR = "rag_app_data"
FAISS_DIR = os.path.join(BASE_DIR, "faiss_index")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_docs")
os.makedirs(BASE_DIR, exist_ok=True)
os.makedirs(FAISS_DIR, exist_ok=True)
os.makedirs(UPLOAD_DIR, exist_ok=True)

# === Environment ===
load_dotenv()
os.environ['OPENAI_API_KEY'] = os.getenv("OPENAI_API_KEY")
os.environ['GROQ_API_KEY'] = os.getenv("GROQ_API_KEY")

# === LLM & Prompt ===
llm = ChatGroq(groq_api_key=os.environ['GROQ_API_KEY'], model_name="Llama3-8b-8192")
prompt = ChatPromptTemplate.from_template("""
Answer the questions based on the provided context only.
<context>
{context}
</context>
Question: {input}
""")
embedder = OpenAIEmbeddings()

# === Session State ===
if "chat_history" not in st.session_state:
    st.session_state.chat_history = []
if "vectors" not in st.session_state:
    st.session_state.vectors = None
if "csv_dataframes" not in st.session_state:
    st.session_state.csv_dataframes = {}
if "json_dataframes" not in st.session_state:
    st.session_state.json_dataframes = {}

# === Auto-load existing vectorstore ===
faiss_index_path = os.path.join(FAISS_DIR, "index.faiss")
faiss_meta_path = os.path.join(FAISS_DIR, "index.pkl")
if os.path.exists(faiss_index_path) and os.path.exists(faiss_meta_path):
    st.session_state.vectors = FAISS.load_local(FAISS_DIR, embedder, allow_dangerous_deserialization=True)

# === Page Configuration ===
st.set_page_config(page_title="RAG Chatbot | PDF + CSV + JSON", layout="wide")

with st.sidebar:
    st.markdown("## 📁 Uploaded Files")
    existing_files = sorted(f for f in os.listdir(UPLOAD_DIR) if f.endswith((".csv", ".pdf", ".json")))
    if existing_files:
        for file in existing_files:
            file_path = os.path.join(UPLOAD_DIR, file)
            col1, col2 = st.columns([4, 1])
            col1.markdown(f"`{file}`")
            if col2.button("❌", key=f"del_{file}"):
                os.remove(file_path)
                st.success(f"Deleted {file}")
                st.experimental_rerun()
    else:
        st.info("Upload files to begin.")

st.markdown("""
    <style>
    .block-container {
        padding-top: 2rem;
    }
    .stChatInput input {
        font-size: 1.2rem;
    }
    .stDownloadButton button, .stButton button {
        border-radius: 10px;
        padding: 0.6rem 1.2rem;
        font-weight: bold;
    }
    .stExpanderHeader {
        font-weight: bold;
    }
    </style>
""", unsafe_allow_html=True)

st.title("🧠 RAG Chatbot")
st.caption("Chat with your uploaded PDFs, CSVs, and JSON using Llama3")

with st.expander("📤 Upload Files", expanded=True):
    uploaded = st.file_uploader("Upload PDF, CSV or JSON", type=["pdf", "csv", "json"], accept_multiple_files=True)

# === File Handling ===
if uploaded:
    all_docs = []
    for file in uploaded:
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
                st.session_state.csv_dataframes[file.name] = df
                with st.expander(f"📊 `{file.name}` Summary"):
                    st.dataframe(df.describe(include='all').transpose())
            except Exception as e:
                st.warning(f"Couldn't summarize {file.name}: {e}")
        elif file.name.endswith(".json"):
            try:
                df = pd.read_json(path)
                st.session_state.json_dataframes[file.name] = df
                all_docs.append({'page_content': df.to_json(), 'metadata': {'source': file.name}})
                with st.expander(f"🗂️ `{file.name}` Preview"):
                    st.dataframe(df.head())
            except Exception as e:
                st.warning(f"Couldn't load {file.name}: {e}")

    if all_docs:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(all_docs)
        new_index = FAISS.from_documents(chunks, embedder)
        if st.session_state.vectors:
            st.session_state.vectors.merge_from(new_index)
        else:
            st.session_state.vectors = new_index
        st.session_state.vectors.save_local(FAISS_DIR)
        st.success("✅ Documents indexed.")

# === Chat Section ===
st.divider()
st.subheader("💬 Chat")
user_input = st.chat_input("Ask about your documents...")

if user_input:
    answer = ""
    csv_used = False

    for name, df in {**st.session_state.csv_dataframes, **st.session_state.json_dataframes}.items():
        cols_lower = [col.lower() for col in df.columns]
        if any(re.search(col, user_input.lower()) for col in cols_lower):
            try:
                if "sum" in user_input.lower():
                    result = df.sum(numeric_only=True)
                elif "average" in user_input.lower() or "mean" in user_input.lower():
                    result = df.mean(numeric_only=True)
                elif "count" in user_input.lower():
                    result = df.count()
                else:
                    result = df.describe(include='all').transpose()
                answer = f"📊 From `{name}`:\n\n" + result.to_string()
                csv_used = True
                break
            except Exception as e:
                answer = f"Error: {e}"
                csv_used = True
                break

    if not csv_used:
        if st.session_state.vectors:
            chain = create_retrieval_chain(
                st.session_state.vectors.as_retriever(),
                create_stuff_documents_chain(llm, prompt),
            )
            with st.spinner("Searching documents..."):
                result = chain.invoke({"input": user_input})
            answer = result["answer"]
        else:
            with st.spinner("Thinking..."):
                result = llm.invoke(user_input)
            answer = result.content if hasattr(result, "content") else str(result)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.chat_history.append({
        "timestamp": timestamp,
        "question": user_input,
        "answer": answer
    })

# === Display Chat History ===
if st.session_state.chat_history:
    for idx, msg in reversed(list(enumerate(st.session_state.chat_history))):
        with st.chat_message("user"):
            st.markdown(f"**You:** {msg['question']}")
        with st.chat_message("assistant"):
            st.markdown(f"**Bot:** {msg['answer']}")

# === Utility Buttons ===
st.divider()
col1, col2 = st.columns(2)
with col1:
    if st.button("🧹 Clear Chat"):
        st.session_state.chat_history = []
        st.experimental_rerun()
with col2:
    if st.session_state.chat_history:
        history = json.dumps(st.session_state.chat_history, indent=2)
        st.download_button("⬇️ Download Chat Log", history, file_name="chat_history.json")
