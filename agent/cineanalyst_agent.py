import os
import re

import clickhouse_connect
from dotenv import load_dotenv
from google import genai


# ============================================================
# 1. ENVIRONMENT
# ============================================================

load_dotenv()


# ============================================================
# 2. CLICKHOUSE CONNECTION
# ============================================================

CLICKHOUSE_HOST = os.getenv("CLICKHOUSE_HOST")
CLICKHOUSE_PORT = int(os.getenv("CLICKHOUSE_PORT", "8443"))
CLICKHOUSE_USER = os.getenv("CLICKHOUSE_USER", "default")
CLICKHOUSE_PASSWORD = os.getenv("CLICKHOUSE_PASSWORD")
CLICKHOUSE_DATABASE = os.getenv("CLICKHOUSE_DATABASE", "default")


if not CLICKHOUSE_HOST:
    raise ValueError("CLICKHOUSE_HOST is missing from .env")

if not CLICKHOUSE_PASSWORD:
    raise ValueError("CLICKHOUSE_PASSWORD is missing from .env")


client = clickhouse_connect.get_client(
    host=CLICKHOUSE_HOST,
    port=CLICKHOUSE_PORT,
    username=CLICKHOUSE_USER,
    password=CLICKHOUSE_PASSWORD,
    database=CLICKHOUSE_DATABASE,
    secure=True,
)


# ============================================================
# 3. GEMINI CONNECTION
# ============================================================

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is missing from .env")


gemini = genai.Client(
    api_key=GEMINI_API_KEY
)


# ============================================================
# 4. FIND AVAILABLE GEMINI MODEL
# ============================================================

def get_available_model():
    """
    Finds a Gemini model available for the current API key.
    """

    preferred_models = [
        "models/gemini-3.5-flash",
        "models/gemini-3.5-flash-lite",
        "models/gemini-3.1-flash",
        "models/gemini-3.1-flash-lite",
        "models/gemini-3-flash",
        "models/gemini-2.5-flash-lite",
    ]

    available_models = {}

    for model in gemini.models.list():

        name = getattr(model, "name", "")

        supported_actions = getattr(
            model,
            "supported_actions",
            []
        ) or []

        if "generateContent" in supported_actions:
            available_models[name] = model

    # Try preferred models first
    for model_name in preferred_models:

        if model_name in available_models:
            return model_name

    # Otherwise use the first compatible model
    if available_models:
        return next(iter(available_models))

    raise RuntimeError(
        "No Gemini model supporting generateContent "
        "is available for this API key."
    )


MODEL = get_available_model()

print()
print(f"Gemini model selected: {MODEL}")


# ============================================================
# 5. DATABASE SCHEMA
# ============================================================

DATABASE_SCHEMA = """
Database: default

Table: default.movies

Columns:

id
title
genre
release_year
rating
revenue
country
"""


# ============================================================
# 6. GENERATE SQL
# ============================================================

def generate_sql(question):

    prompt = f"""
You are CineAnalyst, an AI movie database analyst.

Your task is to convert a user's natural-language question
into ONE valid ClickHouse SQL SELECT query.

{DATABASE_SCHEMA}

IMPORTANT RULES:

1. Return ONLY SQL.
2. The SQL must start with SELECT.
3. Only SELECT queries are allowed.
4. Never use INSERT.
5. Never use UPDATE.
6. Never use DELETE.
7. Never use DROP.
8. Never use ALTER.
9. Never use CREATE.
10. Never use TRUNCATE.
11. Always use default.movies.
12. Use ClickHouse-compatible SQL.
13. Do not return Markdown.
14. Do not explain the SQL.
15. Use COUNT() for counting rows.
16. Use AVG() for averages.
17. Use SUM() for totals.
18. Use ORDER BY for rankings.
19. Use LIMIT when appropriate.
20. For USA, use country = 'USA'.
21. For highest rating, use rating DESC.
22. For highest revenue, use revenue DESC.

EXAMPLES:

Question:
What is the highest-rated movie?

SQL:
SELECT title, rating
FROM default.movies
ORDER BY rating DESC
LIMIT 1


Question:
Which movie generated the most revenue?

SQL:
SELECT title, revenue
FROM default.movies
ORDER BY revenue DESC
LIMIT 1


Question:
How many movies are from USA?

SQL:
SELECT COUNT()
FROM default.movies
WHERE country = 'USA'


Question:
Which movies were released after 2000?

SQL:
SELECT title, release_year
FROM default.movies
WHERE release_year > 2000
ORDER BY release_year ASC


Question:
What is the average rating of Sci-Fi movies?

SQL:
SELECT AVG(rating)
FROM default.movies
WHERE genre = 'Sci-Fi'


USER QUESTION:
{question}
"""

    response = gemini.models.generate_content(
        model=MODEL,
        contents=prompt,
    )

    sql = response.text.strip()

    # Remove Markdown code fences
    sql = re.sub(
        r"^```sql\s*",
        "",
        sql,
        flags=re.IGNORECASE
    )

    sql = re.sub(
        r"^```\s*",
        "",
        sql
    )

    sql = re.sub(
        r"\s*```$",
        "",
        sql
    )

    return sql.strip()


# ============================================================
# 7. SQL SECURITY
# ============================================================

def validate_sql(sql):

    sql_clean = sql.strip()

    if not sql_clean:
        raise ValueError("Gemini returned an empty SQL query.")

    if not sql_clean.upper().startswith("SELECT"):
        raise ValueError(
            "Security error: only SELECT queries are allowed."
        )

    forbidden_keywords = [
        "INSERT ",
        "UPDATE ",
        "DELETE ",
        "DROP ",
        "ALTER ",
        "CREATE ",
        "TRUNCATE ",
        "OPTIMIZE ",
        "GRANT ",
        "REVOKE ",
    ]

    sql_upper = sql_clean.upper()

    for keyword in forbidden_keywords:

        if keyword in sql_upper:
            raise ValueError(
                f"Security error: forbidden SQL command "
                f"{keyword.strip()}"
            )


# ============================================================
# 8. FORMAT VALUES
# ============================================================

def format_value(value):

    if value is None:
        return "N/A"

    if isinstance(value, float):

        # Avoid ugly floating point values such as:
        # 9.300000190734863

        if value.is_integer():
            return f"{int(value):,}"

        return f"{value:.2f}"

    if isinstance(value, int):
        return f"{value:,}"

    return str(value)


# ============================================================
# 9. DISPLAY RESULTS
# ============================================================

def display_results(result):

    print()
    print("🎬 CineAnalyst Results")
    print("=" * 55)

    rows = result.result_set

    if not rows:

        print("No results found.")

        return

    for row in rows:

        # COUNT / AVG / SUM
        if len(row) == 1:

            print(
                f"📊 Result: {format_value(row[0])}"
            )

        # title + rating/revenue/year
        elif len(row) == 2:

            print(
                f"🎬 {format_value(row[0])}"
            )

            print(
                f"📊 {format_value(row[1])}"
            )

        # More columns
        else:

            for index, value in enumerate(row):

                print(
                    f"• {format_value(value)}"
                )

        print("-" * 55)


# ============================================================
# 10. ASK CINEANALYST
# ============================================================

def ask_cineanalyst(question):

    print()
    print("⏳ Analyzing your question...")

    # Generate SQL
    sql = generate_sql(question)

    print()
    print("Generated SQL:")
    print(sql)

    # Security validation
    validate_sql(sql)

    # Execute ClickHouse query
    result = client.query(sql)

    # Display result
    display_results(result)


# ============================================================
# 11. MAIN CHAT
# ============================================================

def main():

    print()
    print("=" * 60)
    print("🎬 CineAnalyst AI")
    print("=" * 60)

    print("✅ Connected to ClickHouse")
    print(f"🤖 Gemini model: {MODEL}")

    print()
    print("Ask questions about your movie database.")
    print("Languages: English / Français / العربية")
    print("Type 'exit' to quit.")

    print("=" * 60)

    while True:

        try:

            question = input(
                "\nAsk CineAnalyst: "
            ).strip()

        except KeyboardInterrupt:

            print("\n\nGoodbye! 👋")

            break

        except EOFError:

            print("\n\nGoodbye! 👋")

            break

        # Empty question
        if not question:
            continue

        # Exit
        if question.lower() in [
            "exit",
            "quit",
            "q"
        ]:

            print("\nGoodbye! 👋")

            break

        try:

            ask_cineanalyst(question)

        except Exception as error:

            print()
            print("❌ Error:")
            print(error)


# ============================================================
# 12. START
# ============================================================

if __name__ == "__main__":
    main()
