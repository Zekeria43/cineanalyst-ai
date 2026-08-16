import os
import re
import traceback
from typing import Any

import clickhouse_connect
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from google import genai


# ============================================================
# ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="CineAnalyst AI API",
    version="2.0.0",
    description="AI-powered movie analytics API using Gemini and ClickHouse.",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cineanalyst-dashboard.onrender.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# ENV VARIABLES
# ============================================================

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8443"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)


# ============================================================
# GLOBAL CLIENTS
# ============================================================

client = None
gemini = None


# ============================================================
# CLICKHOUSE CONNECTION
# ============================================================

try:
    if not CLICKHOUSE_HOST:
        print("WARNING: CLICKHOUSE_HOST is not configured.")
    elif not CLICKHOUSE_PASSWORD:
        print("WARNING: CLICKHOUSE_PASSWORD is not configured.")
    else:
        client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DATABASE,
            secure=True,
        )

        client.query("SELECT 1")

        print("ClickHouse connection: OK")

except Exception:
    print("ClickHouse connection: FAILED")
    traceback.print_exc()
    client = None


# ============================================================
# GEMINI CONNECTION
# ============================================================

try:
    if GEMINI_API_KEY:
        gemini = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("Gemini client: OK")
    else:
        print("WARNING: GEMINI_API_KEY is not configured.")

except Exception:
    print("Gemini client: FAILED")
    traceback.print_exc()
    gemini = None


# ============================================================
# REQUEST MODELS
# ============================================================

class QuestionRequest(BaseModel):
    question: str


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def format_value(value: Any):
    """
    Convert ClickHouse/Python values into JSON-friendly values.
    """

    if value is None:
        return None

    if isinstance(value, float):
        if value.is_integer():
            return int(value)

        return round(value, 2)

    return value


def clean_sql(sql: str) -> str:
    """
    Clean Gemini-generated SQL.
    """

    if not sql:
        return ""

    sql = sql.strip()

    # Remove markdown code fences
    sql = re.sub(r"^```sql\s*", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"^```\s*", "", sql)
    sql = re.sub(r"\s*```$", "", sql)

    # Remove unwanted semicolon at the end
    sql = sql.strip().rstrip(";").strip()

    return sql


def is_safe_sql(sql: str) -> bool:
    """
    Only allow read-only SQL queries.
    """

    if not sql:
        return False

    normalized = sql.strip().lower()

    # Must start with SELECT or WITH
    if not (
        normalized.startswith("select")
        or normalized.startswith("with")
    ):
        return False

    # Block write/destructive operations
    forbidden = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "truncate ",
        "create ",
        "replace ",
        "attach ",
        "detach ",
        "optimize ",
        "grant ",
        "revoke ",
        "system ",
    ]

    for keyword in forbidden:
        if keyword in normalized:
            return False

    return True


def get_movies_schema() -> str:
    """
    Get the schema of default.movies.
    """

    if client is None:
        return ""

    result = client.query("""
        SELECT
            name,
            type
        FROM system.columns
        WHERE database = 'default'
          AND table = 'movies'
        ORDER BY position
    """)

    schema_lines = []

    for row in result.result_rows:
        name = row[0]
        data_type = row[1]
        schema_lines.append(f"- {name}: {data_type}")

    return "\n".join(schema_lines)


def generate_sql(question: str) -> str:
    """
    Generate SQL from natural language using Gemini.
    """

    if gemini is None:
        raise HTTPException(
            status_code=503,
            detail="Gemini AI is not configured."
        )

    schema = get_movies_schema()

    prompt = f"""
You are an expert ClickHouse SQL assistant.

Convert the user's natural-language question into ONE safe,
read-only ClickHouse SQL query.

Database:
default

Main table:
default.movies

Table schema:
{schema}

Important rules:

1. Return ONLY SQL.
2. Do not use Markdown.
3. Only generate SELECT or WITH queries.
4. Never generate INSERT, UPDATE, DELETE, DROP, ALTER, CREATE,
   TRUNCATE, SYSTEM, GRANT or REVOKE.
5. Use the exact column names from the schema.
6. For "most revenue", sort revenue DESC.
7. For "highest rated", sort rating DESC.
8. For counting movies, use COUNT(*).
9. For averages, use AVG().
10. For questions asking for a single best/worst movie, use LIMIT 1.
11. Use ClickHouse-compatible SQL.
12. Use default.movies explicitly.
13. Do not invent columns.

User question:
{question}
"""

    try:
        response = gemini.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )

        sql = clean_sql(response.text)

        return sql

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Gemini error: {str(error)}"
        )


# ============================================================
# ROOT
# ============================================================

@app.get("/")
def root():
    return {
        "name": "CineAnalyst AI",
        "status": "online",
        "version": "2.0.0",
        "message": "CineAnalyst API is running.",
    }


# ============================================================
# HEALTH
# ============================================================

@app.get("/health")
def health():
    clickhouse_status = client is not None
    gemini_status = gemini is not None

    return {
        "status": "ok",
        "clickhouse": clickhouse_status,
        "gemini": gemini_status,
    }


# ============================================================
# MOVIES
# ============================================================

@app.get("/movies")
def get_movies():
    """
    Return movies from ClickHouse.
    """

    if client is None:
        raise HTTPException(
            status_code=503,
            detail="ClickHouse connection is not available."
        )

    try:
        result = client.query("""
            SELECT
                id,
                title,
                genre,
                release_year,
                rating,
                revenue
            FROM default.movies
            ORDER BY revenue DESC
        """)

        movies = []

        for row in result.result_rows:
            movie = {}

            for index, column in enumerate(result.column_names):
                movie[column] = format_value(row[index])

            movies.append(movie)

        return {
            "success": True,
            "count": len(movies),
            "columns": result.column_names,
            "movies": movies,
        }

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to load movies: {str(error)}"
        )


# ============================================================
# HISTORY
# ============================================================

@app.get("/history")
def get_history():
    """
    Return recent query history if the history table exists.
    """

    if client is None:
        raise HTTPException(
            status_code=503,
            detail="ClickHouse connection is not available."
        )

    try:

        # Check whether a history table exists.
        tables = client.query("""
            SELECT name
            FROM system.tables
            WHERE database = 'default'
              AND name = 'query_history'
        """)

        if not tables.result_rows:
            return {
                "success": True,
                "history": [],
                "message": "No query_history table found.",
            }

        result = client.query("""
            SELECT *
            FROM default.query_history
            ORDER BY 1 DESC
            LIMIT 50
        """)

        history = []

        for row in result.result_rows:
            item = {}

            for index, column in enumerate(result.column_names):
                item[column] = format_value(row[index])

            history.append(item)

        return {
            "success": True,
            "columns": result.column_names,
            "history": history,
        }

    except Exception as error:
        traceback.print_exc()

        return {
            "success": True,
            "history": [],
            "message": str(error),
        }


# ============================================================
# ASK AI
# ============================================================

@app.post("/ask")
def ask_ai(request: QuestionRequest):
    """
    Convert natural language into SQL,
    execute it in ClickHouse,
    and return the result.
    """

    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty."
        )

    if len(question) > 1000:
        raise HTTPException(
            status_code=400,
            detail="Question is too long."
        )

    if client is None:
        raise HTTPException(
            status_code=503,
            detail="ClickHouse connection is not available."
        )

    # --------------------------------------------------------
    # Generate SQL
    # --------------------------------------------------------

    sql = generate_sql(question)

    # --------------------------------------------------------
    # Validate SQL
    # --------------------------------------------------------

    if not is_safe_sql(sql):
        raise HTTPException(
            status_code=400,
            detail="Generated SQL was rejected for safety reasons."
        )

    # --------------------------------------------------------
    # Execute SQL
    # --------------------------------------------------------

    try:

        result = client.query(sql)

        rows = []

        for row in result.result_rows:
            item = {}

            for index, column in enumerate(result.column_names):
                item[column] = format_value(row[index])

            rows.append(item)

        # ----------------------------------------------------
        # Also provide array format for frontend compatibility
        # ----------------------------------------------------

        result_arrays = []

        for row in result.result_rows:
            result_arrays.append([
                format_value(value)
                for value in row
            ])

        return {
            "success": True,
            "question": question,
            "sql": sql,
            "sql_source": "Gemini AI",
            "columns": result.column_names,
            "results": result_arrays,
            "rows": rows,
            "count": len(rows),
        }

    except Exception as error:
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"ClickHouse query failed: {str(error)}"
        )


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():
    print("=" * 60)
    print("CineAnalyst AI API")
    print("Version: 2.0.0")
    print("Status: starting")
    print("=" * 60)

    print(
        "ClickHouse:",
        "CONNECTED" if client else "NOT CONNECTED"
    )

    print(
        "Gemini:",
        "CONNECTED" if gemini else "NOT CONNECTED"
    )

    print("=" * 60)