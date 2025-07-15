"""import streamlit as st
import os
import json
import pandas as pd
from datetime import datetime
from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_openai import OpenAIEmbeddings
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain.chains.combine_documents import create_stuff_documents_chain
from langchain_core.prompts import ChatPromptTemplate
from langchain.chains import create_retrieval_chain
from langchain_community.vectorstores import FAISS
from langchain_community.document_loaders import PyPDFLoader, CSVLoader

# === Directories ===
BASE_DIR = "rag_app_data"
FAISS_DIR = os.path.join(BASE_DIR, "faiss_index")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploaded_docs")
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

# === Auto-load existing vectorstore ===
faiss_index_path = os.path.join(FAISS_DIR, "index.faiss")
faiss_meta_path = os.path.join(FAISS_DIR, "index.pkl")
if os.path.exists(faiss_index_path) and os.path.exists(faiss_meta_path):
    st.session_state.vectors = FAISS.load_local(FAISS_DIR, embedder, allow_dangerous_deserialization=True)

# === Streamlit Page ===
st.set_page_config(page_title="RAG Chatbot | PDF + CSV", layout="wide")
st.title("📄 RAG Chatbot | CSV + PDF | Upload + Summarize + Chat")

# === Sidebar with upload ===
with st.sidebar:
    st.markdown("### 📂 Uploaded Files")
    existing_files = sorted(f for f in os.listdir(UPLOAD_DIR) if f.endswith((".csv", ".pdf")))
    if existing_files:
        for file in existing_files:
            st.markdown(f"- {file}")
    else:
        st.info("No uploaded files found.")

    uploaded = st.file_uploader("➕ Upload PDF or CSV", type=["pdf", "csv"], accept_multiple_files=True)

# === Handle Upload ===
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
                st.markdown(f"### 📊 Summary of `{file.name}`")
                st.dataframe(df.describe(include='all').transpose())
            except Exception as e:
                st.warning(f"Unable to summarize {file.name}: {e}")

    if all_docs:
        splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        chunks = splitter.split_documents(all_docs)
        new_index = FAISS.from_documents(chunks, embedder)

        if st.session_state.vectors:
            st.session_state.vectors.merge_from(new_index)
        else:
            st.session_state.vectors = new_index
        st.session_state.vectors.save_local(FAISS_DIR)
        st.success("✅ Documents processed and indexed.")

# === Chat Input ===
user_input = st.chat_input("Ask a question about your uploaded documents")

if user_input:
    if st.session_state.vectors:
        chain = create_retrieval_chain(
            st.session_state.vectors.as_retriever(),
            create_stuff_documents_chain(llm, prompt),
        )
        with st.spinner("Searching documents and generating answer..."):
            result = chain.invoke({"input": user_input})
        answer = result["answer"]
    else:
        with st.spinner("Using LLM without document context..."):
            result = llm.invoke(user_input)
        answer = result.content if hasattr(result, "content") else str(result)

    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    st.session_state.chat_history.append({
        "timestamp": timestamp,
        "question": user_input,
        "answer": answer
    })

# === Display Chat ===
for msg in st.session_state.chat_history:
    with st.chat_message("user"):
        st.markdown(f"**🕒 {msg['timestamp']}**\n\n{msg['question']}")
    with st.chat_message("assistant"):
        st.markdown(msg["answer"])

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
"""