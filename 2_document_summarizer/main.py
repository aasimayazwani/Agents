# app.py
import streamlit as st
import json
import pandas as pd

# --- Local file loading (JSON, CSV, PDF) ---
@st.cache_data

def load_json_file(filepath):
    try:
        with open(filepath, 'r') as f:
            return json.load(f)
    except Exception as e:
        st.error(f"Failed to load JSON: {e}")
        return None

def parse_csv_file(filepath):
    try:
        return pd.read_csv(filepath)
    except Exception as e:
        st.error(f"Failed to read CSV: {e}")
        return None

def parse_pdf_file(filepath):
    return "PDF parsing placeholder."  # Extend as needed

# --- Helper for JSON flattening ---
def flatten_json(y):
    out = []
    def flatten(x, name=''):
        if isinstance(x, dict):
            for a in x:
                flatten(x[a], f"{name}{a}_")
        elif isinstance(x, list):
            for i, a in enumerate(x):
                flatten(a, f"{name}{i}_")
        else:
            out.append(f"{name[:-1]}: {x}")
    flatten(y)
    return "\n".join(out)

# --- Dummy LLM Agent ---
class DummyAgent:
    def __init__(self, context_text):
        self.context = context_text

    def run(self, query):
        return f"(Echo) You asked: '{query}'\nContext preview:\n{self.context[:300]}..."

def build_dummy_agent(data_text):
    return DummyAgent(data_text)

# --- Main UI ---
st.set_page_config(page_title="Transit Data Chatbot", layout="centered")
st.title("Transit Data Chatbot")

# Automatically load embedded file (update path as needed)
json_data = load_json_file("getvehicles.json")

if json_data:
    st.success("Loaded embedded transit JSON file.")
    if st.checkbox("Show raw JSON"):
        st.json(json_data)

    flattened_text = flatten_json(json_data)
    agent = build_dummy_agent(flattened_text)

    query = st.text_input("Ask a question about the transit data:")
    if query:
        answer = agent.run(query)
        st.write("Answer:", answer)
else:
    st.error("Failed to load the embedded JSON file. Please check the path.")