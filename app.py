````python
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


# ============================================================
# FASTAPI
# ============================================================

app = FastAPI(
    title="CineAnalyst AI API",
    version="2.0.0",
)


# ============================================================
# CORS
# ============================================================

# TEMPORARY / TEST CONFIGURATION
# Allows the deployed frontend to communicate with Render.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
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

MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)


# ============================================================
# ENVIRONMENT VALIDATION
# ============================================================

if not CLICKHOUSE_HOST:
    print("WARNING: CLICKHOUSE_HOST is not configured.")

if not CLICKHOUSE_PASSWORD:
    print("WARNING: CLICKHOUSE_PASSWORD is not configured.")

if not GEMINI_API_KEY:
    print("WARNING: GEMINI_API_KEY is not configured.")


# ============================================================
# CLICKHOUSE
# ============================================================

client = None

try:

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

except Exception as error:

    print("ClickHouse connection: FAILED")
    traceback.print_exc()


# ============================================================
# GEMINI
# ============================================================

gemini = None

try:

    if GEMINI_API_KEY:

        gemini = genai.Client(
            api_key=GEMINI_API_KEY
        )

        print("Gemini client: OK")

    else:

        print("Gemini client: NOT CONFIGURED")

except Exception as error:

    print("Gemini client: FAILED")
    traceback.print_exc()


# ============================================================
# REQUEST MODEL
# ============================================================

class QuestionRequest(BaseModel):
    question: str


# ============================================================
# FORMAT VALUES
# ============================================================

def format_value(value):

    if value is None:
        return None

    if isinstance(value, float):

        if value.is_integer():
            return int(value)

        return round(value, 2)

    return value


# ============================================================
# LOCAL SQL FALLBACK
# ============================================================

def fallback_sql(question: str):

    q = question.lower().strip()

    # Most revenue
    if (
        "most revenue" in q
        or "highest revenue" in q
        or "top revenue" in q
        or "generated the most" in q
    ):

        return """
        SELECT title, revenue
        FROM default.movies
        ORDER BY revenue DESC
        LIMIT 1
        """

    # Highest rated
    if (
        "highest-rated" in q
        or "highest rated" in q
        or "best rated" in q
        or "top rated" in q
    ):

        return """
        SELECT title, rating
        FROM default.movies
        ORDER BY rating DESC
        LIMIT 1
        """

    # Count movies
    if (
        "how many movies" in q
        or "number of movies" in q
        or "count of movies" in q
    ):

        return """
        SELECT COUNT()
        FROM default.movies
        """

    # Average rating
    if (
        "average rating" in q
        or "average score" in q
    ):

        return """
        SELECT AVG(rating)
        FROM default.movies
        """

    # USA
    if (
        "movies from usa" in q
        or "movies from the usa" in q
        or "how many movies are from usa" in q
    ):

        return """
        SELECT COUNT()
        FROM default.movies
        WHERE country = 'USA'
        """

    return None


# ============================================================
# GEMINI SQL GENERATION
# ============================================================

def generate_sql(question: str):

    if not gemini:

        raise RuntimeError(
            "Gemini client is not configured."
        )

    prompt = f"""
You are CineAnalyst AI.

You convert natural-language movie questions into
safe ClickHouse SQL queries.

DATABASE:

Table:
default.movies

Columns:

title
revenue
rating
country
genre
release_year

RULES:

1. Return SQL ONLY.
2. Use ONLY SELECT queries.
3. Use ONLY default.movies.
4. Never use INSERT.
5. Never use UPDATE.
6. Never use DELETE.
7. Never use DROP.
8. Never use ALTER.
9. Never use CREATE.
10. Never use TRUNCATE.
11. Never use multiple SQL statements.
12. Do not use Markdown.
13. Do not explain the SQL.

EXAMPLE 1:

Question:
Which movie generated the most revenue?

SQL:
SELECT title, revenue
FROM default.movies
ORDER BY revenue DESC
LIMIT 1

EXAMPLE 2:

Question:
What is the highest-rated movie?

SQL:
SELECT title, rating
FROM default.movies
ORDER BY rating DESC
LIMIT 1

EXAMPLE 3:

Question:
How many movies are from USA?

SQL:
SELECT COUNT()
FROM default.movies
WHERE country = 'USA'

EXAMPLE 4:

Question:
Which movies were released after 2000?

SQL:
SELECT title, release_year
FROM default.movies
WHERE release_year > 2000
ORDER BY release_year ASC

EXAMPLE 5:

Question:
What is the average rating of Sci-Fi movies?

SQL:
SELECT AVG(rating)
FROM default.movies
WHERE genre = 'Sci-Fi'

USER QUESTION:

{question}

RETURN SQL ONLY.
"""

    print()
    print("=" * 60)
    print("GEMINI REQUEST")
    print("=" * 60)
    print("Question:", question)
    print("Model:", MODEL)

    try:

        response = gemini.models.generate_content(
            model=MODEL,
            contents=prompt,
        )

    except Exception as error:

        print()
        print("=" * 60)
        print("GEMINI ERROR")
        print("=" * 60)

        traceback.print_exc()

        raise RuntimeError(
            f"Gemini request failed: {error}"
        )

    if not response:

        raise RuntimeError(
            "Gemini returned no response."
        )

    if not response.text:

        raise RuntimeError(
            "Gemini returned an empty response."
        )

    sql = response.text.strip()

    print()
    print("RAW GEMINI RESPONSE:")
    print(sql)

    # Remove Markdown fences
    sql = re.sub(
        r"^```sql\s*",
        "",
        sql,
        flags=re.IGNORECASE,
    )

    sql = re.sub(
        r"^```\s*",
        "",
        sql,
    )

    sql = re.sub(
        r"\s*```$",
        "",
        sql,
    )

    return sql.strip()


# ============================================================
# SQL SECURITY
# ============================================================

def validate_sql(sql: str):

    sql_clean = sql.strip()

    if not sql_clean:

        raise ValueError(
            "Gemini returned an empty SQL query."
        )

    # Only SELECT
    if not re.match(
        r"^SELECT\b",
        sql_clean,
        flags=re.IGNORECASE,
    ):

        raise ValueError(
            "Security error: only SELECT queries are allowed."
        )

    # Forbidden commands
    forbidden_keywords = [
        "INSERT",
        "UPDATE",
        "DELETE",
        "DROP",
        "ALTER",
        "CREATE",
        "TRUNCATE",
        "OPTIMIZE",
        "GRANT",
        "REVOKE",
    ]

    sql_upper = sql_clean.upper()

    for keyword in forbidden_keywords:

        if re.search(
            rf"\b{keyword}\b",
            sql_upper,
        ):

            raise ValueError(
                f"Security error: forbidden SQL command {keyword}"
            )

    # Only one statement
    statements = [
        statement.strip()
        for statement in sql_clean.split(";")
        if statement.strip()
    ]

    if len(statements) > 1:

        raise ValueError(
            "Security error: multiple SQL statements are not allowed."
        )

    # Only our table
    if not re.search(
        r"\bdefault\.movies\b",
        sql_clean,
        flags=re.IGNORECASE,
    ):

        raise ValueError(
            "Security error: query must use default.movies."
        )


# ============================================================
# ASK ENDPOINT
# ============================================================

@app.post("/ask")
def ask_cineanalyst(
    request: QuestionRequest
):

    question = request.question.strip()

    print()
    print("=" * 60)
    print("NEW /ask REQUEST")
    print("=" * 60)
    print("Question:", question)

    if not question:

        raise HTTPException(
            status_code=400,
            detail="Question cannot be empty.",
        )

    if not client:

        raise HTTPException(
            status_code=503,
            detail="ClickHouse is not available.",
        )

    # --------------------------------------------------------
    # GENERATE SQL
    # --------------------------------------------------------

    sql = None
    sql_source = None
    gemini_error = None

    # First try Gemini
    try:

        sql = generate_sql(question)
        sql_source = "Gemini AI"

    except Exception as error:

        gemini_error = str(error)

        print()
        print("=" * 60)
        print("GEMINI UNAVAILABLE")
        print("=" * 60)

        print(gemini_error)

        # Try local fallback
        sql = fallback_sql(question)

        if sql:

            sql_source = "Local Fallback"

            print()
            print("=" * 60)
            print("FALLBACK SQL")
            print("=" * 60)

            print(sql)

        else:

            raise HTTPException(
                status_code=503,
                detail={
                    "message": (
                        "Gemini is unavailable and "
                        "no local fallback matches "
                        "this question."
                    ),
                    "gemini_error": gemini_error,
                },
            )

    # --------------------------------------------------------
    # VALIDATE SQL
    # --------------------------------------------------------

    try:

        validate_sql(sql)

    except Exception as error:

        raise HTTPException(
            status_code=400,
            detail=str(error),
        )

    # --------------------------------------------------------
    # EXECUTE CLICKHOUSE
    # --------------------------------------------------------

    try:

        print()
        print("=" * 60)
        print("EXECUTING CLICKHOUSE QUERY")
        print("=" * 60)

        print(sql)

        result = client.query(sql)

    except Exception as error:

        print()
        print("=" * 60)
        print("CLICKHOUSE ERROR")
        print("=" * 60)

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"ClickHouse query failed: {error}",
        )

    # --------------------------------------------------------
    # GET ROWS
    # --------------------------------------------------------

    rows = result.result_set

    print()
    print("CLICKHOUSE RESULT:")
    print(rows)

    # --------------------------------------------------------
    # FORMAT RESULTS
    # --------------------------------------------------------

    formatted_rows = []

    for row in rows:

        formatted_rows.append(
            [
                format_value(value)
                for value in row
            ]
        )

    # --------------------------------------------------------
    # SAVE HISTORY
    # --------------------------------------------------------

    history.append(
        {
            "question": question,
            "sql": sql,
            "sql_source": sql_source,
            "columns": list(result.column_names),
            "results": formatted_rows,
        }
    )

    # Keep latest 50 questions
    if len(history) > 50:

        del history[:-50]

    # --------------------------------------------------------
    # RESPONSE
    # --------------------------------------------------------

    return {
        "success": True,
        "question": question,
        "sql": sql,
        "sql_source": sql_source,
        "columns": list(result.column_names),
        "results": formatted_rows,
    }


# ============================================================
# MOVIES ENDPOINT
# ============================================================

@app.get("/movies")
def get_movies():

    if not client:

        raise HTTPException(
            status_code=503,
            detail="ClickHouse is not available.",
        )

    try:

        result = client.query(
            """
            SELECT
                title,
                revenue,
                rating,
                country,
                genre,
                release_year
            FROM default.movies
            ORDER BY revenue DESC
            """
        )

        movies = []

        for row in result.result_set:

            movies.append(
                {
                    "title": format_value(row[0]),
                    "revenue": format_value(row[1]),
                    "rating": format_value(row[2]),
                    "country": format_value(row[3]),
                    "genre": format_value(row[4]),
                    "release_year": format_value(row[5]),
                }
            )

        return {
            "success": True,
            "movies": movies,
        }

    except Exception as error:

        print()
        print("MOVIES ERROR:")

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Failed to load movies: {error}",
        )


# ============================================================
# DASHBOARD SUMMARY
# ============================================================

@app.get("/dashboard")
def dashboard():

    if not client:

        raise HTTPException(
            status_code=503,
            detail="ClickHouse is not available.",
        )

    try:

        total_result = client.query(
            """
            SELECT COUNT()
            FROM default.movies
            """
        )

        revenue_result = client.query(
            """
            SELECT title, revenue
            FROM default.movies
            ORDER BY revenue DESC
            LIMIT 1
            """
        )

        rating_result = client.query(
            """
            SELECT title, rating
            FROM default.movies
            ORDER BY rating DESC
            LIMIT 1
            """
        )

        average_result = client.query(
            """
            SELECT AVG(rating)
            FROM default.movies
            """
        )

        return {
            "success": True,

            "total_movies": format_value(
                total_result.result_set[0][0]
            ),

            "top_revenue": {
                "title": format_value(
                    revenue_result.result_set[0][0]
                ),
                "revenue": format_value(
                    revenue_result.result_set[0][1]
                ),
            },

            "top_rated": {
                "title": format_value(
                    rating_result.result_set[0][0]
                ),
                "rating": format_value(
                    rating_result.result_set[0][1]
                ),
            },

            "average_rating": format_value(
                average_result.result_set[0][0]
            ),
        }

    except Exception as error:

        print()
        print("DASHBOARD ERROR:")

        traceback.print_exc()

        raise HTTPException(
            status_code=500,
            detail=f"Dashboard failed: {error}",
        )


# ============================================================
# HISTORY
# ============================================================

history = []


@app.get("/history")
def get_history():

    return {
        "success": True,
        "history": history,
    }


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
# HEALTH CHECK
# ============================================================

@app.get("/health")
def health():

    clickhouse_ok = False

    try:

        if not client:

            return {
                "status": "error",
                "clickhouse": False,
                "gemini": bool(gemini),
                "model": MODEL,
                "fallback": True,
                "message": "ClickHouse client is not initialized.",
            }

        result = client.query(
            "SELECT 1"
        )

        clickhouse_ok = (
            result.result_set[0][0] == 1
        )

    except Exception as error:

        print()
        print("HEALTH CHECK ERROR:")

        traceback.print_exc()

        return {
            "status": "error",
            "clickhouse": False,
            "gemini": bool(gemini),
            "model": MODEL,
            "fallback": True,
            "message": str(error),
        }

    return {
        "status": "healthy" if clickhouse_ok else "error",
        "clickhouse": clickhouse_ok,
        "gemini": bool(gemini),
        "model": MODEL,
        "fallback": True,
    }
````
