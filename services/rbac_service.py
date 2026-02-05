import os
import re
from sqlalchemy import text, create_engine
from sqlalchemy.pool import NullPool
import urllib.parse
from dotenv import load_dotenv

load_dotenv()

class RBACService:
    def __init__(self):
        self._engine = None

    @property
    def engine(self):
        if not self._engine:
            conn_str = os.getenv("ADMIN_DB_CONN")
            if not conn_str:
                raise ValueError("ADMIN_DB_CONN not set")
            
            if "Driver=" in conn_str:
                 self._engine = create_engine(
                    "mssql+pyodbc:///?odbc_connect=" + urllib.parse.quote_plus(conn_str),
                    poolclass=NullPool, future=True
                )
            else:
                self._engine = create_engine(conn_str, poolclass=NullPool, future=True)
        return self._engine

    def is_admin(self, email: str) -> bool:
        """Check if user has global admin role or specific admin role."""
        if not email: return False
        with self.engine.connect() as conn:
            # Check for explicit 'Admin' role in ANY project or a global admin flag if you had one.
            # For now, we stick to the project-based check: is there a role named 'Admin' assigned to this user?
            q = """
            SELECT 1
            FROM Users u
            JOIN UserProjectRoles upr ON upr.UserID = u.UserID
            JOIN Roles r ON r.RoleID = upr.RoleID
            WHERE u.Email = :email AND r.RoleName = 'Admin'
            """
            return bool(conn.execute(text(q), {"email": email}).first())

    def get_user_projects(self, email: str):
        """Get list of projects and roles for a user."""
        sql = """
        SELECT p.ProjectName, r.RoleName
        FROM Users u
        JOIN UserProjectRoles upr ON upr.UserID = u.UserID
        JOIN Projects p ON p.ProjectID = upr.ProjectID
        JOIN Roles r ON r.RoleID = upr.RoleID
        WHERE u.Email = :email
        """
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), {"email": email}).mappings().all()
            return [{"project": r["ProjectName"], "role": r["RoleName"]} for r in rows]

    def get_allowed_tables(self, email: str, project_name: str):
        """Get accessible tables for a user in a project."""
        sql = """
        SELECT perm.TableName, perm.CanRead, perm.CanReadSelf, r.RoleName
        FROM Users u
        JOIN UserProjectRoles upr ON upr.UserID = u.UserID
        JOIN Projects p ON p.ProjectID = upr.ProjectID
        JOIN Roles r ON r.RoleID = upr.RoleID
        JOIN Permissions perm ON perm.ProjectID = p.ProjectID AND perm.RoleID = r.RoleID
        WHERE u.Email = :email AND p.ProjectName = :project
        """
        with self.engine.connect() as conn:
            return [dict(x) for x in conn.execute(text(sql), {"email": email, "project": project_name}).mappings().all()]

    def get_bootstrap_data(self):
        """Fetch all metadata for Admin UI."""
        with self.engine.connect() as conn:
            users = [dict(x) for x in conn.execute(text("SELECT UserID,Email,Name FROM Users ORDER BY Email")).mappings().all()]
            projects = [dict(x) for x in conn.execute(text("SELECT ProjectID,ProjectName FROM Projects ORDER BY ProjectName")).mappings().all()]
            roles = [dict(x) for x in conn.execute(text("SELECT RoleID,RoleName FROM Roles ORDER BY RoleName")).mappings().all()]
            td = [dict(x) for x in conn.execute(text("""
                SELECT td.ID, p.ProjectName, td.TableName
                FROM TableDirectory td JOIN Projects p ON p.ProjectID = td.ProjectID
                ORDER BY p.ProjectName, td.TableName
            """)).mappings().all()]
        return {"users": users, "projects": projects, "roles": roles, "tables": td}

    def get_project_role_permissions(self, project_name: str, role_name: str):
        """Get permissions for a specific role in a project."""
        sql = """
        SELECT perm.TableName, perm.CanRead, perm.CanReadSelf
        FROM Permissions perm
        JOIN Projects p ON p.ProjectID = perm.ProjectID
        JOIN Roles r ON r.RoleID = perm.RoleID
        WHERE p.ProjectName = :p AND r.RoleName = :r
        """
        with self.engine.connect() as conn:
            return [dict(x) for x in conn.execute(text(sql), {"p": project_name, "r": role_name}).mappings().all()]

    def assign_user_role(self, email: str, name: str, grants: list):
        """
        Create/Update user and assign roles to projects.
        This does NOT touch the Permissions table.
        """
        if not email or not name: raise ValueError("Email and Name required")
        
        # Domain Restriction
        if not email.lower().endswith("@ariqt.com"):
            raise ValueError("Only @ariqt.com emails are allowed")
        
        with self.engine.begin() as conn:
            # 1. Upsert User
            conn.execute(text("""
                IF NOT EXISTS (SELECT 1 FROM Users WHERE Email = :e)
                    INSERT INTO Users(Email, Name) VALUES(:e, :n);
            """), {"e": email, "n": name})
            
            # Update name
            conn.execute(text("UPDATE Users SET Name=:n WHERE Email=:e"), {"n": name, "e": email})
            
            user_id = conn.execute(text("SELECT UserID FROM Users WHERE Email=:e"), {"e": email}).scalar()
            
            # 2. Assign Roles
            for g in grants:
                project = g.get("project")
                role = g.get("role")
                
                pid = conn.execute(text("SELECT ProjectID FROM Projects WHERE ProjectName=:p"), {"p": project}).scalar()
                rid = conn.execute(text("SELECT RoleID FROM Roles WHERE RoleName=:r"), {"r": role}).scalar()
                
                if not pid or not rid:
                    raise ValueError(f"Invalid Project '{project}' or Role '{role}'")

                # Validation: Only one CEO or CTO per project
                if role in ["CEO", "CTO"]:
                    existing = conn.execute(text("""
                        SELECT u.Name FROM UserProjectRoles upr
                        JOIN Roles r ON r.RoleID = upr.RoleID
                        JOIN Users u ON u.UserID = upr.UserID
                        WHERE upr.ProjectID=:pid AND r.RoleName=:r AND u.UserID != :uid
                    """), {"pid": pid, "r": role, "uid": user_id}).scalar()
                    if existing:
                        raise ValueError(f"Project '{project}' already has a {role}: {existing}")
                
                conn.execute(text("""
                    IF NOT EXISTS (SELECT 1 FROM UserProjectRoles WHERE UserID=:uid AND ProjectID=:pid)
                        INSERT INTO UserProjectRoles(UserID, ProjectID, RoleID) VALUES(:uid, :pid, :rid)
                    ELSE
                        UPDATE UserProjectRoles SET RoleID=:rid WHERE UserID=:uid AND ProjectID=:pid
                """), {"uid": user_id, "pid": pid, "rid": rid})

    def get_user_name(self, email: str) -> str:
        """Get user name by email."""
        if not email: return ""
        with self.engine.connect() as conn:
            return conn.execute(text("SELECT Name FROM Users WHERE Email=:e"), {"e": email}).scalar() or ""

    def update_role_permissions(self, role: str, project: str, permissions: list):
        """
        Define what a Role can do in a Project.
        This does NOT touch Users.
        """
        with self.engine.begin() as conn:
            pid = conn.execute(text("SELECT ProjectID FROM Projects WHERE ProjectName=:p"), {"p": project}).scalar()
            rid = conn.execute(text("SELECT RoleID FROM Roles WHERE RoleName=:r"), {"r": role}).scalar()
            
            if not pid or not rid:
                raise ValueError(f"Invalid Project '{project}' or Role '{role}'")

            # We iterate through the provided permissions list. 
            # Ideally, the UI sends the full state for that Project+Role combo.
            # But here we just upsert what's sent.
            
            for p in permissions:
                table = p.get("table")
                can_read = 1 if p.get("canRead") else 0
                can_self = 1 if p.get("canReadSelf") else 0
                
                conn.execute(text("""
                    IF NOT EXISTS (SELECT 1 FROM Permissions WHERE ProjectID=:pid AND RoleID=:rid AND TableName=:t)
                        INSERT INTO Permissions(ProjectID, RoleID, TableName, CanRead, CanReadSelf)
                        VALUES(:pid, :rid, :t, :cr, :cs)
                    ELSE
                        UPDATE Permissions SET CanRead=:cr, CanReadSelf=:cs
                        WHERE ProjectID=:pid AND RoleID=:rid AND TableName=:t
                """), {"pid": pid, "rid": rid, "t": table, "cr": can_read, "cs": can_self})

    def delete_user(self, email: str):
        """Delete a user and their associations."""
        if not email: raise ValueError("Email required")
        
        with self.engine.begin() as conn:
            # Get UserID
            uid = conn.execute(text("SELECT UserID FROM Users WHERE Email=:e"), {"e": email}).scalar()
            if not uid:
                raise ValueError("User not found")
            
            # Delete associations first (FKs usually require this, though CASCADE might exist, explicit is safer)
            conn.execute(text("DELETE FROM UserProjectRoles WHERE UserID=:uid"), {"uid": uid})
            conn.execute(text("DELETE FROM Users WHERE UserID=:uid"), {"uid": uid})

rbac = RBACService()
