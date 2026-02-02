import re

def apply_row_level_security(sql, perm_map, email, role):
    """
    Applies Row-Level Security (RLS) by injecting WHERE clauses into the SQL.
    Admins and CTOs bypass this layer entirely.
    """
    
    # 1. SECURITY GUARD: Only SELECT allowed
    clean_sql = sql.strip().upper()
    if not clean_sql.startswith("SELECT") and not clean_sql.startswith("WITH"):
        raise PermissionError("Security Block: Only read-only SELECT operations are permitted.")

    # 2. ROLE-BASED BYPASS: Admins and CTOs see all data
    privileged_roles = ["admin", "cto", "manager", "techlead"]
    if role.strip().lower() in privileged_roles:
        return sql

    # 3. Identify tables that require RLS enforcement
    # Condition: CanRead (Read All) is False AND CanReadSelf is True
    rls_tables = set()
    for table, (can_read, can_read_self) in perm_map.items():
        if can_read_self and not can_read:
            rls_tables.add(table)

    # If no tables need RLS, return original SQL
    if not rls_tables:
        return sql

    # 2. Parse SQL to identify which of the RLS tables are actually used, and their aliases.
    # Regex to capture: FROM/JOIN [schema.]Table [AS] Alias
    # This is a basic parser and assumes standard SQL formatting.
    # Group 2: Table Name
    # Group 3: Alias (optional)
    pattern = re.compile(
        r'\b(FROM|JOIN)\s+'
        r'(?:\[?\w+\]?\.)?\[?(\w+)\]?'  # Table Name (e.g. Users or [Users])
        r'(?:\s+(?:AS\s+)?\[?(\w+)\]?)?', # Alias (e.g. u or [u])
        re.IGNORECASE
    )

    conditions = []
    
    # Iterate matches to find active tables
    for match in pattern.finditer(sql):
        table_name = match.group(2)
        alias = match.group(3)
        
        # KEY FIX: Ensure the alias isn't actually a SQL keyword (WHERE, ON, GROUP, etc.)
        reserved_keywords = {"WHERE", "ON", "GROUP", "ORDER", "LIMIT", "INNER", "LEFT", "RIGHT", "JOIN"}
        if alias and alias.upper() in reserved_keywords:
            alias = None
            
        final_alias = alias if alias else table_name
        
        matched_table = next((t for t in rls_tables if t.lower() == table_name.lower()), None)
        
        if matched_table:
            # DYNAMIC COLUMN DETECTION
            col_map = {
                "employees": "Email",
                "attendance": "EmployeeEmail",
                "permissions": "RoleName"
            }
            
            owner_col = col_map.get(matched_table.lower())
            
            # If not in map, we could potentially query the DB schema here, 
            # but for performance we use a sensible default or the map.
            if not owner_col:
                owner_col = "Email" # Standard enterprise convention
            
            if matched_table.lower() == "permissions":
                cond = f"{final_alias}.RoleName = '{role}'"
            else:
                cond = f"{final_alias}.{owner_col} = '{email}'"
            
            conditions.append(cond)

    # If none of the restricted tables are in the query, return original SQL
    if not conditions:
        return sql

    # 3. Inject conditions into the SQL
    full_condition = " AND ".join(conditions)

    # Check for existing WHERE clause
    # We look for the first WHERE. This handles the outermost query in simple cases.
    where_match = re.search(r'\bWHERE\b', sql, re.IGNORECASE)
    
    if where_match:
        # If WHERE exists, we append our conditions with AND.
        # We wrap the injected condition in parenthesis for safety.
        # Strategy: Replace "WHERE" with "WHERE (Injected) AND"
        start, end = where_match.span()
        new_sql = sql[:end] + f" ({full_condition}) AND " + sql[end:]
        return new_sql
    else:
        # No WHERE clause found. We must append one.
        # It must be placed before GROUP BY, ORDER BY, LIMIT, etc.
        # Regex to find the start of these clauses
        eos_keywords = re.search(r'\b(GROUP BY|HAVING|ORDER BY|LIMIT|OFFSET|FOR XML)\b', sql, re.IGNORECASE)
        
        if eos_keywords:
            k_start = eos_keywords.start()
            new_sql = sql[:k_start] + f" WHERE {full_condition} " + sql[k_start:]
            return new_sql
        else:
            # No trailing clauses, just append to end
            return sql + f" WHERE {full_condition}"
