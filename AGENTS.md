# AGENTS.md — Agent & Assistant Guide for Finode

Welcome, AI agent! This document serves as a specialized manual to help you navigate, understand, and develop within the `finode` repository efficiently and safely. Always review these rules and patterns before making modifications.

---

## 🚀 Quick Reference Commands

For any execution tasks, use `uv` to manage tools and dependencies. **Do not run raw `pip`, `pipenv`, or edit `pyproject.toml` manually.**

*   **Install Dependencies:** `uv sync`
*   **Run Development Server:** `uv run fastapi dev` (Runs on `http://localhost:8000` with auto-reload)
*   **Run Production-like Server:** `uv run fastapi run`
*   **Run Automated Tests:** `uv run pytest`
*   **Generate Database Migrations:** `uv run alembic revision --autogenerate -m "description"`
*   **Apply Migrations:** `uv run alembic upgrade head`
*   **Add Python Package:** `uv add <package-name>`

---

## 🏛️ Application Architecture & Conventions

All core logic lives inside the `app/` folder. The codebase follows a strict **five-tier modular structure** segmented by domain entities (`account.py`, `category.py`, `transaction.py`):

```
app/
├── models/         # SQLModel ORM schemas (tables)
├── schemas/        # Pydantic request/response validation models
├── repositories/   # Plain CRUD functions executing over a database Session
├── services/       # Complex business logic orchestrating multiple repositories (add as needed)
└── routers/        # FastAPI APIRouter endpoints and HTTP exception mapping
```

### 1. Style & Import Rules
*   **Imports:** Always use **relative imports** when referencing modules inside the `app/` package (e.g., `from ..models.account import Account`).
*   **No Dependency Injection inside Repositories:** Keep repository files simple. They should consist of pure functions that accept a `Session` (and optionally a user ID / payloads) and return ORM objects or `None`.
*   **Routes & Database:** Routers must **never** access the database session directly or perform SQL operations. They must go through a repository or a service.
*   **Error Handling:** Routers are responsible for mapping `None` values returned by repositories or services into appropriate `HTTPException(status_code=404)`.

### 2. Database & Schema Rules
*   **SQLModel:** The models (under `app/models/`) are the source of truth for the database schema.
*   **Alembic Migrations:** Never invoke `SQLModel.metadata.create_all` during server startup. Always use Alembic migrations to apply structural changes.
*   **Timestamps:** Models should inherit from `TimestampMixin` (found in `app/models/utils.py`) to automatically record `created` and `updated` UTC datetimes.

### 3. Polymorphic Transaction Pattern
Transactions are stored in a single table (`transactions`) but represent three distinct operational types differentiated **implicitly** by foreign key nullability:

*   **Expense:** `source` account set, `destination` account is `None`.
*   **Income:** `source` is `None`, `destination` account set.
*   **Transfer:** Both `source` and `destination` accounts are set.

#### Schema Implementation:
*   The database model is `app/models/transaction.py`.
*   Request/response models in `app/schemas/transaction.py` are split into three Pydantic families: `Expense*`, `Income*`, and `Transfer*`.
*   FastAPI routes accept and return unions (e.g., `ExpenseCreate | IncomeCreate | TransferCreate`) and automatically discriminate which shape is used by validating the combination of present fields.
*   Filtering by type on `GET /transactions/?type=...` is performed in Python within the repository/router layers based on field nullability. There is no `type` column in the database.

### 4. Tenant Isolation & Auth
*   Every entity (`Account`, `Category`, `Transaction`) belongs to a user and has a `user: UUID` foreign key pointing to the Supabase authorization schema (`auth.users.id`).
*   **Enforce Isolation:** Always filter operations by `current_user.id`. When fetching, updating, or deleting records, ensure the database query includes a filter like `.where(Model.user == current_user.id)`.
*   All endpoints protecting tenant data must use the `require_authenticated_user` dependency from `app/auth.py`.
*   Inject the session into route handlers using the custom annotated dependency: `session: DBSession`.

---

## 🧪 Testing Guidelines

*   Tests reside inside the `tests/` directory.
*   **Database Isolation:** Tests do not connect to the development database (`finode.db`). The `tests/conftest.py` setup provisions a fresh, in-memory SQLite database (`sqlite://`) for every individual test.
*   All FastAPI routes inside tests have their `get_db_session` dependency overridden to use this isolated session.
*   **Writing Tests:** When adding features, ensure you write comprehensive integration/unit tests validating both successful operations and edge cases (e.g., tenant cross-access attempts, invalid payloads).
