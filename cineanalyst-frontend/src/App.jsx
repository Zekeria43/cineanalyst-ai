import { useEffect, useMemo, useState } from "react";
import "./App.css";

const API_URL = "https://cineanalyst-ai.onrender.com";

const quickQuestions = [
  "Which movie generated the most revenue?",
  "What is the highest-rated movie?",
  "How many movies are in the database?",
  "What is the average rating of all movies?",
  "How many movies are from USA?",
  "Which movies were released after 2000?",
];

// ==========================================================
// HELPERS
// ==========================================================

function formatMoney(value) {
  if (value === null || value === undefined) return "—";

  const number = Number(value);

  if (Number.isNaN(number)) return "—";

  if (number >= 1_000_000_000) {
    return `$${(number / 1_000_000_000).toFixed(2)}B`;
  }

  if (number >= 1_000_000) {
    return `$${(number / 1_000_000).toFixed(1)}M`;
  }

  if (number >= 1_000) {
    return `$${(number / 1_000).toFixed(0)}K`;
  }

  return `$${number.toLocaleString()}`;
}

function formatNumber(value) {
  if (value === null || value === undefined) return "—";

  const number = Number(value);

  if (Number.isNaN(number)) return "—";

  return number.toLocaleString();
}

// ==========================================================
// API FETCH WITH TIMEOUT
// ==========================================================

async function fetchWithTimeout(url, options = {}, timeout = 15000) {
  const controller = new AbortController();

  const timer = setTimeout(() => {
    controller.abort();
  }, timeout);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal,
    });

    return response;
  } catch (error) {
    if (error.name === "AbortError") {
      throw new Error("API timeout");
    }

    throw error;
  } finally {
    clearTimeout(timer);
  }
}

// ==========================================================
// APP
// ==========================================================

function App() {
  const [page, setPage] = useState("dashboard");

  const [movies, setMovies] = useState([]);
  const [history, setHistory] = useState([]);

  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  const [question, setQuestion] = useState("");
  const [answer, setAnswer] = useState(null);
  const [asking, setAsking] = useState(false);
  const [askError, setAskError] = useState("");

  // ==========================================================
  // LOAD MOVIES
  // ==========================================================

  async function loadMovies() {
    setLoading(true);
    setError("");

    try {
      console.log("=================================");
      console.log("🎬 CineAnalyst API");
      console.log("API URL:", API_URL);
      console.log("Movies URL:", `${API_URL}/movies`);
      console.log("=================================");

      const response = await fetchWithTimeout(
        `${API_URL}/movies`,
        {
          method: "GET",
          headers: {
            Accept: "application/json",
          },
        },
        15000
      );

      console.log("Movies HTTP status:", response.status);
      console.log("Movies HTTP OK:", response.ok);

      if (!response.ok) {
        throw new Error(`HTTP ${response.status}`);
      }

      const data = await response.json();

      console.log("Movies response:", data);

      if (!data.success) {
        throw new Error("Backend returned success=false");
      }

      const loadedMovies = data.movies || [];

      setMovies(loadedMovies);

      console.log(
        `✅ ${loadedMovies.length} movies loaded successfully`
      );

      return true;
    } catch (err) {
      console.error("❌ MOVIES ERROR:", err);

      let message = err.message || "Unknown error";

      if (err.name === "AbortError") {
        message = "API timeout";
      }

      setError(
        `Impossible de charger les films. ${message}`
      );

      throw err;
    } finally {
      setLoading(false);
    }
  }

  // ==========================================================
  // LOAD HISTORY
  // ==========================================================

  async function loadHistory() {
    try {
      console.log("Loading history...");

      const response = await fetchWithTimeout(
        `${API_URL}/history`,
        {
          method: "GET",
          headers: {
            Accept: "application/json",
          },
        },
        15000
      );

      console.log(
        "History HTTP status:",
        response.status
      );

      if (!response.ok) {
        console.log(
          "History endpoint unavailable."
        );

        return;
      }

      const data = await response.json();

      console.log("History response:", data);

      if (data.success) {
        setHistory(data.history || []);
      }
    } catch (err) {
      console.log(
        "History unavailable:",
        err.message
      );
    }
  }

  // ==========================================================
  // INITIAL LOAD WITH RETRY
  // ==========================================================

  useEffect(() => {
    let cancelled = false;

    async function initializeApp() {
      const maxAttempts = 5;

      for (
        let attempt = 1;
        attempt <= maxAttempts;
        attempt++
      ) {
        if (cancelled) return;

        try {
          console.log(
            `🚀 CineAnalyst initialization attempt ${attempt}/${maxAttempts}`
          );

          await loadMovies();

          if (cancelled) return;

          await loadHistory();

          if (cancelled) return;

          console.log(
            "✅ CineAnalyst initialized successfully"
          );

          return;
        } catch (err) {
          console.error(
            `❌ Initialization attempt ${attempt} failed:`,
            err
          );

          if (
            attempt < maxAttempts &&
            !cancelled
          ) {
            const delay = Math.min(
              1000 * attempt,
              5000
            );

            console.log(
              `⏳ Retrying in ${delay / 1000}s...`
            );

            await new Promise((resolve) =>
              setTimeout(resolve, delay)
            );
          }
        }
      }

      if (!cancelled) {
        console.error(
          "❌ CineAnalyst API unavailable after all attempts."
        );
      }
    }

    initializeApp();

    return () => {
      cancelled = true;
    };
  }, []);

  // ==========================================================
  // ONLINE EVENT
  // ==========================================================

  useEffect(() => {
    async function handleOnline() {
      console.log(
        "🌐 Internet connection restored."
      );

      try {
        await loadMovies();
        await loadHistory();
      } catch (error) {
        console.error(
          "Online reload failed:",
          error
        );
      }
    }

    window.addEventListener(
      "online",
      handleOnline
    );

    return () => {
      window.removeEventListener(
        "online",
        handleOnline
      );
    };
  }, []);

  // ==========================================================
  // ASK AI
  // ==========================================================

  async function askQuestion(customQuestion = null) {
    const finalQuestion = (
      customQuestion !== null
        ? customQuestion
        : question
    ).trim();

    if (!finalQuestion) {
      setAskError(
        "Please enter a question."
      );

      return;
    }

    try {
      setAsking(true);
      setAskError("");
      setAnswer(null);

      console.log(
        "🤖 ASK QUESTION:",
        finalQuestion
      );

      const response = await fetchWithTimeout(
        `${API_URL}/ask`,
        {
          method: "POST",

          headers: {
            Accept: "application/json",
            "Content-Type": "application/json",
          },

          body: JSON.stringify({
            question: finalQuestion,
          }),
        },
        60000
      );

      console.log(
        "ASK HTTP STATUS:",
        response.status
      );

      let data;

      try {
        data = await response.json();
      } catch {
        throw new Error(
          "Invalid response from API."
        );
      }

      console.log(
        "ASK RESPONSE:",
        data
      );

      if (!response.ok) {
        const message =
          data?.detail?.message ||
          data?.detail ||
          data?.message ||
          `HTTP ${response.status}`;

        throw new Error(message);
      }

      setAnswer(data);

      setHistory((previous) => [
        {
          question:
            data.question ||
            finalQuestion,

          sql: data.sql,

          sql_source:
            data.sql_source,

          columns:
            data.columns || [],

          results:
            data.results || data.rows || [],
        },

        ...previous,
      ]);
    } catch (err) {
      console.error(
        "❌ ASK ERROR:",
        err
      );

      setAskError(
        err.message ||
          "Unable to process the question."
      );
    } finally {
      setAsking(false);
    }
  }

  // ==========================================================
  // NAVIGATION
  // ==========================================================

  function navigate(target) {
    setPage(target);
    setError("");
    setAskError("");
  }

  // ==========================================================
  // MANUAL REFRESH
  // ==========================================================

  async function handleRefresh() {
    try {
      await loadMovies();
    } catch (error) {
      console.error(
        "Manual refresh failed:",
        error
      );
    }
  }

  // ==========================================================
  // STATISTICS
  // ==========================================================

  const statistics = useMemo(() => {
    if (!movies.length) {
      return {
        total: 0,
        topRevenue: null,
        topRated: null,
        averageRating: 0,
      };
    }

    const topRevenue = [...movies].sort(
      (a, b) =>
        Number(b.revenue || 0) -
        Number(a.revenue || 0)
    )[0];

    const topRated = [...movies].sort(
      (a, b) =>
        Number(b.rating || 0) -
        Number(a.rating || 0)
    )[0];

    const ratings = movies
      .map((movie) =>
        Number(movie.rating)
      )
      .filter(
        (rating) =>
          !Number.isNaN(rating)
      );

    const averageRating =
      ratings.length > 0
        ? ratings.reduce(
            (sum, rating) =>
              sum + rating,
            0
          ) / ratings.length
        : 0;

    return {
      total: movies.length,
      topRevenue,
      topRated,
      averageRating,
    };
  }, [movies]);

  // ==========================================================
  // DASHBOARD
  // ==========================================================

  function Dashboard() {
    return (
      <main className="main-content">

        <div className="page-header">

          <div>
            <h1>Dashboard</h1>

            <p>
              Overview of your movie database
            </p>
          </div>

          <button
            className="refresh-button"
            onClick={handleRefresh}
            disabled={loading}
          >
            {loading
              ? "↻ Loading..."
              : "↻ Refresh"}
          </button>

        </div>

        {error && (
          <div className="error-banner">
            ⚠ {error}
          </div>
        )}

        <section className="hero-card">

          <div className="hero-label">
            MOVIE DATA INTELLIGENCE
          </div>

          <h2>
            Welcome to CineAnalyst AI
          </h2>

          <p>
            Explore your movie database using
            natural language and AI-powered
            SQL analytics.
          </p>

          <button
            className="primary-button"
            onClick={() =>
              navigate("ask")
            }
          >
            Ask a question →
          </button>

        </section>

        <section className="stats-grid">

          <StatCard
            icon="🎬"
            title="Total Movies"
            value={
              loading
                ? "..."
                : formatNumber(
                    statistics.total
                  )
            }
            subtitle="Movies in database"
          />

          <StatCard
            icon="💰"
            title="Top Revenue"
            value={
              statistics.topRevenue
                ? formatMoney(
                    statistics.topRevenue
                      .revenue
                  )
                : "—"
            }
            subtitle={
              statistics.topRevenue?.title ||
              "Highest revenue"
            }
          />

          <StatCard
            icon="⭐"
            title="Top Rated"
            value={
              statistics.topRated
                ? statistics.topRated.rating
                : "—"
            }
            subtitle={
              statistics.topRated?.title ||
              "Highest rating"
            }
          />

          <StatCard
            icon="📊"
            title="Average Rating"
            value={
              statistics.averageRating
                ? statistics.averageRating.toFixed(
                    2
                  )
                : "—"
            }
            subtitle="Average movie rating"
          />

        </section>

        <section className="content-card">

          <div className="section-header">

            <div>
              <h2>Movies</h2>

              <p>
                {movies.length} movies loaded
                from ClickHouse
              </p>
            </div>

          </div>

          {loading ? (
            <div className="loading">
              Loading movies...
            </div>
          ) : movies.length === 0 ? (
            <div className="empty-state">
              No movies found.
            </div>
          ) : (
            <MovieTable
              movies={movies}
            />
          )}

        </section>

      </main>
    );
  }

  // ==========================================================
  // ASK PAGE
  // ==========================================================

  function AskPage() {
    return (
      <main className="main-content">

        <div className="page-header">

          <div>
            <h1>
              Ask CineAnalyst AI
            </h1>

            <p>
              Ask questions about your movie
              database in natural language.
            </p>
          </div>

        </div>

        <section className="content-card ask-card">

          <div className="ask-input-row">

            <input
              type="text"
              value={question}
              onChange={(event) =>
                setQuestion(
                  event.target.value
                )
              }
              onKeyDown={(event) => {
                if (
                  event.key === "Enter" &&
                  !asking
                ) {
                  askQuestion();
                }
              }}
              placeholder="Example: Which movie generated the most revenue?"
              disabled={asking}
            />

            <button
              className="primary-button"
              onClick={() =>
                askQuestion()
              }
              disabled={asking}
            >
              {asking
                ? "Analyzing..."
                : "Ask AI"}
            </button>

          </div>

          <div className="quick-questions">

            <h3>
              Quick questions
            </h3>

            <div className="quick-grid">

              {quickQuestions.map(
                (item) => (
                  <button
                    key={item}
                    className="quick-button"
                    onClick={() => {
                      setQuestion(item);
                      askQuestion(item);
                    }}
                    disabled={asking}
                  >
                    {item}
                  </button>
                )
              )}

            </div>

          </div>

          {askError && (
            <div className="error-banner">
              ⚠ {askError}
            </div>
          )}

          {answer && (
            <AnswerCard
              answer={answer}
            />
          )}

        </section>

      </main>
    );
  }

  // ==========================================================
  // HISTORY PAGE
  // ==========================================================

  function HistoryPage() {
    return (
      <main className="main-content">

        <div className="page-header">

          <div>
            <h1>History</h1>

            <p>
              Previous questions and
              generated SQL.
            </p>
          </div>

        </div>

        <section className="content-card">

          {history.length === 0 ? (
            <div className="empty-state">
              No questions yet.
            </div>
          ) : (
            <div className="history-list">

              {history.map(
                (item, index) => (

                  <div
                    className="history-item"
                    key={`${item.question}-${index}`}
                  >

                    <h3>
                      {item.question}
                    </h3>

                    {item.sql && (
                      <pre>
                        {item.sql}
                      </pre>
                    )}

                    {item.results && (
                      <div className="history-result">

                        {item.results.map(
                          (
                            row,
                            rowIndex
                          ) => (

                            <div
                              key={
                                rowIndex
                              }
                            >

                              {Array.isArray(
                                row
                              )
                                ? row.map(
                                    (
                                      value,
                                      columnIndex
                                    ) => (
                                      <span
                                        key={
                                          columnIndex
                                        }
                                      >
                                        {String(
                                          value
                                        )}
                                      </span>
                                    )
                                  )
                                : (
                                    <span>
                                      {JSON.stringify(
                                        row
                                      )}
                                    </span>
                                  )}

                            </div>

                          )
                        )}

                      </div>
                    )}

                  </div>

                )
              )}

            </div>
          )}

        </section>

      </main>
    );
  }

  // ==========================================================
  // APP LAYOUT
  // ==========================================================

  return (
    <div className="app">

      <aside className="sidebar">

        <div className="logo">

          <div className="logo-icon">
            🎬
          </div>

          <div>
            <strong>
              CineAnalyst
            </strong>

            <span>
              AI
            </span>
          </div>

        </div>

        <nav>

          <button
            className={
              page === "dashboard"
                ? "nav-item active"
                : "nav-item"
            }
            onClick={() =>
              navigate("dashboard")
            }
          >
            <span>📊</span>
            Dashboard
          </button>

          <button
            className={
              page === "ask"
                ? "nav-item active"
                : "nav-item"
            }
            onClick={() =>
              navigate("ask")
            }
          >
            <span>🤖</span>
            Ask AI
          </button>

          <button
            className={
              page === "history"
                ? "nav-item active"
                : "nav-item"
            }
            onClick={() =>
              navigate("history")
            }
          >
            <span>🕘</span>
            History
          </button>

        </nav>

        <div className="sidebar-status">

          <div className="status-dot"></div>

          <div>
            <strong>
              Backend Online
            </strong>

            <small>
              Render API
            </small>
          </div>

        </div>

      </aside>

      <div className="page-container">

        {page === "dashboard" && (
          <Dashboard />
        )}

        {page === "ask" && (
          <AskPage />
        )}

        {page === "history" && (
          <HistoryPage />
        )}

      </div>

    </div>
  );
}

// ==========================================================
// STAT CARD
// ==========================================================

function StatCard({
  icon,
  title,
  value,
  subtitle,
}) {
  return (
    <div className="stat-card">

      <div className="stat-icon">
        {icon}
      </div>

      <div className="stat-content">

        <span>
          {title}
        </span>

        <strong>
          {value}
        </strong>

        <small>
          {subtitle}
        </small>

      </div>

    </div>
  );
}

// ==========================================================
// MOVIE TABLE
// ==========================================================

function MovieTable({ movies }) {
  return (
    <div className="table-wrapper">

      <table>

        <thead>

          <tr>
            <th>Movie</th>
            <th>Revenue</th>
            <th>Rating</th>
            <th>Country</th>
            <th>Genre</th>
            <th>Year</th>
          </tr>

        </thead>

        <tbody>

          {movies.map(
            (movie, index) => (

              <tr
                key={`${movie.title}-${index}`}
              >

                <td>
                  <strong>
                    {movie.title}
                  </strong>
                </td>

                <td>
                  {formatMoney(
                    movie.revenue
                  )}
                </td>

                <td>
                  ⭐ {movie.rating}
                </td>

                <td>
                  {movie.country || "—"}
                </td>

                <td>
                  {movie.genre || "—"}
                </td>

                <td>
                  {movie.release_year ||
                    "—"}
                </td>

              </tr>

            )
          )}

        </tbody>

      </table>

    </div>
  );
}

// ==========================================================
// ANSWER CARD
// ==========================================================

function AnswerCard({ answer }) {
  const results =
    answer.results ||
    answer.rows ||
    [];

  return (
    <div className="answer-card">

      <div className="answer-header">

        <div>

          <span className="answer-label">
            AI ANALYSIS
          </span>

          <h2>
            {answer.question}
          </h2>

        </div>

        <span className="source-badge">
          {answer.sql_source || "AI"}
        </span>

      </div>

      {answer.sql && (
        <div className="sql-section">

          <h3>
            Generated SQL
          </h3>

          <pre>
            {answer.sql}
          </pre>

        </div>
      )}

      <div className="result-section">

        <h3>
          Results
        </h3>

        {results.length ? (

          <div className="table-wrapper">

            <table>

              <thead>

                <tr>

                  {answer.columns?.map(
                    (column) => (
                      <th key={column}>
                        {column}
                      </th>
                    )
                  )}

                </tr>

              </thead>

              <tbody>

                {results.map(
                  (row, rowIndex) => (

                    <tr
                      key={rowIndex}
                    >

                      {Array.isArray(row)
                        ? row.map(
                            (
                              value,
                              columnIndex
                            ) => (
                              <td
                                key={
                                  columnIndex
                                }
                              >
                                {typeof value ===
                                "number"
                                  ? value.toLocaleString()
                                  : String(
                                      value ??
                                        "—"
                                    )}
                              </td>
                            )
                          )
                        : Object.values(
                            row || {}
                          ).map(
                            (
                              value,
                              columnIndex
                            ) => (
                              <td
                                key={
                                  columnIndex
                                }
                              >
                                {String(
                                  value ??
                                    "—"
                                )}
                              </td>
                            )
                          )}

                    </tr>

                  )
                )}

              </tbody>

            </table>

          </div>

        ) : (

          <div className="empty-state">
            No results returned.
          </div>

        )}

      </div>

    </div>
  );
}

export default App;