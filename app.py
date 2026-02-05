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

# ------------ Load .env ------------
load_dotenv()

app = Flask(__name__, static_folder="static", template_folder="templates")
app.secret_key = os.getenv("FLASK_SECRET", "super_secret_for_sessions")

# ------------ Azure OpenAI ------------
from openai import AzureOpenAI

def get_llm():
    return AzureOpenAI(
        api_key=os.getenv("AZURE_OPENAI_API_KEY"),
        azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION"),
    )

DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")

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

def get_admin_engine():
    return build_engine_from_connstr(os.getenv("ADMIN_DB_CONN"))

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

# ------------ LLM helpers ------------
def extract_sql(text_in):
    """Pull a single runnable SELECT from LLM output inside triple backticks."""
    if "```" in text_in:
        parts = text_in.split("```")
        for p in parts:
            if re.search(r"\bselect\b|\bwith\b", p, flags=re.I):
                cleaned = "\n".join(
                    ln for ln in p.splitlines()
                    if not ln.strip().lower().startswith("sql")
                )
                return cleaned.strip()
    return text_in.strip()

DANGEROUS = re.compile(r"\b(insert|update|delete|truncate|drop|alter|create|replace|merge)\b", re.I)
def is_unsafe(sql):
    return bool(DANGEROUS.search(sql))

def conversational_summary_from_rows(question, rows):
    """
    Balanced conversational + professional summary (2–6 sentences).
    No SQL, no code. Human-readable.
    """
    client = get_llm()
    prompt = f"""
You are a senior data analyst. Write a concise, professional, conversational answer for a business user.

Guidelines:
- 2–6 short sentences, natural tone (balanced: not too casual, not too formal).
- Explain the key figures and context clearly.
- If dates or ranges are evident, mention them simply.
- If the data is empty, say so politely and suggest a likely reason.
- Do NOT include SQL or code.

User question:
{question}

Rows (JSON sample):
{json.dumps(rows, default=str)[:12000]}
"""
    try:
        resp = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{"role":"user","content":prompt}],
            temperature=0.2
        )
        return resp.choices[0].message.content.strip()
    except Exception:
        if not rows:
            return ("I couldn’t find any records for that request. "
                    "We can try a different time range or filter.")
        return ("Here’s a brief summary of the result above. "
                "Tell me if you want this broken down by time, product, or region.")

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
        return "<div class='no-results'>No data found.</div>"

    headers = rows[0].keys()
    html = """
    <div class='result-table-wrap'>
        <table class='result-table'>
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
            if isinstance(val, str) and len(val) > 28:
                val = val[:14] + "…" + val[-10:]
            # Format ISO dates
            try:
                if isinstance(val, str) and "T" in val:
                    dt = datetime.fromisoformat(val.replace("Z", ""))
                    val = dt.strftime("%d-%b-%Y")
            except:
                pass
            html += f"<td>{val}</td>"
        html += "</tr>"
    html += "</tbody></table></div>"
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
        with get_admin_engine().connect() as conn:
            q = """
            SELECT 1
            FROM Users u
            JOIN UserProjectRoles upr ON upr.UserID = u.UserID
            JOIN Roles r ON r.RoleID = upr.RoleID
            WHERE u.Email = :email AND r.RoleName = 'Admin'
            """
            row = conn.execute(text(q), {"email": email}).first()
            if not row:
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
        session["email"] = email
        return redirect(url_for("home"))
    return f"Auth error: {result.get('error_description')}"

@app.get("/logout")
def logout():
    session.clear()
    tenant = TENANT_ID
    post_logout = urllib.parse.quote_plus(os.getenv("POST_LOGOUT_REDIRECT_URI", url_for("login", _external=True)))
    aad_logout = f"https://login.microsoftonline.com/{tenant}/oauth2/v2.0/logout?post_logout_redirect_uri={post_logout}"
    return redirect(aad_logout)

# ========== BASIC PAGES ==========
@app.get("/")
def root():
    if "email" in session:
        return redirect(url_for("home"))
    return render_template("login.html")

@app.get("/home")
@login_required
def home():
    return render_template("home.html", email=session["email"])

@app.get("/chatui")
@login_required
def chatui():
    return send_from_directory("static", "chat.html")

@app.get("/admin")
@admin_required
def admin_page():
    return send_from_directory("static", "admin.html")

# ========== ADMIN DB QUERIES ==========
def get_user_projects_and_roles(email:str):
    sql = """
    SELECT p.ProjectName, r.RoleName
    FROM Users u
    JOIN UserProjectRoles upr ON upr.UserID = u.UserID
    JOIN Projects p ON p.ProjectID = upr.ProjectID
    JOIN Roles r ON r.RoleID = upr.RoleID
    WHERE u.Email = :email
    """
    with get_admin_engine().connect() as conn:
        rows = conn.execute(text(sql), {"email": email}).mappings().all()
        return [{"project": r["ProjectName"], "role": r["RoleName"]} for r in rows]

def get_allowed_tables(email:str, project:str):
    sql = """
    SELECT perm.TableName, perm.CanRead, perm.CanReadSelf, r.RoleName
    FROM Users u
    JOIN UserProjectRoles upr ON upr.UserID = u.UserID
    JOIN Projects p ON p.ProjectID = upr.ProjectID
    JOIN Roles r ON r.RoleID = upr.RoleID
    JOIN Permissions perm ON perm.ProjectID = p.ProjectID AND perm.RoleID = r.RoleID
    WHERE u.Email = :email AND p.ProjectName = :project
    """
    with get_admin_engine().connect() as conn:
        return [dict(x) for x in conn.execute(text(sql), {"email": email, "project": project}).mappings().all()]

def list_project_tables_from_admin(project:str):
    sql = """
    SELECT td.TableName
    FROM TableDirectory td
    JOIN Projects p ON p.ProjectID = td.ProjectID
    WHERE p.ProjectName = :project
    ORDER BY td.TableName
    """
    with get_admin_engine().connect() as conn:
        return [r[0] for r in conn.execute(text(sql), {"project": project}).all()]

# ========== APIs ==========
@app.get("/api/me")
@login_required
def api_me():
    email = session["email"]
    mappings = get_user_projects_and_roles(email)
    return jsonify({"email": email, "projects": mappings})

@app.get("/api/accessible-schema")
@login_required
def api_accessible_schema():
    project = request.args.get("project")
    if not project:
        return jsonify({"error":"project is required"}), 400

    email = session["email"]
    allowed = get_allowed_tables(email, project)
    if not allowed:
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
    perms = get_allowed_tables(email, project)
    if not perms:
        return jsonify({"error":"You do not have access to this project"}), 403

    # map table -> (CanRead, CanReadSelf)
    perm_map = {p["TableName"]: (bool(p["CanRead"]), bool(p["CanReadSelf"])) for p in perms}

    # 2. Identify all available tables from engine
    engine = get_project_engine(project)
    insp = inspect(engine)
    all_engine_tables = insp.get_table_names()

    if not selected_tables:
        return jsonify({
            "error": "✨ **Ready to start?** Please select one or more tables from the sidebar so I can help you with your analysis."
        }), 400

    # 3. Determine tables to show LLM
    # Privileged users see full engine schema for selected tables
    # Restricted users see only what perms allow
    is_privileged = current_role.lower() in ["admin", "cto", "manager", "techlead", "hr"]

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

    # 3) Follow-up answers on cached rows
    if is_followup(question) and "rows" in LAST_ROWS:
        answer = conversational_summary_from_rows(question, LAST_ROWS["rows"])
        return jsonify({
            "sql": None,
            "table_html": LAST_ROWS.get("table_html"),
            "summary": answer
        })

    # 4) Generate SQL with LLM
    client = get_llm()
    prompt = f"""
You are an expert SQL generator.

Rules:
1) Use ONLY these tables/columns:
{schema_text}

2) Generate ONE runnable SELECT (no DML/DDL).
3) Always include table aliases if joining.
4) NEVER use tables not listed.
5) Return the SQL inside triple backticks ONLY.
6) If you need user-specific info (like "my salary"), constrain by user identity column if present:
   - If a table has an Email/UserEmail/Username column, filter by Email = '{email}'.
   - If no such column exists, avoid leaking other people's data.

USER QUESTION:
{question}
"""
    try:
        raw = client.chat.completions.create(
            model=DEPLOYMENT,
            messages=[{"role":"user","content":prompt}],
            temperature=0.1
        ).choices[0].message.content
        sql = extract_sql(raw)
    except Exception as e:
        return jsonify({
            "error": "🧠 **Processing Insight**: I encountered a bit of trouble generating the query. Could you try rephrasing your question or checking the selected tables?"
        }), 500

    # 5) Safety & RBAC
    if is_unsafe(sql) or os.getenv("READ_ONLY","true").lower() == "true" and re.search(r"\b(insert|update|delete|alter|create|truncate|merge|drop)\b", sql, re.I):
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
    if not refs and selected_tables:
        return jsonify({
            "error": "Your question does not match any of the selected tables. Please rephrase or select the correct tables."
        }), 400

    not_allowed = [t for t in refs if t not in perm_map]
    if not_allowed:
        proj_label = project or "this project"
        msg = (
            "🚫 Access denied\n\n"
            f"You do not have permission to access the following tables:\n"
            f"{', '.join(not_allowed)}\n\n"
            "Please contact your administrator if you need access.")
        return jsonify({"error": msg, "sql": sql}), 403

    # 6) Execute
    try:
        rows = run_sql(engine, sql)
    except Exception as e:
        return jsonify({
            "error": "⚙️ **Technical Hiccup**: I ran into an issue while retrieving the data. Please try again in a few moments, or reach out to support if the issue persists."
        }), 500

    table_html = format_table(rows)

    # 7) Conversational summary
    summary = conversational_summary_from_rows(question, rows)

    LAST_ROWS["rows"] = rows
    LAST_ROWS["table_html"] = table_html

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
    with get_admin_engine().connect() as conn:
        users = [dict(x) for x in conn.execute(text("SELECT UserID,Email,Name FROM Users ORDER BY Email")).mappings().all()]
        projects = [dict(x) for x in conn.execute(text("SELECT ProjectID,ProjectName FROM Projects ORDER BY ProjectName")).mappings().all()]
        roles = [dict(x) for x in conn.execute(text("SELECT RoleID,RoleName FROM Roles ORDER BY RoleName")).mappings().all()]
        td = [dict(x) for x in conn.execute(text("""
            SELECT td.ID, p.ProjectName, td.TableName
            FROM TableDirectory td JOIN Projects p ON p.ProjectID = td.ProjectID
            ORDER BY p.ProjectName, td.TableName
        """)).mappings().all()]
    return jsonify({"users": users, "projects": projects, "roles": roles, "tables": td})

# ---- Disable old write endpoints in True Save All mode ----
@app.post("/api/admin/add-user")
@admin_required
def admin_add_user_disabled():
    return jsonify({"error": "This action is disabled in True Save All mode. Use /api/admin/save-all"}), 409

@app.post("/api/admin/grant-role")
@admin_required
def admin_grant_role_disabled():
    return jsonify({"error": "This action is disabled in True Save All mode. Use /api/admin/save-all"}), 409

@app.post("/api/admin/set-permissions-bulk")
@admin_required
def admin_set_permissions_bulk_disabled():
    return jsonify({"error": "This action is disabled in True Save All mode. Use /api/admin/save-all"}), 409

# ---- New atomic Save All ----
@app.post("/api/admin/save-all")
@admin_required
def save_all():
    """
    Payload:
    {
      "user": {"email":"...", "name":"..."},
      "grants": [ {"project":"...", "role":"..."} ],
      "permissions": [
        {"role":"...","project":"...","table":"...","canRead":true,"canReadSelf":false}
      ]
    }
    """
    try:
        data = request.get_json(force=True) or {}
        user = data.get("user")
        grants = data.get("grants", [])
        perms  = data.get("permissions", [])

        # ---- Validation: required fields ----
        if not user or not user.get("email") or not user.get("name"):
            return jsonify({"error": "Please fill the required fields."}), 400

        email = (user["email"] or "").strip().lower()
        name  = (user["name"] or "").strip()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            return jsonify({"error": "Please fill the required fields."}), 400

        for g in grants:
            if not g.get("project") or not g.get("role"):
                return jsonify({"error": "Please fill the required fields."}), 400

        for p in perms:
            if not p.get("role") or not p.get("project") or not p.get("table"):
                return jsonify({"error": "Please fill the required fields."}), 400

        # ---- Transactional Save (atomic) ----
        with get_admin_engine().begin() as conn:
            # 1) Upsert user (UserID is IDENTITY)
            upsert_user_sql = text("""
                IF NOT EXISTS (SELECT 1 FROM Users WHERE Email = :e)
                    INSERT INTO Users(Email, Name) VALUES(:e, :n);
            """)
            conn.execute(upsert_user_sql, {"e": email, "n": name})

            # Update name if already exists (optional, keeps admin edits in sync)
            conn.execute(text("UPDATE Users SET Name=:n WHERE Email=:e"), {"n": name, "e": email})

            # Fetch UserID
            user_id = conn.execute(text("SELECT UserID FROM Users WHERE Email=:e"), {"e": email}).scalar()
            if not user_id:
                raise RuntimeError("Failed to resolve UserID after insert")

            # Utility to map names to IDs
            def get_project_id(project_name: str):
                return conn.execute(text("SELECT ProjectID FROM Projects WHERE ProjectName=:p"),
                                    {"p": project_name}).scalar()

            def get_role_id(role_name: str):
                return conn.execute(text("SELECT RoleID FROM Roles WHERE RoleName=:r"),
                                    {"r": role_name}).scalar()

            # 2) Upsert user grants
            for g in grants:
                pid = get_project_id(g["project"])
                rid = get_role_id(g["role"])
                if not pid or not rid:
                    raise RuntimeError(f"Unknown project/role: {g['project']} / {g['role']}")

                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM UserProjectRoles WHERE UserID=:uid AND ProjectID=:pid
                    )
                        INSERT INTO UserProjectRoles(UserID, ProjectID, RoleID)
                        VALUES(:uid, :pid, :rid)
                    ELSE
                        UPDATE UserProjectRoles SET RoleID=:rid
                        WHERE UserID=:uid AND ProjectID=:pid
                """), {"uid": user_id, "pid": pid, "rid": rid})

            # 3) Upsert role-based permissions
            for p in perms:
                pid = get_project_id(p["project"])
                rid = get_role_id(p["role"])
                if not pid or not rid:
                    raise RuntimeError(f"Unknown project/role in permissions: {p['project']} / {p['role']}")

                can_read = 1 if p.get("canRead") else 0
                can_self = 1 if p.get("canReadSelf") else 0

                conn.execute(text("""
                    IF NOT EXISTS (
                        SELECT 1 FROM Permissions
                        WHERE ProjectID=:pid AND RoleID=:rid AND TableName=:tbl
                    )
                        INSERT INTO Permissions(ProjectID, RoleID, TableName, CanRead, CanReadSelf)
                        VALUES(:pid, :rid, :tbl, :cr, :cs)
                    ELSE
                        UPDATE Permissions
                        SET CanRead=:cr, CanReadSelf=:cs
                        WHERE ProjectID=:pid AND RoleID=:rid AND TableName=:tbl
                """), {"pid": pid, "rid": rid, "tbl": p["table"], "cr": can_read, "cs": can_self})

        return jsonify({"status": "ok", "message": "All changes saved atomically"})

    except Exception as e:
        return jsonify({"error": str(e)}), 500

# --------- (Optional) run local ----------
if __name__ == "__main__":
    # POST_LOGOUT_REDIRECT_URI can be set; defaults to /login
    app.run(debug=True, port=5000)
