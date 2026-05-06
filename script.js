const BACKEND_URL = "http://127.0.0.1:8000";
const statusEl = document.getElementById("status");
const resultsEl = document.getElementById("results");
const summaryEl = document.getElementById("summary");
const highlightsEl = document.getElementById("highlights");
const recommendationsEl = document.getElementById("recommendations");
const scoreEl = document.getElementById("score");
const ratingEl = document.getElementById("rating");
const outputEl = document.getElementById("output");
const analyzeBtn = document.getElementById("analyzeBtn");

async function upload() {
  const file = document.getElementById("file").files[0];
  const text = document.getElementById("policyText").value.trim();

  if (!file && !text) {
    return showStatus("Select a PDF/text file or paste policy text to analyze.", "warning");
  }

  showStatus(file ? "Analyzing uploaded file..." : "Analyzing pasted text...", "info");
  toggleResults(false);

  try {
    let res;
    if (file) {
      const formData = new FormData();
      formData.append("file", file);
      res = await fetch(`${BACKEND_URL}/analyze`, {
        method: "POST",
        body: formData,
      });
    } else {
      res = await fetch(`${BACKEND_URL}/analyze-text`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ text }),
      });
    }

    if (!res.ok) {
      const text = await res.text();
      throw new Error(text || "Failed to analyze policy.");
    }

    const data = await res.json();
    renderResult(data);
    showStatus("Analysis complete.", "success");
  } catch (error) {
    showStatus(error.message || "Unable to analyze policy.", "error");
  } finally {
    setLoading(false);
  }
}

document.addEventListener("DOMContentLoaded", () => {
  const warningBanner = document.querySelector(".backend-warning");
  if (warningBanner && window.location.origin === BACKEND_URL) {
    warningBanner.style.display = "none";
  }
  checkBackendStatus();
});

async function checkBackendStatus() {
  setLoading(true);
  try {
    const res = await fetch(BACKEND_URL + "/", { method: "GET" });
    if (!res.ok) {
      throw new Error("Backend is not ready.");
    }
    showStatus("Backend is available. Paste a policy or upload a file to start.", "success");
    analyzeBtn.disabled = false;
  } catch (error) {
    showStatus("Backend unavailable. Start the server on 127.0.0.1:8000.", "error");
    analyzeBtn.disabled = true;
  } finally {
    setLoading(false);
  }
}

function setLoading(isLoading) {
  analyzeBtn.disabled = isLoading;
  analyzeBtn.textContent = isLoading ? "Analyzing..." : "Analyze Policy";
}

function showStatus(message, level = "info") {
  statusEl.textContent = message;
  statusEl.className = `status ${level}`;
}

function toggleResults(show) {
  resultsEl.classList.toggle("hidden", !show);
}

function renderResult(data) {
  const analysis = data.analysis || {};
  const summary = analysis.summary || analysis.simple_summary || "No summary returned.";
  const rawScore = analysis.risk_score ?? analysis.riskScore ?? analysis.score ?? "--";
  const score = typeof rawScore === "string" && !Number.isNaN(Number(rawScore)) ? Number(rawScore) : rawScore;
  const rating = analysis.rating || riskRating(score);
  const highlights = analysis.highlights || analysis.risks || [];
  const recommendations = analysis.recommendations || [];

  summaryEl.textContent = summary;
  scoreEl.textContent = typeof score === "number" ? score : score;
  ratingEl.textContent = rating;
  outputEl.textContent = JSON.stringify(data.analysis || data, null, 2);

  renderHighlights(highlights);
  renderRecommendations(recommendations);
  toggleResults(true);
}

function riskRating(score) {
  if (typeof score !== "number") return "Unknown";
  if (score >= 80) return "High risk";
  if (score >= 50) return "Medium risk";
  return "Low risk";
}

function renderHighlights(items) {
  if (!items.length) {
    highlightsEl.textContent = "No specific highlights found.";
    return;
  }

  highlightsEl.innerHTML = "";
  const list = document.createElement("div");
  list.className = "highlight-list";

  items.slice(0, 6).forEach((item) => {
    const clause = item.clause || item.description || item.concern || "Clause text unavailable.";
    const concern = item.concern || item.description || item.category || "Privacy concern.";
    const severity = item.severity || item.risk || "Medium";

    const card = document.createElement("div");
    card.className = `highlight-card ${severity.toLowerCase()}`;
    card.innerHTML = `
      <strong>${severity}</strong>
      <p>${concern}</p>
      <blockquote>${clause}</blockquote>
    `;
    list.appendChild(card);
  });

  highlightsEl.appendChild(list);
}

function renderRecommendations(items) {
  if (!items.length) {
    recommendationsEl.textContent = "No clear recommendations returned.";
    return;
  }

  recommendationsEl.innerHTML = items
    .map((item) => `<p>• ${item}</p>`)
    .join("");
}
