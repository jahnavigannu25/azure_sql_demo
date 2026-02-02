# RBAC Improvement Plan: Towards a "Perfect" System

## 1. Current System Analysis

### Existing Components
- **Auth:** MSAL (Azure AD) for identity.
- **Database:** SQL Server with tables: `Users`, `Projects`, `Roles`, `UserProjectRoles`, `Permissions`.
- **Logic:** Embedded in `app.py`.
- **UI:** `admin.html` mixes User Assignment with Role Definition.

### 🔴 Critical Flaws Identified
1.  **Side-Effect Permission Editing (The "Hidden Danger"):**
    - In `api/admin/save-all`, updating a user's access *also* updates the `Permissions` table for the selected Role and Project.
    - **Scenario:** You add "User A" to "Project X" with role "Viewer". You decide "User A" needs access to `Table_Z`, so you check that box.
    - **Result:** You have just granted access to `Table_Z` for **EVERY** user who has the "Viewer" role in "Project X", not just User A.
    - **Fix:** "Role Definition" (what a Viewer can see) must be completely separate from "User Assignment" (who is a Viewer).

2.  **Rigid UI Constraints:**
    - The admin panel limits users to exactly 2 projects.
    - It forces the *same* role for all selected projects (e.g., cannot be Admin in Project A and Viewer in Project B).

3.  **Lack of Granularity:**
    - Permissions are strictly `CanRead` / `CanReadSelf`.
    - No support for "Write", "Delete", or "Approve" actions (even if the app is currently read-only, a robust RBAC should support actions).

4.  **Performance:**
    - Permission checks query the DB on every single request (`get_allowed_tables`). This will not scale.

## 2. The "Perfect" RBAC Architecture

To achieve a flexible, safe, and scalable RBAC system, we need to restructure the application into distinct layers.

### A. Database Schema Refinements
The current schema is actually quite decent, but we should formalize it.

*   `Roles`: Should define *Global* templates (Admin, Editor, Viewer).
*   `Permissions`: (ProjectID, RoleID, Resource, Action).
    *   *Change:* Instead of just `TableName`, use `Resource` to allow for future non-table resources (e.g., 'Reports', 'UserManagement').
    *   *Change:* Add `Action` column (READ, WRITE, DELETE) or keep bit-flags but ensure they are extensible.

### B. Separation of Concerns (Backend)
We will move logic out of `app.py` into a dedicated service.

**New Structure:**
```text
/services
  ├── rbac_service.py      # Core logic (check_permission, get_user_roles)
  ├── admin_service.py     # Admin actions (create_user, assign_role)
  └── auth_service.py      # MSAL/Login helpers
```

### C. Workflow Changes (Frontend & API)

**1. Role Manager (New View)**
*   "I want to define what a 'Viewer' can do in 'Project Sales'."
*   Select Project -> Select Role -> Check boxes for tables/actions -> **SAVE**.
*   *This only touches the `Permissions` table.*

**2. User Manager (Refactored View)**
*   "I want to give Alice access."
*   Select User (Alice).
*   Add Row: Project "Sales" -> Role "Viewer".
*   Add Row: Project "Finance" -> Role "Admin".
*   **SAVE**.
*   *This only touches the `UserProjectRoles` table.*

### D. Caching Strategy
*   Implement a caching layer (e.g., Redis or in-memory dictionary with TTL) for `get_allowed_tables`.
*   Cache Key: `permissions:{user_email}:{project_id}`.
*   Invalidate cache when an Admin updates roles or assignments.

## 3. Implementation Roadmap

### Phase 1: Refactoring & Safety (Immediate)
1.  Extract RBAC queries from `app.py` to `services/rbac_service.py`.
2.  **Split the `save_all` endpoint.** Create distinct `update_role_permissions` and `assign_user_roles` endpoints.
3.  Update `app.py` to use the new service.

### Phase 2: Frontend Separation
1.  Update `admin.html` to remove the permissions table from the "Add User" flow.
2.  Create a separate "Role Definition" section/page in `admin.html`.
3.  Allow per-project role selection (remove the "same role" constraint).

### Phase 3: Advanced Features
1.  Add `Action` granularity (Create, Update, Delete).
2.  Implement Caching.

## 4. Immediate Next Steps
I recommend we start with **Phase 1**. I will create the `rbac_service.py` module and refactor the dangerous `save_all` logic.
