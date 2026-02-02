import os, re, json, urllib.parse
from decimal import Decimal
from datetime import datetime
from functools import wraps

from flask import Flask, request, jsonify, send_from_directory, session, redirect, url_for, render_template
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.pool import NullPool
from sqlalchemy.exc import IntegrityError
from dotenv import load_dotenv
import msal

from services.rbac_service import rbac
from services.row_security import apply_row_level_security
from services.llm_service import llm_service

# ------------ Load .env ------------
load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET", "super_secret_for_sessions")

# ------------ MSAL (Entra) ------------
CLIENT_ID = os.getenv("CLIENT_ID")
CLIENT_SECRET = os.getenv("CLIENT_SECRET")
TENANT_ID = os.getenv("TENANT_ID")
AUTHORITY = f"https://login.microsoftonline.com/{TENANT_ID}"
REDIRECT_URI = os.getenv("REDIRECT_URI")
SCOPE = ["User.Read"]

def _msal_app(cache=None):
    return msal.ConfidentialClientApplication(
        CLIENT_ID, authority=AUTHORITY,
        client_credential=CLIENT_SECRET, token_cache=cache
    )

# ------------ DB connection helpers ------------
def build_engine_from_connstr(conn_str: str):
    # Always use pyodbc ODBC string format for SQL Server
    if "Driver=" in conn_str:
        return create_engine(
            "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(conn_str),
            poolclass=NullPool, future=True
        )
    return create_engine(conn_str, poolclass=NullPool, future=True)

PROJECT_TO_CONN_ENV = {
    "Billio": "BILLIO_DB_CONN",
    "Sales":  "SALES_DB_CONN"
}

def get_project_engine(project_name: str):
    env_key = PROJECT_TO_CONN_ENV.get(project_name)
    if not env_key:
        raise ValueError(f"No connection configured for project: {project_name}")
    conn = os.getenv(env_key)
    if not conn:
        raise ValueError(f"Missing env for {env_key}")
    return build_engine_from_connstr(conn)

# ------------ Safe conversions ------------
def convert_values(obj):
    if isinstance(obj, Decimal):
        return float(obj)
    return obj

# ------------ SQL execution + table render ------------
def run_sql(engine, sql, limit=500):
    rows = []
    with engine.connect() as conn:
        result = conn.execute(text(sql))
        if result.returns_rows:
            for i, row in enumerate(result.mappings()):
                row_dict = {k: convert_values(v) for k, v in row.items()}
                rows.append(row_dict)
                if i + 1 >= limit:
                    break
        else:
            rows.append({"message": f"Affected rows: {result.rowcount}"})
    return rows

def format_table(rows):
    if not rows:
        return ""

    headers = rows[0].keys()
    html = """
    <table class="premium-data-table">
        <thead>
            <tr>
    """
    for h in headers:
        html += f"<th>{h}</th>"
    html += "</tr></thead><tbody>"

    for r in rows:
        html += "<tr>"
        for h in headers:
            val = r[h]
            # Format long strings
            if isinstance(val, str) and len(val) > 50:
                val = val[:47] + "..."
            # Format ISO dates
            try:
                if isinstance(val, str) and "T" in val:
                    dt = datetime.fromisoformat(val.replace("Z", ""))
                    val = dt.strftime("%d %b, %Y")
            except:
                pass
            html += f"<td>{val}</td>"
        html += "</tr>"
    html += "</tbody></table>"
    return html

# ========== SESSION / AUTH GUARDS ==========
def login_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if "email" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return inner

def admin_required(f):
    @wraps(f)
    def inner(*args, **kwargs):
        if "email" not in session:
            return redirect(url_for("login"))
        email = session["email"]
        if not rbac.is_admin(email):
             return "Access denied (Admin only)", 403
        return f(*args, **kwargs)
    return inner

# ========== MSAL ROUTES ==========
@app.get("/login")
def login():
    auth_url = _msal_app().get_authorization_request_url(SCOPE, redirect_uri=REDIRECT_URI)
    return redirect(auth_url)

@app.get("/getAToken")
def getAToken():
    if "code" not in request.args:
        return "Login failed"
    result = _msal_app().acquire_token_by_authorization_code(
        request.args["code"], scopes=SCOPE, redirect_uri=REDIRECT_URI
    )
    if "access_token" in result:
        email = result["id_token_claims"].get("preferred_username") or result["id_token_claims"].get("upn")
        
        # Domain Restriction
        if not email or not email.lower().endswith("@ariqt.com"):
            return "Access denied. Only @ariqt.com accounts are allowed.", 403
            
        session["email"] = email
        return redirect(url_for("chatui")) # Direct to chat
    return f"Auth error: {result.get('error_description')}"

@app.get("/logout")
def logout():
    session.clear()
    tenant = TENANT_ID
    post_logout = urllib.parse.quote_plus(os.getenv("POST_LOGOUT_REDIRECT_URI", url_for("login", _external=True)))
    aad_logout = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/logout?post_logout_redirect_uri={post_logout}"
    return redirect(aad_logout)

@app.get("/logo.svg")
def serve_logo():
    return send_from_directory("static", "logo.svg")

# ========== BASIC PAGES ==========
@app.get("/")
def root():
    if "email" in session:
        return redirect(url_for("chatui"))
    return render_template("login.html")

@app.get("/home")
@login_required
def home():
    # Deprecated dashboard, strictly for legacy if needed, but we prefer chatui
    return render_template("home.html", email=session["email"])

@app.get("/chatui")
@login_required
def chatui():
    return send_from_directory("static", "chat.html")

@app.get("/admin")
@admin_required
def admin_page():
    return send_from_directory("static", "admin.html")

# ========== APIs ==========
@app.get("/api/me")
@login_required
def api_me():
    email = session["email"]
    name = rbac.get_user_name(email)
    mappings = rbac.get_user_projects(email)
    is_admin = rbac.is_admin(email)
    return jsonify({"email": email, "name": name, "projects": mappings, "is_admin": is_admin})

@app.get("/api/accessible-schema")
@login_required
def api_accessible_schema():
    project = request.args.get("project")
    if not project:
        return jsonify({"error":"project is required"}), 400

    email = session["email"]
    allowed = rbac.get_allowed_tables(email, project)
    if not allowed:
        return jsonify({"error": "No role in this project"}), 403

    allowed_table_names = sorted({a["TableName"] for a in allowed if a["CanRead"] or a["CanReadSelf"]})
    if not allowed_table_names:
        return jsonify({"tables":[], "schema":[]})

    engine = get_project_engine(project)
    insp = inspect(engine)
    schema_rows = []
    for t in insp.get_table_names():
        if t not in allowed_table_names:
            continue
        try:
            cols = insp.get_columns(t)
        except:
            cols = []
        for c in cols:
            schema_rows.append({"table": t, "column": c["name"], "type": str(c["type"])})
    return jsonify({"tables": allowed_table_names, "schema": schema_rows})

LAST_ROWS = {}
def is_followup(question):
    keywords = ["which","what","when","highest","lowest","average","count","total","how many","summarize","details"]
    return any(k in question.lower() for k in keywords)

@app.post("/api/chat")
@login_required
def api_chat():
    data = request.json
    question = data.get("question","").strip()
    project = data.get("project")  # required
    selected_tables = data.get("selectedTables", [])

    if not project:
        return jsonify({"error":"project is required"}), 400

    # 1) Get permissions
    email = session["email"]
    perms = rbac.get_allowed_tables(email, project)
    if not perms:
        return jsonify({"error":"You do not have access to this project"}), 403

    # map table -> (CanRead, CanReadSelf)
    perm_map = {p["TableName"]: (bool(p["CanRead"]), bool(p["CanReadSelf"])) for p in perms}

    # 2) Load schema limited to allowed tables
    engine = get_project_engine(project)
    insp = inspect(engine)

    if not selected_tables:
        return jsonify({
            "error": "⚠ Please select at least one table before asking your question."
        }), 400

    schema_rows = []
    for t in insp.get_table_names():
        if t not in selected_tables:
            continue
        if t not in perm_map:
            continue
        try:
            cols = insp.get_columns(t)
        except:
            cols = []
        for c in cols:
            schema_rows.append({"table": t, "column": c["name"], "type": str(c["type"])})
    schema_text = "\n".join(f"{r['table']}.{r['column']} ({r['type']})" for r in schema_rows)

    # 3) Follow-up answers on cached rows
    if is_followup(question) and "rows" in LAST_ROWS:
        answer = llm_service.summarize_results(question, LAST_ROWS["rows"])
        return jsonify({
            "sql": None,
            "table_html": LAST_ROWS.get("table_html"),
            "summary": answer
        })

    # Handle Greetings & Small Talk
    q_norm = question.lower().strip().replace('?','').replace('!','')
    
    conversational_intents = {
        "hi": "Hello! Ready to dive into your data?",
        "hello": "Hi there! What can I help you analyze today?",
        "hey": "Hey! I'm listening.",
        "good morning": "Good morning! Let's get to work.",
        "how are you": "I'm functioning perfectly and ready to run some queries for you! How can I help?",
        "who are you": "I am your AI Data Assistant, designed to help you query and understand your Azure SQL data securely.",
        "what can you do": "I can query your database, summarize results, and help you find insights in tables like " + (", ".join(selected_tables[:3]) if selected_tables else "your project tables") + ".",
        "thanks": "You're welcome! Let me know if you need anything else.",
        "thank you": "You're welcome! Happy to help."
    }

    if q_norm in conversational_intents:
        name = rbac.get_user_name(email) or ""
        msg = conversational_intents[q_norm]
        if name and "Hello" in msg:
            msg = msg.replace("Hello!", f"Hello {name}!")
        
        return jsonify({
            "sql": None, 
            "table_html": "",
            "summary": msg
        })

    # 4) Generate SQL with LLM Service
    try:
        sql = llm_service.generate_sql(schema_text, question, email)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 5) Safety & RBAC
    if llm_service.is_unsafe(sql) or os.getenv("READ_ONLY","true").lower() == "true" and re.search(r"\b(insert|update|delete|alter|create|truncate|merge|drop)\b", sql, re.I):
        return jsonify({"error":"Unsafe or non-read query blocked", "sql": sql}), 400

    # Ensure referenced tables are permitted
    referenced = set(re.findall(r"\bfrom\s+([a-zA-Z0-9_\.\[\]]+)|\bjoin\s+([a-zA-Z0-9_\.\[\]]+)", sql, flags=re.I))
    refs = set([p for tup in referenced for p in tup if p])
    def clean_name(n):
        n = n.strip("[]")
        n = n.split()[0]
        if "." in n:
            n = n.split(".")[-1]
        return n
    refs = {clean_name(x) for x in refs}
    
    # Strictly validate against schema_rows logic (selected + permitted)
    valid_tables = {r['table'] for r in schema_rows}
    not_allowed = [t for t in refs if t not in valid_tables]
    
    if not_allowed:
        # Check if it is an alias issue or subquery. 
        # For simplicity, if table is not in valid_tables, block it.
        # But some SQL generators use CTEs or Aliases that look like tables. 
        # We'll rely on the RBAC check as primary gate.
        
        # Real RBAC check:
        real_not_allowed = [t for t in not_allowed if t not in perm_map]
        if real_not_allowed:
            msg = (
                "🚫 Access denied\n\n"
                f"You do not have permission to access the following tables: {', '.join(real_not_allowed)}\n"
            )
            return jsonify({"error": msg, "sql": sql}), 403

    # Apply Row-Level Security
    sql = apply_row_level_security(sql, perm_map, email)

    # 6) Execute
    try:
        rows = run_sql(engine, sql)
    except Exception as e:
        return jsonify({"error": f"Query failed: {e}", "sql": sql}), 500

    table_html = format_table(rows)

    # 7) Conversational summary
    summary = llm_service.summarize_results(question, rows)

    LAST_ROWS["rows"] = rows
    LAST_ROWS["table_html"] = table_html

    return jsonify({"sql": sql, "table_html": table_html, "summary": summary})

# ========== ADMIN APIs ==========
@app.get("/api/admin/bootstrap")
@admin_required
def admin_bootstrap():
    return jsonify(rbac.get_bootstrap_data())

@app.get("/api/admin/role-permissions")
@admin_required
def admin_role_permissions():
    project = request.args.get("project")
    role = request.args.get("role")
    if not project or not role:
        return jsonify({"error": "Missing project or role"}), 400
    perms = rbac.get_project_role_permissions(project, role)
    return jsonify(perms)

@app.post("/api/admin/assign-user")
@admin_required
def api_admin_assign_user():
    """
    Assign a user to one or more projects with specific roles.
    Payload: { "email": "...", "name": "...", "grants": [ {"project": "...", "role": "..."} ] }
    """
    try:
        data = request.json
        rbac.assign_user_role(data.get("email"), data.get("name"), data.get("grants", []))
        return jsonify({"status": "ok", "message": "User assigned successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/admin/update-permissions")
@admin_required
def api_admin_update_permissions():
    """
    Update permissions for a specific Role in a specific Project.
    Payload: { "role": "...", "project": "...", "permissions": [ {"table": "...", "canRead": true, ...} ] }
    """
    try:
        data = request.json
        rbac.update_role_permissions(data.get("role"), data.get("project"), data.get("permissions", []))
        return jsonify({"status": "ok", "message": "Permissions updated successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.post("/api/admin/delete-user")
@admin_required
def api_admin_delete_user():
    """
    Delete a user.
    Payload: { "email": "..." }
    """
    try:
        data = request.json
        rbac.delete_user(data.get("email"))
        return jsonify({"status": "ok", "message": "User deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --------- (Optional) run local ----------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
