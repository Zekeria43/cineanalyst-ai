import os
import re
import traceback
from typing import Optional

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://localhost:5174",
        "http://localhost:5175",
        "http://localhost:5176",
        "http://localhost:5177",
        "http://localhost:5178",
        "http://localhost:5179",
        "http://localhost:5180",
        "http://127.0.0.1:5173",
        "http://127.0.0.1:5174",
        "http://127.0.0.1:5175",
        "http://127.0.0.1:5176",
        "http://127.0.0.1:5177",
        "http://127.0.0.1:5178",
        "http://127.0.0.1:5179",
        "http://127.0.0.1:5180",
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

MODEL = os.getenv(
    "GEMINI_MODEL",
    "gemini-3.6-flash",
)


# ============================================================
# ENV CHECK
# ============================================================

if not CLICKHOUSE_HOST:
    raise RuntimeError("CLICKHOUSE_HOST is missing from .env")

if not CLICKHOUSE_PASSWORD:
    raise RuntimeError("CLICKHOUSE_PASSWORD is missing from .env")

if not GEMINI_API_KEY:
    raise RuntimeError("GEMINI_API_KEY is missing from .env")


# ============================================================
# CLICKHOUSE CONNECTION
# ============================================================

try:
    client = clickhouse_connect.get_client(
        host=CLICKHOUSE_HOST,
        port=CLICKHOUSE_PORT,
        username=CLICKHOUSE_USER,
        password=CLICKHOUSE_PASSWORD,
        database=CLICKHOUSE_DATABASE,
        secure=True,
    )

    print("ClickHouse connection: OK")

except Exception as error:
    print("CLICKHOUSE CONNECTION ERROR:")
    traceback.print_exc()

    raise RuntimeError(
        f"ClickHouse connection failed: {error}"
    )


# ============================================================
# GEMINI CLIENT
# ============================================================

try:
    gemini = genai.Client(
        api_key=GEMINI_API_KEY
    )

    print("Gemini client: OK")

except Exception as error:
    print("GEMINI CLIENT ERROR:")
    traceback.print_exc()

    raise RuntimeError(
        f"Gemini client initialization failed: {error}"
    )


# ============================================================
# REQUEST MODEL
# ============================================================

class QuestionRequest(BaseModel):
    question: str


# ============================================================
# FALLBACK SQL
# ============================================================

def fallback_sql(question: str) -> Optional[str]:

    q = question.lower().strip()

    # --------------------------------------------------------
    # MOST REVENUE
    # --------------------------------------------------------

    if (
        "most revenue" in q
        or "highest revenue" in q
        or "top revenue" in q
        or (
            "revenue" in q
            and (
                "most" in q
                or "highest" in q
                or "maximum" in q
                or "max" in q
            )
        )
    ):
        return """
SELECT title, revenue
FROM default.movies
ORDER BY revenue DESC
LIMIT 1
""".strip()

    # --------------------------------------------------------
    # HIGHEST RATING
    # --------------------------------------------------------

    if (
        "highest rated" in q
        or "highest rating" in q
        or "best rated" in q
        or "best movie" in q
        or (
            "rating" in q
            and (
                "highest" in q
                or "best" in q
                or "maximum" in q
            )
        )
    ):
        return """
SELECT title, rating
FROM default.movies
ORDER BY rating DESC
LIMIT 1
""".strip()

    # --------------------------------------------------------
    # COUNT MOVIES
    # --------------------------------------------------------

    if (
        "how many movies" in q
        or "number of movies" in q
        or "count of movies" in q
        or "total movies" in q
        or "how many films" in q
        or "number of films" in q
    ):
        return """
SELECT COUNT()
FROM default.movies
""".strip()

    # --------------------------------------------------------
    # AVERAGE RATING
    # --------------------------------------------------------

    if (
        "average rating" in q
        or "avg rating" in q
        or "mean rating" in q
        or "average movie rating" in q
    ):
        return """
SELECT AVG(rating)
FROM default.movies
""".strip()

    # --------------------------------------------------------
    # MOVIES AFTER 2000
    # --------------------------------------------------------

    if (
        "movies after 2000" in q
        or "films after 2000" in q
        or "released after 2000" in q
    ):
        return """
SELECT title, release_year
FROM default.movies
WHERE release_year > 2000
ORDER BY release_year ASC
""".strip()

    # --------------------------------------------------------
    # USA MOVIES
    # --------------------------------------------------------

    if (
        "movies from usa" in q
        or "movies from the usa" in q
        or "films from usa" in q
        or (
            "usa" in q
            and (
                "how many" in q
                or "count" in q
            )
        )
    ):
        return """
SELECT COUNT()
FROM default.movies
WHERE country = 'USA'
""".strip()

    # --------------------------------------------------------
    # TOP 5 REVENUE
    # --------------------------------------------------------

    if (
        "top 5 revenue" in q
        or "top five revenue" in q
        or "five highest revenue" in q
    ):
        return """
SELECT title, revenue
FROM default.movies
ORDER BY revenue DESC
LIMIT 5
""".strip()

    # --------------------------------------------------------
    # TOP 5 RATING
    # --------------------------------------------------------

    if (
        "top 5 rated" in q
        or "top five rated" in q
        or "five highest rated" in q
    ):
        return """
SELECT title, rating
FROM default.movies
ORDER BY rating DESC
LIMIT 5
""".strip()

    # --------------------------------------------------------
    # SCI-FI AVERAGE
    # --------------------------------------------------------

    if (
        "average rating of sci-fi" in q
        or "average rating of sci fi" in q
        or "average rating for sci-fi" in q
    ):
        return """
SELECT AVG(rating)
FROM default.movies
WHERE genre = 'Sci-Fi'
""".strip()

    # --------------------------------------------------------
    # RETURN NONE IF UNKNOWN
    # --------------------------------------------------------

    return None


# ============================================================
# GENERATE SQL WITH GEMINI
# ============================================================

def generate_sql(question: str) -> str:

    prompt = f"""
You are CineAnalyst AI.

Your job is to convert natural language questions
into ClickHouse SQL queries.

DATABASE:

default.movies

AVAILABLE COLUMNS:

title
revenue
rating
country
genre
release_year

IMPORTANT RULES:

1. Return SQL only.
2. Do not use Markdown.
3. Do not use ```sql.
4. Only SELECT queries are allowed.
5. Never use INSERT.
6. Never use UPDATE.
7. Never use DELETE.
8. Never use DROP.
9. Never use ALTER.
10. Never use CREATE.
11. Never use TRUNCATE.
12. Never use OPTIMIZE.
13. Never use GRANT.
14. Never use REVOKE.
15. Use ClickHouse SQL syntax.
16. Use default.movies as the table.
17. Use COUNT() for counting.
18. Use AVG() for averages.
19. Use SUM() for totals.
20. Use ORDER BY for rankings.
21. Use LIMIT when appropriate.
22. For highest rating use rating DESC.
23. For highest revenue use revenue DESC.
24. For USA use country = 'USA'.

EXAMPLE 1:

Question:
What is the highest-rated movie?

SQL:
SELECT title, rating
FROM default.movies
ORDER BY rating DESC
LIMIT 1

EXAMPLE 2:

Question:
Which movie generated the most revenue?

SQL:
SELECT title, revenue
FROM default.movies
ORDER BY revenue DESC
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
                    "message": "Gemini is unavailable and no local fallback matches this question.",
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
            "gemini": True,
            "model": MODEL,
            "message": str(error),
        }

    return {
        "status": "healthy",
        "clickhouse": clickhouse_ok,
        "gemini": True,
        "model": MODEL,
        "fallback": True,
    }