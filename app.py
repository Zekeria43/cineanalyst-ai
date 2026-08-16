import os
import re
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

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8443"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="CineAnalyst AI",
    version="2.0.0",
    description="AI-powered movie analytics API using Gemini and ClickHouse",
)


# ============================================================
# CORS
# ============================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "https://cineanalyst-dashboard.onrender.com",
        "https://cineanalyst-ai.onrender.com",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============================================================
# CLIENTS
# ============================================================

gemini_client = None
clickhouse_client = None


def get_gemini_client():
    global gemini_client

    if gemini_client is None:
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY is not configured")

        gemini_client = genai.Client(
            api_key=GEMINI_API_KEY
        )

    return gemini_client


def get_clickhouse_client():
    global clickhouse_client

    if clickhouse_client is None:
        if not CLICKHOUSE_HOST:
            raise RuntimeError("CLICKHOUSE_HOST is not configured")

        clickhouse_client = clickhouse_connect.get_client(
            host=CLICKHOUSE_HOST,
            port=CLICKHOUSE_PORT,
            username=CLICKHOUSE_USER,
            password=CLICKHOUSE_PASSWORD,
            database=CLICKHOUSE_DATABASE,
            secure=True,
        )

    return clickhouse_client


# ============================================================
# MODELS
# ============================================================

class AskRequest(BaseModel):
    question: str


# ============================================================
# HELPERS
# ============================================================

def clean_sql(text: str) -> str:
    """
    Extract SQL from Gemini response.
    """

    if not text:
        raise ValueError("Gemini returned an empty response")

    text = text.strip()

    # Remove markdown code fences
    text = re.sub(r"^```sql\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"^```\s*", "", text)
    text = re.sub(r"\s*```$", "", text)

    # Find SELECT or WITH
    match = re.search(
        r"(?is)\b(SELECT|WITH)\b.*",
        text
    )

    if match:
        text = match.group(0)

    # Remove trailing semicolon
    text = text.strip().rstrip(";").strip()

    return text


def validate_sql(sql: str) -> str:
    """
    Only allow read-only SQL.
    """

    sql_clean = sql.strip()

    if not re.match(
        r"^(SELECT|WITH)\b",
        sql_clean,
        flags=re.IGNORECASE,
    ):
        raise ValueError(
            "Only SELECT queries are allowed."
        )

    forbidden = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "TRUNCATE",
        "CREATE",
        "RENAME",
        "OPTIMIZE",
        "SYSTEM",
        "GRANT",
        "REVOKE",
    ]

    upper_sql = sql_clean.upper()

    for word in forbidden:
        if re.search(
            rf"\b{word}\b",
            upper_sql,
        ):
            raise ValueError(
                f"Forbidden SQL operation: {word}"
            )

    return sql_clean


def get_movies_schema() -> str:
    client = get_clickhouse_client()

    result = client.query(
        """
        SELECT
            name,
            type
        FROM system.columns
        WHERE database = {database:String}
          AND table = 'movies'
        ORDER BY position
        """,
        parameters={
            "database": CLICKHOUSE_DATABASE
        },
    )

    lines = []

    for row in result.result_rows:
        name, data_type = row
        lines.append(
            f"- {name}: {data_type}"
        )

    return "\n".join(lines)


def generate_sql(question: str) -> tuple[str, str]:
    schema = get_movies_schema()

    prompt = f"""
You are CineAnalyst AI, an expert SQL analyst.

You have access to a ClickHouse database.

Database:
{CLICKHOUSE_DATABASE}

Table:
default.movies

Schema:
{schema}

User question:
{question}

Generate ONE read-only ClickHouse SQL query.

Rules:
- Return ONLY SQL.
- Use only SELECT or WITH.
- Never modify data.
- Do not use INSERT.
- Do not use UPDATE.
- Do not use DELETE.
- Do not use DROP.
- Do not use ALTER.
- Do not use CREATE.
- Use the actual columns from the schema.
- For "most revenue", order revenue DESC.
- For "highest rated", order rating DESC.
- For counting movies, use COUNT().
- For averages, use AVG().
- Keep the query simple and efficient.

SQL:
"""

    client = get_gemini_client()

    response = client.models.generate_content(
        model=GEMINI_MODEL,
        contents=prompt,
    )

    sql = clean_sql(
        getattr(response, "text", "")
    )

    sql = validate_sql(sql)

    return sql, "Gemini AI"


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
    result = {
        "status": "ok",
        "api": "online",
        "clickhouse": "unknown",
        "gemini": "configured" if GEMINI_API_KEY else "missing",
    }

    try:
        client = get_clickhouse_client()

        client.query("SELECT 1")

        result["clickhouse"] = "connected"

    except Exception as exc:
        result["clickhouse"] = "error"
        result["clickhouse_error"] = str(exc)

    return result


# ============================================================
# MOVIES
# ============================================================

@app.get("/movies")
def movies():
    try:
        client = get_clickhouse_client()

        result = client.query(
            """
            SELECT
                id,
                title,
                genre,
                release_year,
                rating,
                revenue
            FROM default.movies
            ORDER BY revenue DESC
            """
        )

        columns = [
            "id",
            "title",
            "genre",
            "release_year",
            "rating",
            "revenue",
        ]

        movie_list = []

        for row in result.result_rows:
            movie_list.append(
                {
                    "id": row[0],
                    "title": row[1],
                    "genre": row[2],
                    "release_year": row[3],
                    "rating": row[4],
                    "revenue": row[5],
                }
            )

        return {
            "success": True,
            "count": len(movie_list),
            "columns": columns,
            "movies": movie_list,
        }

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Unable to load movies.",
                "error": str(exc),
            },
        )


# ============================================================
# HISTORY
# ============================================================

@app.get("/history")
def history():
    """
    History is currently maintained by the frontend.
    This endpoint exists so the dashboard can safely call it.
    """

    return {
        "success": True,
        "history": [],
    }


# ============================================================
# ASK AI
# ============================================================

@app.post("/ask")
def ask(request: AskRequest):
    question = request.question.strip()

    if not question:
        raise HTTPException(
            status_code=400,
            detail={
                "message": "Question cannot be empty."
            },
        )

    try:
        sql, sql_source = generate_sql(
            question
        )

        client = get_clickhouse_client()

        result = client.query(sql)

        columns = list(
            result.column_names
        )

        rows = []

        for row in result.result_rows:
            rows.append(
                list(row)
            )

        return {
            "success": True,
            "question": question,
            "sql": sql,
            "sql_source": sql_source,
            "columns": columns,
            "results": rows,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail={
                "message": str(exc)
            },
        )

    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail={
                "message": "Unable to process the question.",
                "error": str(exc),
            },
        )


# ============================================================
# RUN
# ============================================================

if __name__ == "__main__":
    import uvicorn

    port = int(
        os.getenv(
            "PORT",
            "8000"
        )
    )

    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )