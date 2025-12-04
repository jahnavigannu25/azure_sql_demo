import os, re, json, urllib.parse
from decimal import Decimal
from flask import Flask, request, jsonify, send_from_directory
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool
from dotenv import load_dotenv
from openai import AzureOpenAI
from datetime import datetime

load_dotenv()

app = Flask(__name__, static_folder="static")

# Memory for follow-up answers
LAST_ROWS = {}

# ---------------- Azure OpenAI Client ---------------- #
def get_llm():
    return AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")


# ---------------- Database Engine ---------------- #
def build_engine(db_type, conn_str):
    if db_type in ["azure", "mssql"] and "Driver=" in conn_str:
        return create_engine(
            "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(conn_str),
            poolclass=NullPool,
            future=True,
        )
    return create_engine(conn_str, poolclass=NullPool, future=True)


# ---------------- Convert Decimal ---------------- #
def convert_values(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    return obj


# ---------------- Schema Introspection ---------------- #
def introspect_schema(engine, only_tables=None):
    insp = inspect(engine)
    out = []
    for t in insp.get_table_names():
        if only_tables and t not in only_tables:
            continue
        try:
            cols = insp.get_columns(t)
        except:
            cols = []
        for c in cols:
            out.append({
                "table": t,
                "column": c["name"],
                "type": str(c["type"])
            })
    return out


# ---------------- Extract SQL ---------------- #
def extract_sql(text):
    if "```" in text:
        parts = text.split("```")
        for p in parts:
            if re.search(r"\bselect\b|\bwith\b", p, flags=re.I):
                cleaned = "\n".join(
                    ln for ln in p.splitlines()
                    if not ln.strip().lower().startswith("sql")
                )
                return cleaned.strip()
    return text.strip()


# ---------------- SAFE SQL CHECK ---------------- #
DANGEROUS = re.compile(
    r"\b(insert|update|delete|truncate|drop|alter|create|replace)\b",
    re.I
)

def is_unsafe(sql):
    return bool(DANGEROUS.search(sql))


# ---------------- RUN SQL — FINAL 100% FIXED VERSION ---------------- #
def run_sql(engine, sql, limit=500):
    rows = []
    with engine.connect() as conn:
        result = conn.execute(text(sql))

        if result.returns_rows:

            # FIX: ALWAYS use mappings() to avoid RMKeyView or tuple rows
            for i, row in enumerate(result.mappings()):
                row_dict = {k: convert_values(v) for k, v in row.items()}
                rows.append(row_dict)

                if i + 1 >= limit:
                    break

        else:
            rows.append({"message": f"Affected rows: {result.rowcount}"})

    return rows


# ---------------- FORMAT TABLE ---------------- #
def format_table(rows):
    if not rows:
        return "<p>No data found.</p>"

    def short(x):
        if isinstance(x, str) and len(x) > 12:
            return x[:6] + "…" + x[-4:]
        return x

    def format_date(val):
        if isinstance(val, str) and "T" in val:
            try:
                dt = datetime.fromisoformat(val.replace("Z", ""))
                return dt.strftime("%d-%b-%Y")
            except:
                return val
        return val

    headers = rows[0].keys()

    html = "<table class='nice'><thead><tr>"
    for h in headers:
        html += f"<th>{h}</th>"
    html += "</tr></thead><tbody>"

    for r in rows:
        html += "<tr>"
        for h in headers:
            v = r[h]
            if h.lower() == "bloburl":
                html += f"<td><a href='{v}' target='_blank'>View</a></td>"
            else:
                html += f"<td>{format_date(short(v))}</td>"
        html += "</tr>"

    html += "</tbody></table>"
    return html


# ---------------- BUSINESS BULLET SUMMARY (100% ACCURATE) ---------------- #
def generate_bullet_summary(rows):
    if not rows:
        return "• No records found."

    # ---------------- Detect numeric columns ---------------- #
    numeric_cols = set()
    for r in rows:
        for k, v in r.items():
            try:
                float(v)
                numeric_cols.add(k)
            except:
                pass

    # ---------------- Detect date columns ---------------- #
    date_cols = set()
    for r in rows:
        for k, v in r.items():
            if isinstance(v, str) and ("-" in v or "T" in v):
                try:
                    datetime.fromisoformat(v.replace("Z", ""))
                    date_cols.add(k)
                except:
                    pass

    summary = []

    # ---------------- Latest Date ---------------- #
    for col in date_cols:
        try:
            parsed = [
                datetime.fromisoformat(r[col].replace("Z", ""))
                for r in rows
                if r.get(col)
            ]
            if parsed:
                latest = max(parsed)
                summary.append(
                    f"• Latest value in **{col}**: {latest.strftime('%d-%b-%Y')}."
                )
        except:
            pass

    # ---------------- Numeric Statistics ---------------- #
    for col in numeric_cols:
        try:
            nums = [
                float(r[col])
                for r in rows
                if r.get(col) not in (None, "", "null")
            ]
            if nums:
                avg = sum(nums) / len(nums)
                mx = max(nums)
                mn = min(nums)

                summary.append(
                    f"• Column **{col}** → Avg: {avg:.2f}, Max: {mx:.2f}, Min: {mn:.2f}."
                )
        except:
            pass

    summary.append(f"• Total records analyzed: {len(rows)}.")

    return "\n".join(summary)


# ---------------- FOLLOW-UP DETECTION ---------------- #
def is_followup(question):
    keywords = [
        "which", "what", "when", "highest", "lowest", "average",
        "count", "total", "how many", "summarize", "details"
    ]
    return any(k in question.lower() for k in keywords)


# ---------------- /chat ---------------- #
@app.post("/chat")
def chat():
    data = request.json
    question = data["question"].strip()
    db_type = data["dbType"]
    conn_str = data["connectionString"]
    selected_tables = data.get("selectedTables", [])

    # FOLLOW-UP
    if is_followup(question) and "rows" in LAST_ROWS:
        client = get_llm()

        follow_prompt = f"""
Answer the user's follow-up question using ONLY this data:

{json.dumps(LAST_ROWS['rows'], indent=2, default=str)}

User question:
{question}

Return a clear business-friendly answer.
"""

        try:
            response = client.chat.completions.create(
                model=DEPLOYMENT,
                messages=[{"role": "user", "content": follow_prompt}],
                temperature=0.2
            )
            answer = response.choices[0].message.content

            return jsonify({
                "sql": None,
                "table_html": LAST_ROWS["table_html"],
                "summary": answer
            })

        except Exception as e:
            return jsonify({"error": str(e)})

    # NEW SQL GENERATION
    engine = build_engine(db_type, conn_str)
    schema_rows = introspect_schema(engine, selected_tables)
    schema_text = "\n".join(
        f"{r['table']}.{r['column']} ({r['type']})"
        for r in schema_rows
    )

    client = get_llm()
    prompt = f"""
You are an expert SQL generator. Follow these rules STRICTLY:

1. **Use ONLY the tables and columns listed below. Do NOT assume missing columns.**
2. **Generate a single, valid, fully runnable SQL SELECT query.**
3. **NEVER use INSERT, UPDATE, DELETE, DROP, ALTER, CREATE, TRUNCATE, or REPLACE.**
4. **If the user request cannot be satisfied using ONLY the provided schema, generate the closest possible valid SELECT query.**
5. **Always alias tables clearly if joins are involved.**
6. **If multiple tables are used, ALWAYS specify proper JOIN conditions based on column names.**
7. **Always return SQL inside triple backticks. Nothing else.**
8. **NEVER explain, never add comments, never add natural language. Only return SQL.**
9. **Do NOT hallucinate columns. Only use columns EXACTLY as given.**

AVAILABLE SCHEMA:
{schema_text}

USER QUESTION:
{question}

Return ONLY the SQL inside ```sql codeblock.
"""

    try:
        raw = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1
        ).choices[0].message.content

        sql = extract_sql(raw)
    except Exception as e:
        return jsonify({"error": str(e)})

    if is_unsafe(sql):
        return jsonify({"error": "Unsafe SQL detected", "sql": sql})

    rows = run_sql(engine, sql)
    table_html = format_table(rows)
    summary = generate_bullet_summary(rows)

    LAST_ROWS["rows"] = rows
    LAST_ROWS["table_html"] = table_html

    return jsonify({
        "sql": sql,
        "table_html": table_html,
        "summary": summary
    })


# ---------------- /connect ---------------- #
@app.post("/connect")
def connect():
    data = request.json
    engine = build_engine(data["dbType"], data["connectionString"])

    try:
        with engine.connect():
            pass
    except Exception as e:
        return jsonify({"error": str(e)})

    schema = introspect_schema(engine)
    tables = sorted({row["table"] for row in schema})

    return jsonify({"ok": True, "tables": tables, "schema": schema})


# ---------------- Serve UI ---------------- #
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    app.run(debug=True, port=5000)
