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
    "EmployeeDB_Test": "EMPLOYEE_DB_CONN",
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
    # Return both is_admin (current code) and isAdmin (requirement) for safety
    return jsonify({
        "email": email, 
        "name": name, 
        "projects": mappings, 
        "is_admin": is_admin, 
        "isAdmin": is_admin
    })

@app.get("/api/accessible-schema")
@login_required
def api_accessible_schema():
    project = request.args.get("project")
    if not project:
        return jsonify({"error":"project is required"}), 400

    email = session["email"]
    
    # 1. Identify Role
    user_projects = rbac.get_user_projects(email)
    role_info = next((p for p in user_projects if p["project"] == project), None)
    if not role_info:
        return jsonify({"error": "No role in this project"}), 403
    
    current_role = role_info["role"].lower()
    is_privileged = current_role in ["admin", "cto", "manager", "techlead"]

    # 2. Get engine and inspector
    engine = get_project_engine(project)
    insp = inspect(engine)
    all_engine_tables = insp.get_table_names()

    # 3. Determine allowed tables
    if is_privileged:
        # Privileged roles see all tables in the database
        allowed_table_names = sorted(all_engine_tables)
    else:
        # Others see only what is explicitly granted in RBAC
        allowed = rbac.get_allowed_tables(email, project)
        allowed_table_names = sorted({a["TableName"] for a in allowed if a["CanRead"] or a["CanReadSelf"]})

    if not allowed_table_names:
        return jsonify({"tables":[], "schema":[]})

    schema_rows = []
    for t in all_engine_tables:
        if t not in allowed_table_names:
            continue
        try:
            cols = insp.get_columns(t)
        except:
            cols = []
        for c in cols:
            schema_rows.append({"table": t, "column": c["name"], "type": str(c["type"])})
    return jsonify({"tables": allowed_table_names, "schema": schema_rows})

@app.post("/api/chat")
@login_required
def api_chat():
    data = request.json
    question = data.get("question","").strip()
    project = data.get("project")  # required
    selected_tables = data.get("selectedTables", [])

    if not project:
        return jsonify({"error":"project is required"}), 400

    # 1) Get permissions & identify Role
    email = session["email"]
    user_projects = rbac.get_user_projects(email)
    is_admin = rbac.is_admin(email)
    
    # Find the specific role for this project (Case-insensitive & Trimmed)
    project_clean = project.strip().lower()
    current_role_info = next((p for p in user_projects if p["project"].strip().lower() == project_clean), None)
    
    if is_admin:
        current_role = "Admin"
    elif not current_role_info:
        return jsonify({"error":f"You do not have access to project: {project}"}), 403
    else:
        current_role = current_role_info["role"].strip()
    
    perms = rbac.get_allowed_tables(email, project)
    
    # map table -> (CanRead, CanReadSelf)
    perm_map = {p["TableName"]: (bool(p["CanRead"]), bool(p["CanReadSelf"])) for p in perms}

    # 2. Identify all available tables from engine
    engine = get_project_engine(project)
    insp = inspect(engine)
    all_engine_tables = insp.get_table_names()

    if not selected_tables:
        return jsonify({
            "error": "⚠ Please select at least one table before asking your question."
        }), 400

    # 3. Determine tables to show LLM
    # Privileged users see full engine schema for selected tables
    # Restricted users see only what perms allow
    is_privileged = current_role.lower() in ["admin", "cto", "manager", "techlead"]

    schema_rows = []
    for t in all_engine_tables:
        if t not in selected_tables:
            continue
        
        # If not privileged, check if table is in permission map
        if not is_privileged and t not in perm_map:
            continue
            
        try:
            cols = insp.get_columns(t)
        except:
            cols = []
        for c in cols:
            schema_rows.append({"table": t, "column": c["name"], "type": str(c["type"])})
    
    schema_text = "\n".join(f"{r['table']}.{r['column']} ({r['type']})" for r in schema_rows)

    # Handle Greetings & Small Talk
    q_norm = question.lower().strip().replace('?','').replace('!','')
    
    # 3.5) Enterprise Privacy Guard (Intelligent RBAC Enforcement)
    # Check if any selected table has 'CanReadSelf' but NOT 'CanRead' (Global Read)
    restricted_tables = [t for t in selected_tables if t in perm_map and perm_map[t][1] and not perm_map[t][0]]
    
    if restricted_tables and not is_admin:
        user_name = rbac.get_user_name(email)
        q_lower = question.lower()
        
        # Determine if the query is strictly about the logged-in user
        # Check for self-referential keywords or the user's own name/email
        self_keywords = ["my", "me", "mine", "self", "i ", "i'm"]
        is_self_query = any(word in q_lower for word in self_keywords)
        
        if email.lower() in q_lower:
            is_self_query = True
        if user_name and user_name.lower() in q_lower:
            is_self_query = True
            
        # Detect if they are asking about someone ELSE specifically
        # If they mention an email that isn't theirs, or if they don't mention themselves but ask for salary/etc.
        other_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', q_lower)
        if other_emails and any(e != email.lower() for e in other_emails):
            is_self_query = False

        if not is_self_query:
            table_list = ", ".join(restricted_tables)
            return jsonify({
                "error": f"🔒 **Access Restricted**: You are only authorized to view your personal data in: {table_list}. Your query appears to request information about other entities or general data which is not permitted under current policy."
            }), 403

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
        sql = llm_service.generate_sql(schema_text, question, email, current_role)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    # 5) Safety & RBAC
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
        # Separate into 'Deselected' vs 'No Permission'
        deselected = [t for t in not_allowed if t in all_engine_tables and (is_privileged or t in perm_map)]
        no_permission = [t for t in not_allowed if t not in deselected]
        
        if deselected:
            return jsonify({
                "error": f"⚠ **Table Not Selected**: The generated query uses tables you haven't selected: {', '.join(deselected)}. Please select them in the sidebar to include them in your analysis."
            }), 400
            
        if no_permission:
            msg = (
                "🚫 **Access Denied**\n\n"
                f"You do not have permission to access the following tables: {', '.join(no_permission)}\n"
            )
            return jsonify({"error": msg, "sql": sql}), 403

    # Apply Row-Level Security with ROLE awareness
    try:
        sql = apply_row_level_security(sql, perm_map, email, current_role)
    except PermissionError as pe:
        return jsonify({"error": str(pe), "sql": sql}), 403

    # 6) Execute
    try:
        rows = run_sql(engine, sql)
    except Exception as e:
        return jsonify({"error": f"Query failed: {e}", "sql": sql}), 500

    table_html = format_table(rows)

    # 7) Conversational summary
    summary = llm_service.summarize_results(question, rows)

    return jsonify({"sql": sql, "table_html": table_html, "summary": summary})

# ========== ADMIN APIs ==========
@app.get("/api/admin/projects")
@admin_required
def api_admin_projects():
    """Returns all projects from the Projects table."""
    return jsonify(rbac.get_all_projects())

@app.get("/api/admin/tables")
@admin_required
def api_admin_tables():
    """Returns all tables for a specific project using INFORMATION_SCHEMA."""
    project = request.args.get("project")
    if not project:
        return jsonify({"error": "Project name is required"}), 400
    
    try:
        engine = get_project_engine(project)
        with engine.connect() as conn:
            sql = "SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES WHERE TABLE_TYPE='BASE TABLE' ORDER BY TABLE_NAME"
            rows = conn.execute(text(sql)).mappings().all()
            return jsonify([r["TABLE_NAME"] for r in rows])
    except Exception as e:
        return jsonify({"error": f"Could not fetch tables for {project}: {str(e)}"}), 500

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
