import os
import re
import traceback

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

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8443"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")


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
        "https://cineanalyst-ai-zekeria.onrender.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# GLOBAL CLIENTS
# ============================================================

clickhouse_client = None
gemini_client = None


# ============================================================
# STARTUP
# ============================================================

@app.on_event("startup")
def startup_event():
    global clickhouse_client
    global gemini_client

    # --------------------------------------------------------
    # ClickHouse
    # --------------------------------------------------------

    try:
        if CLICKHOUSE_HOST and CLICKHOUSE_PASSWORD:
            clickhouse_client = clickhouse_connect.get_client(
                host=CLICKHOUSE_HOST,
                port=CLICKHOUSE_PORT,
                username=CLICKHOUSE_USER,
                password=CLICKHOUSE_PASSWORD,
                database=CLICKHOUSE_DATABASE,
                secure=True,
            )

            clickhouse_client.query("SELECT 1")

            print("ClickHouse connection: OK")

        else:
            print("WARNING: ClickHouse credentials are not configured.")

    except Exception:
        print("ClickHouse connection: FAILED")
        traceback.print_exc()
        clickhouse_client = None

    # --------------------------------------------------------
    # Gemini
    # --------------------------------------------------------

    try:
        if GEMINI_API_KEY:
            gemini_client = genai.Client(
                api_key=GEMINI_API_KEY
            )

            print(f"Gemini client: OK - model: {GEMINI_MODEL}")

        else:
            print("WARNING: GEMINI_API_KEY is not configured.")

    except Exception:
        print("Gemini client: FAILED")
        traceback.print_exc()
        gemini_client = None


# ============================================================
# REQUEST MODEL
# ============================================================

class QuestionRequest(BaseModel):
    question: str


# ============================================================
# HELPERS
# ============================================================

def format_value(value):
    if value is None:
        return None

    if isinstance(value, float):
        if value.is_integer():
            return int(value)

        return round(value, 2)

    return value


def clean_sql(sql: str) -> str:
    """
    Clean SQL returned by Gemini.
    """

    if not sql:
        return ""

    sql = sql.strip()

    # Remove Markdown code fences
    sql = re.sub(r"^```(?:sql)?", "", sql, flags=re.IGNORECASE)
    sql = re.sub(r"```$", "", sql)

    sql = sql.strip()

    # Remove accidental prefixes
    sql = re.sub(
        r"^(SQL\s*:|QUERY\s*:)\s*",
        "",
        sql,
        flags=re.IGNORECASE,
    )

    return sql.strip()


def validate_sql(sql: str) -> bool:
    """
    Only allow read-only SQL.
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

    # Block dangerous operations
    forbidden = [
        "insert ",
        "update ",
        "delete ",
        "drop ",
        "alter ",
        "truncate ",
        "create ",
        "replace ",
        "grant ",
        "revoke ",
        "attach ",
        "detach ",
        "optimize ",
        "system ",
    ]

    for keyword in forbidden:
        if keyword in normalized:
            return False

    return True


# ============================================================
# LOCAL SQL FALLBACK
# ============================================================

def local_sql_fallback(question: str):
    """
    Simple deterministic SQL fallback for common questions.
    """

    q = question.lower().strip()

    # Most revenue
    if (
        "most revenue" in q
        or "highest revenue" in q
        or "maximum revenue" in q
        or "top revenue" in q
        or "highest earning" in q
    ):
        return """
SELECT
    title,
    revenue
FROM default.movies
WHERE revenue IS NOT NULL
ORDER BY revenue DESC
LIMIT 1
""".strip()

    # Most popular
    if "most popular" in q or "highest popularity" in q:
        return """
SELECT
    title,
    popularity
FROM default.movies
WHERE popularity IS NOT NULL
ORDER BY popularity DESC
LIMIT 1
""".strip()

    # Highest rating
    if (
        "highest rating" in q
        or "best rated" in q
        or "highest rated" in q
    ):
        return """
SELECT
    title,
    vote_average
FROM default.movies
WHERE vote_average IS NOT NULL
ORDER BY vote_average DESC
LIMIT 1
""".strip()

    # Number of movies
    if (
        "how many movies" in q
        or "number of movies" in q
        or "count movies" in q
    ):
        return """
SELECT
    count(*) AS movie_count
FROM default.movies
""".strip()

    return None


# ============================================================
# DATABASE QUERY
# ============================================================

def execute_query(sql: str):
    if clickhouse_client is None:
        raise RuntimeError("ClickHouse client is not available.")

    result = clickhouse_client.query(sql)

    columns = list(result.column_names)

    rows = []

    for row in result.result_rows:
        item = {}

        for index, column in enumerate(columns):
            item[column] = format_value(row[index])

        rows.append(item)

    return columns, rows


# ============================================================
# GEMINI SQL GENERATION
# ============================================================

def generate_sql_with_gemini(question: str):
    if gemini_client is None:
        return None

    schema = """
Database: ClickHouse
Table: default.movies

Available columns may include:
- title
- revenue
- popularity
- vote_average
- vote_count
- budget
- release_date
- runtime
- genres
- overview
- original_language
- original_title
"""

    prompt = f"""
You are CineAnalyst AI, a movie analytics SQL assistant.

Convert the user's natural-language question into ONE safe ClickHouse SQL query.

Rules:
1. Return ONLY SQL.
2. Use only the table default.movies.
3. Use SELECT or WITH queries only.
4. Never modify data.
5. Never use INSERT, UPDATE, DELETE, DROP, ALTER, TRUNCATE, CREATE, or other write operations.
6. If the user asks for the movie with the highest revenue, sort revenue DESC and LIMIT 1.
7. Prefer explicit column names.
8. Add LIMIT when returning movie rows.
9. Do not use Markdown code fences.

{schema}

User question:
{question}
"""

    try:
        response = gemini_client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )

        text = getattr(response, "text", None)

        if not text:
            return None

        sql = clean_sql(text)

        if validate_sql(sql):
            return sql

    except Exception:
        print("Gemini SQL generation failed:")
        traceback.print_exc()

    return None


# ============================================================
# HEALTH CHECK
# ============================================================

@app.get("/")
def root():
    return {
        "name": "CineAnalyst AI",
        "status": "online",
        "version": "2.0.0",
        "message": "CineAnalyst API is running.",
    }


@app.get("/health")
def health():
    return {
        "status": "ok",
        "clickhouse": clickhouse_client is not None,
        "gemini": gemini_client is not None,
        "model": GEMINI_MODEL,
    }


# ============================================================
# ASK ENDPOINT
# ============================================================

@app.post("/ask")
def ask_question(request: QuestionRequest):

    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    # --------------------------------------------------------
    # Generate SQL
    # --------------------------------------------------------

    sql_source = "Gemini"

    sql = generate_sql_with_gemini(question)

    # --------------------------------------------------------
    # Local fallback
    # --------------------------------------------------------

    if not sql:
        sql = local_sql_fallback(question)
        sql_source = "Local Fallback"

    if not sql:
        raise HTTPException(
            status_code=503,
            detail=(
                "Unable to generate SQL for this question. "
                "Please try another movie analytics question."
            ),
        )

    # --------------------------------------------------------
    # Validate SQL
    # --------------------------------------------------------

    sql = clean_sql(sql)

    if not validate_sql(sql):
        raise HTTPException(
            status_code=400,
            detail="Generated SQL failed the safety validation.",
        )

    # --------------------------------------------------------
    # Execute SQL
    # --------------------------------------------------------

    try:
        columns, rows = execute_query(sql)

    except Exception as error:
        print("ClickHouse query failed:")
        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Database query failed: {str(error)}",
        )

    # --------------------------------------------------------
    # Return response
    # --------------------------------------------------------

    return {
        "success": True,
        "question": question,
        "sql": sql,
        "sql_source": sql_source,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
    }


# ============================================================
# RUN LOCALLY
# ============================================================

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=True,
    )