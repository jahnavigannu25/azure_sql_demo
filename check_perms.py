
from services.rbac_service import rbac
from sqlalchemy import text

def check():
    engine = rbac.engine

    with engine.connect() as conn:
        print("--- PROJECTS ---")
        rows = conn.execute(text("SELECT * FROM Projects")).fetchall()
        for r in rows: print(r)

        print("\n--- ROLES ---")
        rows = conn.execute(text("SELECT * FROM Roles")).fetchall()
        for r in rows: print(r)
        
        print("\n--- PERMISSIONS ---")
        rows = conn.execute(text("""
            SELECT p.ProjectName, r.RoleName, perm.TableName, perm.CanRead, perm.CanReadSelf
            FROM Permissions perm
            JOIN Projects p ON p.ProjectID = perm.ProjectID
            JOIN Roles r ON r.RoleID = perm.RoleID
            ORDER BY p.ProjectName, r.RoleName, perm.TableName
        """)).fetchall()
        for r in rows: print(r)

        print("\n--- USER ROLES (Jahnavi) ---")
        rows = conn.execute(text("""
            SELECT u.Email, u.Name, p.ProjectName, r.RoleName
            FROM Users u
            JOIN UserProjectRoles upr ON upr.UserID = u.UserID
            JOIN Projects p ON p.ProjectID = upr.ProjectID
            JOIN Roles r ON r.RoleID = upr.RoleID
            WHERE u.Email LIKE '%gannu%' OR u.Name LIKE '%gannu%' OR u.Email LIKE '%jahnavi%'
        """)).fetchall()
        for r in rows: print(r)

if __name__ == "__main__":
    check()
