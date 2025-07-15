###############################################################################
# app.py – streamlined, hardened version for vehicles.db                      #
# (ChatGPT API + developer‑defined system instructions)                       #
###############################################################################
import unicodedata
from pathlib import Path
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
import streamlit as st
from sqlalchemy import create_engine
import sqlite3
from io import StringIO
from io import BytesIO
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
import pandas as pd
from langchain.agents import create_sql_agent, AgentExecutor
from langchain.agents.agent_toolkits import SQLDatabaseToolkit
from langchain.agents.agent_types import AgentType
from langchain.callbacks import StreamlitCallbackHandler
from langchain.sql_database import SQLDatabase
from langchain_openai import ChatOpenAI
from langchain_community.agent_toolkits.sql.base import create_sql_agent
from langchain_community.agent_toolkits.sql.toolkit import SQLDatabaseToolkit
from langchain_community.utilities import SQLDatabase
from langchain_community.callbacks.streamlit import StreamlitCallbackHandler
from langchain_community.agent_toolkits.sql.prompt import SQL_PREFIX as _LC_SQL_PREFIX

import re
# Attempt to pull LangChain's default SQL prompt so we can append our own.
try:
    from langchain.agents.agent_toolkits.sql.prompt import SQL_PREFIX as _LC_SQL_PREFIX
except Exception:  # Fallback if import path changes
    _LC_SQL_PREFIX = ""


from pathlib import Path


import json

HISTORY_FILE = Path("chat_history.json")

def save_history():
    with open(HISTORY_FILE, "w") as f:
        json.dump(st.session_state["messages"], f)

def load_history():
    if HISTORY_FILE.exists():
        try:
            with open(HISTORY_FILE) as f:
                return json.load(f)
        except json.JSONDecodeError:
            # If file is corrupt or empty, start fresh
            return []
    return []

def load_modular_system_prompt(folder: str = "modular_prompt") -> str:
    """
    Load and concatenate all modular instruction files into one system prompt string.
    Files are read in alphabetical order.
    """
    folder_path = Path(folder)
    if not folder_path.exists():
        raise FileNotFoundError(f"Missing prompt folder: {folder_path}")
    
    parts = []
    for file in sorted(folder_path.glob("*.*")):
        parts.append(file.read_text().strip())
    
    return "\n\n".join(parts)

# Load the final system prompt
def ascii_clean(text: str) -> str:
    """Remove problematic unicode characters from prompts."""
    return (
        unicodedata.normalize("NFKD", text)
        .encode("ascii", errors="ignore")
        .decode("ascii")
    )

SYSTEM_PROMPT = ascii_clean(load_modular_system_prompt())

def extract_markdown_table(markdown_text: str) -> pd.DataFrame | None:
    """Try to extract a DataFrame from a markdown table in a string."""
    lines = markdown_text.strip().splitlines()
    table_lines = [line for line in lines if "|" in line]
    if len(table_lines) >= 2:
        csv_text = "\n".join(
            line.strip().strip("|").replace("|", ",")
            for line in table_lines
            if "---" not in line
        )
        try:
            return pd.read_csv(StringIO(csv_text))
        except Exception:
            return None
    return None

def display_response_with_downloads(response) -> str:
    """Display a response and return the assistant reply content (for chat history)."""
    response_df = None

    if isinstance(response, pd.DataFrame):
        response_df = response
    elif isinstance(response, str):
        response_df = extract_markdown_table(response)

    if response_df is not None:
        # ✅ Cache for future reruns
        st.session_state["last_response_df"] = response_df
        st.dataframe(response_df)

        format_choice = st.radio(
            "📁 Choose download format:",
            options=["CSV", "PDF"],
            horizontal=True,
            index=0,
            key="format_selector",  # persist across reruns
        )

        if format_choice == "CSV":
            st.download_button(
                label="📥 Download as CSV",
                data=response_df.to_csv(index=False).encode("utf-8"),
                file_name="query_result.csv",
                mime="text/csv",
            )
        elif format_choice == "PDF":
            from reportlab.platypus import Image, Spacer
            from reportlab.lib.units import inch

            pdf_buffer = BytesIO()
            doc = SimpleDocTemplate(pdf_buffer, pagesize=letter)

            # ⬇️ Build story with optional logo
            story = []

            # ✅ Add logo at top (adjust path/size)
            logo_path = "logo.png"  # relative or absolute path to your logo file
            try:
                logo = Image(logo_path, width=2.0 * inch, height=1.0 * inch)
                story.append(logo)
                story.append(Spacer(1, 0.25 * inch))
            except Exception as e:
                st.warning(f"⚠️ Could not load logo: {e}")

            # ⬇️ Add table
            data = [response_df.columns.tolist()] + response_df.values.tolist()
            table = Table(data)
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightblue),
                ("GRID", (0, 0), (-1, -1), 1, colors.grey),
                ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ]))

            story.append(table)
            doc.build(story)

            pdf_bytes = pdf_buffer.getvalue()

            st.download_button(
                label="📥 Download as PDF",
                data=pdf_bytes,
                file_name="query_result.pdf",
                mime="application/pdf",
            )


        return "Here is the table you requested. Use the buttons above to download it as CSV or PDF."
    else:
        return response

###############################################################################
# ---------- Developer system instructions -----------------------------------
###############################################################################
FORMAT_INSTRUCTIONS = """
Use the following format in your response:

Thought: Do I need to use a tool? Yes or No.
If Yes:
Action: the action to take, must be one of [sql_db_list_tables, sql_db_schema, sql_db_query]
Action Input: the input to the action

IMPORTANT:
- NEVER output both a Final Answer and an Action block together.
- If you're taking an Action, you must wait for its result before outputting a Final Answer.

If No:
Thought: Do I need to use a tool? No.
Final Answer: the final answer to the original input question.

 Always use the phrase 'Final Answer:' exactly — or the system will throw a parsing error.
"""

def extract_raw_sql(text: str) -> str:
    """Extracts the raw SQL query from markdown-fenced output, or returns raw."""
    #match = re.search(r"```sql\s+(.?)```", text, re.DOTALL | re.IGNORECASE)
    match = re.search(r"```sql\s+(.*?)```", text, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else text.strip()



def is_transit_related(query: str, api_key: str) -> bool:
    """Check if the user's query is related to fleet/transit/dispatch (for OpenAI SDK v1.0+)."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key)

    prompt = (
        "Is the following question about public transportation, electric buses, "
        "transit dispatch, scheduling, or vehicle telematics? Reply with only Yes or No.\n\n"
        f"Question: {query.strip()}"
    )

    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[{"role": "user", "content": prompt}],
            temperature=0,
            max_tokens=5,
        )
        answer = response.choices[0].message.content.strip().lower()
        return "yes" in answer
    except Exception as e:
        st.warning(f"⚠️ Domain check failed: {e}")
        return True  # fallback to allow query
    
###############################################################################
# ---------- Utility helpers --------------------------------------------------
###############################################################################
DB_FILE = Path(__file__).parent / "vehicles.db"

def ascii_sanitise(value: str) -> str:
    """Return a strictly-ASCII version of `value`."""
    return (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", errors="ignore")
        .decode("ascii")
    )

def convert_to_message_history(messages):
    from langchain_core.messages import AIMessage, HumanMessage

    history = []
    for msg in messages:
        if msg["role"] == "user":
            history.append(HumanMessage(content=msg["content"]))
        elif msg["role"] == "assistant":
            history.append(AIMessage(content=msg["content"]))
    return history

###############################################################################
# ---------- Streamlit sidebar (API key only) ---------------------------------
###############################################################################
st.set_page_config(page_title="LangChain • Vehicles DB", page_icon="🚌")
st.title("🚌 Chat with Vehicles Database")

# Try to fetch OpenAI API key from secrets first
api_key_raw = st.secrets.get("OPENAI_API_KEY", "")

# If not set, fallback to user prompt
if not api_key_raw:
    api_key_raw = st.sidebar.text_input("🔐 Enter OpenAI API Key", type="password")

api_key = ascii_sanitise(api_key_raw or "")

# Stop if no key is present at all
if not api_key:
    st.warning("OpenAI API key not found. Please add it to Streamlit secrets or enter it above.")
    st.stop()
st.session_state.setdefault("messages", load_history())
###############################################################################
# ---------- Configure DB connection (cached, auto-invalidated) --------------
###############################################################################
@st.cache_resource(ttl=0)
def get_db_connection(db_path: Path, api_key_ascii: str):
    """Return (SQLDatabase, ChatOpenAI LLM) tuple."""
    if not db_path.exists():
        raise FileNotFoundError(f"Database file not found at: {db_path}")

    st.session_state["_db_mtime"] = db_path.stat().st_mtime  # refresh on change

    from sqlalchemy.pool import StaticPool

    # ⬇️ Open in read-only mode so no accidental writes occur
    creator = lambda: sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    engine = create_engine(
        "sqlite://",
        creator=creator,
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    sql_db = SQLDatabase(engine)

    llm = ChatOpenAI(
        openai_api_key=api_key_ascii,
        model_name="gpt-4.1-mini",
        #model_name="o4-mini",
        #model_name="o4-mini",
        streaming=True,
        temperature=0.5
    )

    return sql_db, llm


db, llm = get_db_connection(DB_FILE, api_key)

###############################################################################
# ---------- Capture baseline tables -----------------------------------------
###############################################################################
if "base_tables" not in st.session_state:
    with sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True) as _conn:
        st.session_state["base_tables"] = {
            row[0] for row in _conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table';"
            )
        }

###############################################################################
# ---------- LangChain agent with custom prompt ------------------------------
###############################################################################
toolkit = SQLDatabaseToolkit(db=db, llm=llm)
# custom_prefix = SYSTEM_INSTRUCTIONS.strip() + "\n\n" + _LC_SQL_PREFIX
#escaped_system_instructions = SYSTEM_INSTRUCTIONS.replace("{", "{{").replace("}", "}}")
escaped_system_instructions = SYSTEM_PROMPT.replace("{", "{{").replace("}", "}}")


custom_prefix = (
    escaped_system_instructions.strip()
    + "\n\n"
    + FORMAT_INSTRUCTIONS.strip()
    + "\n\n"
    + _LC_SQL_PREFIX.strip()
)



prompt = ChatPromptTemplate.from_messages([
    ("system", escaped_system_instructions),
    ("system", FORMAT_INSTRUCTIONS),
    ("system", _LC_SQL_PREFIX),
    ("system", "You can use the following tools:\n{tools}"),
    ("system", "Tool names: {tool_names}"),
    MessagesPlaceholder("history"),  # ✅ keep this!
    ("human", "{input}"),
    ("ai", "{agent_scratchpad}")
])

_base_agent = create_sql_agent(
    llm=llm,
    toolkit=toolkit,
    prompt=prompt,  # ✅ Now fully compatible
    agent_type=AgentType.ZERO_SHOT_REACT_DESCRIPTION,
    verbose=True,
)

agent = AgentExecutor.from_agent_and_tools(
    agent=_base_agent.agent,
    tools=toolkit.get_tools(),
    handle_parsing_errors=True,
    return_intermediate_steps=True,
    verbose=True,
    max_iterations=50,         # Adjust this as needed
    max_execution_time=100,    # In seconds
)

###############################################################################
# ---------- Table Download UI (new tables only) -----------------------------
###############################################################################
#st.sidebar.markdown("### 📥 Download new Table as CSV")

with sqlite3.connect(f"file:{DB_FILE}?mode=ro", uri=True) as _conn:
    current_tables = {
        row[0] for row in _conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table';"
        )
    }

###############################################################################
# ---------- Chat UI & session history ---------------------------------------
###############################################################################
if (
    "messages" not in st.session_state
    or st.button("🗑️ Clear chat history", help="Start a fresh session")
):
    st.session_state.messages = [
        {
            "role": "assistant",
            "content": (
                "Hi there – ask me anything about the vehicles.db tables. "
            ),
        }
    ]

for msg in st.session_state.messages:
    st.chat_message(msg["role"]).write(msg["content"])

user_query = st.chat_input("Ask a question…")

if user_query:
    user_query = unicodedata.normalize("NFKD", user_query).encode("ascii", errors="ignore").decode("ascii")
    st.chat_message("user").write(user_query)
    st.session_state.messages.append({"role": "user", "content": user_query})
    save_history()

    with st.chat_message("assistant"):
        cb = StreamlitCallbackHandler(st.container())
        try:
            history = convert_to_message_history(st.session_state.messages)

            # Run the agent with full trace
            response = agent.invoke(
                {
                    "input": user_query,
                    "history": history
                },
                callbacks=[cb]
            )

            # --- Extract assistant's reply ---
            #assistant_reply = response.get("output", response) if isinstance(response, dict) else response
            #chat_reply = display_response_with_downloads(assistant_reply)
            # Extract steps + output
            intermediate_steps = response.get("intermediate_steps", []) if isinstance(response, dict) else []
            assistant_reply = response.get("output", response) if isinstance(response, dict) else response
            chat_reply = display_response_with_downloads(assistant_reply)

            # 🧠 Display chain of thought if available
            if intermediate_steps:
                with st.expander("🧠 Agent Chain of Thought", expanded=False):
                    for i, (action, observation) in enumerate(intermediate_steps):
                        st.markdown(f"**Step {i+1}:**")
                        st.markdown(f"- **Thought**: {action.log.strip()}")
                        st.markdown(f"- **Tool Used**: `{action.tool}`")
                        st.markdown(f"- **Input**: `{action.tool_input}`")
                        st.markdown(f"- **Observation**: `{observation}`")


        except UnicodeEncodeError:
            chat_reply = (
                "⚠️ I encountered a Unicode encoding issue while talking to the LLM. "
                "Please try rephrasing your question using plain ASCII characters."
            )
        except Exception as e:
            chat_reply = f"⚠️ Something went wrong:\n\n`{e}`"

        st.write(chat_reply)

        # Always store assistant reply as a string (not dict or DataFrame)
        st.session_state.messages.append({"role": "assistant", "content": str(chat_reply)})
        save_history()

if not user_query and "last_response_df" in st.session_state:
    st.write("📌 Here's your previous result:")
    display_response_with_downloads(st.session_state["last_response_df"])