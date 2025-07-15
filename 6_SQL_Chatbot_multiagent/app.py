import streamlit as st
from langgraph.graph import StateGraph, END
from typing import TypedDict, Optional, Any, Dict
from openai import OpenAI
from pathlib import Path
import json
import os
import sqlite3
import logging
import pandas as pd
import csv
import pathlib
import datetime as dt
import functools
from shapely.geometry import Point, Polygon

# ---------- 1. Define State and Constants ----------
client = OpenAI(api_key="sk-proj")
MAX_RETRIES = 3
LOG_PATH = os.getenv("STEP_LOG", "query_log.csv")
MAX_DISPLAY_ROWS = 20
MAX_PREVIEW_ROWS = 20

# Define bus yard polygon from provided GPS points
yard_coords = [
    (33.90569271628536, -118.31175238807698),
    (33.90567242912735, -118.31055159492222),
    (33.90498900267104, -118.30926830452778),
    (33.90410954017733, -118.30927448909796),
    (33.90370429579649, -118.30925946566806),
    (33.90372299942574, -118.31049389062383),
    (33.903750015771855, -118.3114203353168),
    (33.90465609749877, -118.31141532750766),
    (33.90560581044806, -118.31155554617293)
]
YARD_POLYGON = Polygon(yard_coords)

class AgentState(TypedDict, total=False):
    user_query: str
    db_path: str
    data_scope: str
    sql_query: str
    sql_result: Any
    evaluation: str
    schema: dict
    candidate_tables: list[str]
    df_raw: pd.DataFrame
    skip_sql_generation: bool

FEW_SHOTS = [
    ("How many records were loaded today?", "current"),
    ("List columns in the trips table", "metadata"),
    ("Average SOC in 2022 Q4", "historical"),
    ("Forecast charging demand next month", "future"),
    ("What does the bus_vid table do?", "metadata"),
    ("Show GPS positions in the yard", "location"),
    ("give me the last gps points for 10 buses", "location"),
]

# ---------- 2. File Reading and Setup ----------

def read_md(name: str) -> str:
    return Path("/Users/aasimwani/Desktop/prompts/" + name).read_text()

TABLE_SELECTION = read_md("table_selection_heuristics.md")
TABLE_DEFS = read_md("table_definitions.md")
JOIN_KEYS = read_md("join_keys.md")
QUERY_SELECTION = read_md("query_selection.md")
RECENCY_POLICY = read_md("value_recency_policy.md")
GLOBAL_RULES = read_md("global_rules.txt")
BUSINESS_RULES = read_md("business_rules.md")
EXAMPLES = read_md("examples.md")

MEMORY = json.loads(Path("/Users/aasimwani/Desktop/prompts/structured_memory.json").read_text())
DEFAULT_DB_PATH = os.getenv("SQLITE_DB_PATH", "/Users/aasimwani/Downloads/vehicle.db")

if not logging.getLogger("sql_graph").handlers:
    logging.basicConfig(
        filename="sql_graph_debug.log",
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
    )
lg = logging.getLogger("sql_graph")

# ---------- 3. Pipeline Nodes ----------

@functools.lru_cache(maxsize=4)
def _load_schema(db_path: str) -> dict:
    with sqlite3.connect(db_path) as conn:
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        ).fetchall()
        schema = {}
        for (tbl,) in tables:
            cols = [r[1] for r in conn.execute(f"PRAGMA table_info({tbl})")]
            schema[tbl] = cols
    return schema

def schema_loader(state: AgentState) -> dict:
    db_path = state.get("db_path", DEFAULT_DB_PATH)
    if not db_path or not os.path.isfile(db_path):
        lg.error(f"Database file not found: {db_path}")
        return {"schema": {}}
    schema = _load_schema(db_path)
    return {"schema": schema}

def table_selector_agent(state: AgentState) -> dict:
    q_words = set(state["user_query"].lower().split())
    hits = []
    for tbl, cols in state["schema"].items():
        score = 0
        if tbl.lower() in q_words:
            score += 3
        score += sum(col.lower() in q_words for col in cols)
        if score:
            hits.append((score, tbl))
    hits.sort(reverse=True)
    cand = [tbl for _, tbl in hits[:5]] or list(state["schema"].keys())[:3]
    return {"candidate_tables": cand}

def handle_metadata_query(state: AgentState) -> dict:
    query_lower = state["user_query"].lower()
    if "tables" in query_lower and "database" in query_lower:
        tables = list(state["schema"].keys())
        md = "| Table Name |\n|------------|\n" + "\n".join(f"| {t} |" for t in tables)
        return {"sql_result": md, "skip_sql_generation": True}
    if any(kw in query_lower for kw in ["what does", "summarize", "describe"]) and any(tbl.lower() in query_lower for tbl in state["schema"]):
        table_name = next((tbl for tbl in state["schema"] if tbl.lower() in query_lower), None)
        if table_name:
            cols = state["schema"][table_name]
            description = f"The {table_name} table contains: {', '.join(cols)}. It likely stores {table_name.replace('_', ' ').lower()} data."
            return {"sql_result": description, "skip_sql_generation": True}
    return {}

def generate_sql(state: AgentState) -> AgentState:
    if state.get("skip_sql_generation", False):
        return {}
    table_hint = ", ".join(state.get("candidate_tables", [])) or "ALL"
    schema_json = json.dumps(state.get("schema", {}), indent=2)[:4000]
    scope = state.get("data_scope", "unknown")
    scope_rules = {
        "historical": "Add a WHERE clause with tmstmp < CURRENT_DATE for historical data.",
        "current": "Filter for tmstmp >= CURRENT_TIMESTAMP for current data.",
        "future": "Use prediction functions or join with prediction_models table for future values."
    }
    system_prompt = (
        f"{GLOBAL_RULES}\n\n"
        "## Scope Rules\n"
        f"{scope_rules.get(scope, '')}\n"
        "## Table Selection & Query Construction Rules\n"
        f"{TABLE_SELECTION}\n{JOIN_KEYS}\n{QUERY_SELECTION}\n{RECENCY_POLICY}\n\n"
        "## Candidate Tables\n"
        f"{table_hint}\n\n"
        "## Schema JSON\n"
        f"{schema_json}\n\n"
        "You are an autonomous SQLite query planner. For queries about database metadata (e.g., listing tables), use `sqlite_master`. "
        "For descriptive queries about a table's purpose, return a brief summary based on its name and columns, not SQL. "
        "For queries involving GPS positions, location, yard, points, or buses, include lat and lon columns if available. "
        "Return only the SQL query as a single string, no markdown, no commentary."
    )
    user_prompt = (
        f"User query:\n{state['user_query']}\n\n"
        "Write a valid SQLite query or a brief summary if the query asks for a table's purpose."
    )
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
            response_format={"type": "text"}
        )
        output = response.choices[0].message.content.strip()
        output = output.split("Action Input:")[-1].strip() if "Action Input:" in output else output
        output = output.split("```sql")[-1].strip().split("```")[0].strip() if "```sql" in output else output
        if "Action: sql_db_list_tables" in output:
            output = "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';"
        elif any(kw in state["user_query"].lower() for kw in ["what does", "summarize", "describe"]):
            return {"sql_result": output, "skip_sql_generation": True}
        return {"sql_query": output}
    except Exception as e:
        lg.error(f"LLM error: {e}")
        return {"sql_result": f"[LLM ERROR] {e}", "has_error": True}

def validate_sql(state: AgentState) -> Dict[str, Any]:
    if state.get("skip_sql_generation", False):
        return {}
    sql = state.get("sql_query", "")
    if not sql:
        return {"sql_result": "[SQL ERROR] No query provided", "has_error": True}
    try:
        with sqlite3.connect(":memory:") as mem:
            mem.execute(f"EXPLAIN {sql}")
        return {}
    except Exception as e:
        return {"sql_result": f"[SQL ERROR] {e}", "has_error": True}

def execute_sql(state: AgentState) -> Dict[str, Any]:
    if state.get("skip_sql_generation", False):
        return {}
    sql = state.get("sql_query", "")
    db_path = state.get("db_path", DEFAULT_DB_PATH)
    result_df = None
    markdown_preview = ""
    if not os.path.isfile(db_path):
        return {"sql_result": f"[SQL ERROR] file not found → {db_path}", "has_error": True}
    try:
        with sqlite3.connect(db_path) as conn:
            result_df = pd.read_sql_query(sql, conn)
        if "lat" in result_df.columns and "lon" in result_df.columns:
            result_df = result_df.rename(columns={"lat": "latitude", "lon": "longitude"})
        elif "latitude" in result_df.columns and "longitude" in result_df.columns:
            pass
        else:
            preview_df = result_df.head(MAX_DISPLAY_ROWS)
        preview_df = result_df.head(MAX_DISPLAY_ROWS)
        markdown_preview = preview_df.to_markdown(index=False)
        if len(result_df) > MAX_DISPLAY_ROWS:
            markdown_preview += f"\n\n… {len(result_df)-MAX_DISPLAY_ROWS} more rows truncated …"
    except Exception as e:
        return {"sql_result": f"[SQL ERROR] {e}", "has_error": True}
    return {"sql_result": markdown_preview, "df_raw": result_df}

def yard_location_checker(state: AgentState) -> Dict[str, Any]:
    if state.get("skip_sql_generation", False):
        return {}
    df_raw = state.get("df_raw")
    query_lower = state["user_query"].lower()
    scope = state.get("data_scope", "unknown")
    if df_raw is None or not isinstance(df_raw, pd.DataFrame) or scope == "future":
        lg.warning(f"yard_location_checker: Skipping for scope {scope} or invalid df_raw")
        return {}
    if not (("latitude" in df_raw.columns and "longitude" in df_raw.columns) or ("lat" in df_raw.columns and "lon" in df_raw.columns)):
        lg.warning(f"yard_location_checker: Missing latitude/lat or longitude/lon")
        return {}
    if any(kw in query_lower for kw in ["gps_position", "location", "yard", "position", "gps", "points", "gps points", "buses"]):
        lg.info(f"yard_location_checker: Adding location_status for query '{state['user_query']}'")
        if "lat" in df_raw.columns and "lon" in df_raw.columns and "latitude" not in df_raw.columns:
            df_raw = df_raw.rename(columns={"lat": "latitude", "lon": "longitude"})
        df_raw["location_status"] = df_raw.apply(
            lambda row: "inside_yard" if Point(row["longitude"], row["latitude"]).within(YARD_POLYGON) else "in-transit",
            axis=1
        )
        return {"df_raw": df_raw}
    lg.debug(f"yard_location_checker: Skipping location_status for query '{state['user_query']}'")
    return {}

def result_sampler(state: AgentState) -> dict:
    if state.get("skip_sql_generation", False):
        return {}
    df_raw = state.get("df_raw")
    sql_result = state.get("sql_result")
    if isinstance(df_raw, pd.DataFrame):
        if len(df_raw) > MAX_PREVIEW_ROWS:
            preview = df_raw.head(MAX_PREVIEW_ROWS)
            return {"sql_result": preview, "df_preview": preview}
        return {"sql_result": df_raw, "df_preview": df_raw}
    elif isinstance(sql_result, pd.DataFrame) and len(sql_result) > MAX_PREVIEW_ROWS:
        preview = sql_result.head(MAX_PREVIEW_ROWS)
        return {"sql_result": preview, "df_preview": preview}
    return {}

def error_handler(state: AgentState) -> Dict[str, Any]:
    msg = state.get("sql_result", "")
    err = state.get("has_error", False) or str(msg).startswith(("[SQL ERROR]", "[FORMAT ERROR]", "[LLM ERROR]"))
    tries = state.get("retry_count", 0)
    if not err:
        return {}
    lg.error(f"Failed query: {state.get('sql_query', 'N/A')}, Error: {msg}")
    if tries >= MAX_RETRIES:
        query_lower = state.get("user_query", "").lower()
        if any(kw in query_lower for kw in ["what does", "summarize", "describe"]) and any(tbl.lower() in query_lower for tbl in state.get("schema", {})):
            table_name = next((tbl for tbl in state["schema"] if tbl.lower() in query_lower), None)
            if table_name:
                cols = state["schema"][table_name]
                friendly = f"The {table_name} table contains: {', '.join(cols)}. It likely stores {table_name.replace('_', ' ').lower()} data."
            else:
                friendly = "I couldn’t determine the table’s purpose. Please check the table name."
        else:
            friendly = "I couldn’t execute a valid SQL query for your request. Please rephrase or check table/column names."
        return {"evaluation": friendly, "skip_eval": True}
    return {
        "retry_count": tries + 1,
        "route": "sql_generator",
        "has_error": False
    }

def format_result_table(state: AgentState) -> dict:
    query_lower = state.get("user_query", "").lower()
    raw = state.get("sql_result")
    if isinstance(raw, str) and (raw.startswith("|") or any(kw in query_lower for kw in ["tables", "what does", "summarize", "describe"])):
        return {"sql_result": raw}
    if isinstance(raw, pd.DataFrame):
        df = raw
    elif isinstance(raw, str):
        txt = raw.strip()
        if txt.startswith(("[SQL ERROR", "[FORMAT ERROR]", "[LLM ERROR]")):
            return {"sql_result": raw}
        try:
            if (txt.startswith("[") and txt.endswith("]")) or (txt.startswith("{") and txt.endswith("}")):
                df = pd.read_json(io.StringIO(txt))
            else:
                df = pd.read_csv(io.StringIO(txt))
        except Exception as e:
            return {"sql_result": f"[FORMAT ERROR] could not parse text → {e}"}
    else:
        return {"sql_result": str(raw)}
    try:
        preview_df = df.head(MAX_DISPLAY_ROWS)
        md = preview_df.to_markdown(index=False)
        if len(df) > MAX_DISPLAY_ROWS:
            md += f"\n\n… {len(df) - MAX_DISPLAY_ROWS} more rows truncated …"
    except ImportError:
        md = df.head(MAX_DISPLAY_ROWS).to_string(index=False)
    return {"sql_result": md}

def scope_detector(state: AgentState) -> dict:
    query = state["user_query"].lower()
    schema = state["schema"]
    scope_rules = {
        "historical": ["yesterday", "last", "202", "qtr", "quarter", "year"],
        "current": ["today", "now", "current", "present"],
        "future": ["next", "forecast", "predict"]
    }
    for scope, keywords in scope_rules.items():
        if any(kw in query for kw in keywords):
            state["data_scope"] = scope
            break
    else:
        state["data_scope"] = "unknown"
    scope_tables = {
        "historical": ["trip_history", "soc_logs"],
        "current": ["realtime_inservice_dispatch_data"],
        "future": ["prediction_models"],
        "unknown": list(schema.keys())
    }
    filtered_schema = {k: v for k, v in schema.items() if k in scope_tables[state["data_scope"]]}
    return {"schema": filtered_schema, "data_scope": state["data_scope"]}

def evaluate_result(state: AgentState) -> AgentState:
    scope = state.get("data_scope", "unknown")
    scope_context = {
        "historical": "Analyze historical trends based on the data.",
        "current": "Provide insights on current operational status.",
        "future": "Interpret predicted values and their implications."
    }
    system_prompt = (
        "You are an EV-fleet analyst.\n"
        f"{BUSINESS_RULES}\n\n"
        f"## Scope Context\n{scope_context.get(scope, '')}\n"
        "Example Q&A pairs:\n"
        f"{EXAMPLES}\n"
        "Always ground your reasoning in these rules."
    )
    user_prompt = (
        f"User question: {state['user_query']}\n\n"
        f"SQL result:\n{state['sql_result']}\n\n"
        "Answer the user, applying the business rules where relevant."
    )
    try:
        resp = client.chat.completions.create(
            model="gpt-4.1-mini",
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.7,
        )
        return {"evaluation": resp.choices[0].message.content.strip()}
    except Exception as e:
        lg.error(f"Evaluation error: {e}")
        return {"evaluation": f"[EVALUATION ERROR] {e}"}

def log_step(state: AgentState) -> Dict[str, Any]:
    row = {
        "ts": dt.datetime.utcnow().isoformat(),
        "user_query": state["user_query"],
        "sql": state.get("sql_query", ""),
        "row_count": getattr(state.get("df_raw"), "shape", [0])[0] if isinstance(state.get("df_raw"), pd.DataFrame) else None,
        "retry": state.get("retry_count", 0),
    }
    try:
        file_existed = pathlib.Path(LOG_PATH).is_file()
        with open(LOG_PATH, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=row.keys())
            if not file_existed:
                w.writeheader()
            w.writerow(row)
    except Exception as e:
        lg.error(f"Logging error: {e}")
    return {}

def format_router(state: AgentState) -> str:
    query = state["user_query"].lower()
    if any(kw in query for kw in ["show", "list", "table", "rows", "columns", "select", "compare", "top", "group by", "gps_position", "location", "yard", "position", "gps", "points", "gps points", "buses"]):
        return "format_result_table"
    return "log_step"

# ---------- 4. Graph Definition ----------

builder = StateGraph(AgentState)
builder.add_node("schema_loader", schema_loader)
builder.add_node("scope_detector", scope_detector)
builder.add_node("table_selector", table_selector_agent)
builder.add_node("metadata_handler", handle_metadata_query)
builder.add_node("sql_generator", generate_sql)
builder.add_node("validate_sql", validate_sql)
builder.add_node("execute_sql", execute_sql)
builder.add_node("yard_location_checker", yard_location_checker)
builder.add_node("result_sampler", result_sampler)
builder.add_node("error_handler", error_handler)
builder.add_node("format_result_table", format_result_table)
builder.add_node("log_step", log_step)
builder.add_node("evaluate_result", evaluate_result)
builder.set_entry_point("schema_loader")
builder.add_edge("schema_loader", "scope_detector")
builder.add_edge("scope_detector", "table_selector")
builder.add_edge("table_selector", "metadata_handler")
builder.add_conditional_edges(
    "metadata_handler",
    lambda state: "format_result_table" if state.get("skip_sql_generation") else "sql_generator",
    {"format_result_table": "format_result_table", "sql_generator": "sql_generator"}
)
builder.add_edge("sql_generator", "validate_sql")
builder.add_edge("validate_sql", "execute_sql")
builder.add_edge("execute_sql", "yard_location_checker")
builder.add_edge("yard_location_checker", "result_sampler")
builder.add_edge("result_sampler", "error_handler")
def post_error_router(state: AgentState) -> str:
    if state.get("route") == "sql_generator":
        return "sql_generator"
    if state.get("skip_eval"):
        return "log_step"
    return format_router(state)
builder.add_conditional_edges(
    "error_handler",
    post_error_router,
    path_map={
        "sql_generator": "sql_generator",
        "format_result_table": "format_result_table",
        "log_step": "log_step",
    },
)
builder.add_edge("format_result_table", "log_step")
builder.add_edge("log_step", "evaluate_result")
builder.add_edge("evaluate_result", END)
graph = builder.compile()

# ---------- 5. Streamlit Interface ----------

st.title("EV Fleet Query Processor")
st.write("Enter a query about the EV fleet data (e.g., 'Average SOC in 2022 Q4', 'Current GPS positions', 'Forecast charging demand next month').")

# Input query
user_query = st.text_input("Query", key="user_input")

# Button to submit query
if st.button("Submit Query"):
    if user_query:
        st.session_state.user_query = user_query
        # Initialize state with the user query
        initial_state = AgentState(user_query=user_query)
        
        # Execute the graph
        with st.spinner("Processing your query..."):
            final_state = graph.invoke(initial_state)
        
        # Display results
        st.subheader("Results")
        sql_result = final_state.get("sql_result", "No SQL result available.")
        evaluation = final_state.get("evaluation", "No evaluation available.")
        
        if isinstance(sql_result, pd.DataFrame):
            st.write("Query Result:")
            st.dataframe(sql_result)
        elif isinstance(sql_result, str) and sql_result.startswith(("[SQL ERROR", "[FORMAT ERROR", "[LLM ERROR]")):
            st.error(sql_result)
        else:
            st.markdown(sql_result)
        
        if evaluation:
            st.subheader("Analysis")
            st.write(evaluation)
    else:
        st.warning("Please enter a query.")

# Display logs (optional)
if st.checkbox("Show Debug Logs"):
    if os.path.exists("sql_graph_debug.log"):
        with open("sql_graph_debug.log", "r") as f:
            st.text_area("Debug Logs", f.read(), height=200)
    else:
        st.write("No debug logs available yet.")

# Run the app
if __name__ == "__main__":
    st.run()