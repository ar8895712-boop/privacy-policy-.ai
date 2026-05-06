import json
from pathlib import Path
import os
try:
    from dotenv import load_dotenv
except ModuleNotFoundError:
    load_dotenv = None

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pypdf import PdfReader

try:
    from openai import OpenAI
except ModuleNotFoundError:
    OpenAI = None

if load_dotenv is not None:
    load_dotenv()
app = FastAPI()
openai_api_key = os.getenv("OPENAI_API_KEY")
client = None
if OpenAI is not None and openai_api_key:
    try:
        client = OpenAI(api_key=openai_api_key)
    except Exception:
        client = None

frontend_dir = Path(__file__).resolve().parent.parent / "frontend"

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def extract_policy_text(file: UploadFile) -> str:
    if file.content_type == "application/pdf" or file.filename.lower().endswith(".pdf"):
        reader = PdfReader(file.file)
        return "".join(page.extract_text() or "" for page in reader.pages)

    raw = file.file.read()
    try:
        return raw.decode("utf-8", errors="ignore")
    except Exception:
        return str(raw)


def build_prompt(policy_text: str) -> str:
    if len(policy_text) > 150_000:
        policy_text = policy_text[:150_000] + "\n\n...[truncated to fit]"

    return f"""
You are a privacy risk analyst. Read the policy text below and respond with a JSON object only.

Required JSON keys:
- summary: plain English summary of the most important privacy and data-risk issues.
- risk_score: integer from 0 to 100 where 100 is the highest privacy risk.
- risks: array of objects with fields: category, severity, description, clause.
- highlights: array of objects with fields: clause, concern, severity.
- recommendations: array of short user-facing actions or warnings.

Example format:
{{
  "summary": "...",
  "risk_score": 85,
  "risks": [{{"category": "Data Sharing", "severity": "High", "description": "...", "clause": "..."}}],
  "highlights": [{{"clause": "...", "concern": "...", "severity": "High"}}],
  "recommendations": ["Do not use this app if you care about location privacy."]
}}

Policy text:
{policy_text}
"""


def analyze_policy_text(policy_text: str) -> dict:
    if not policy_text or not policy_text.strip():
        raise HTTPException(status_code=400, detail="Policy text is empty.")

    if client is None:
        return {
            "analysis": build_demo_analysis(policy_text),
            "raw": "Demo mode active because OPENAI_API_KEY is not configured.",
        }

    prompt = build_prompt(policy_text)
    response = client.responses.create(
        model="gpt-4.1-mini",
        input=prompt,
        temperature=0.15,
        max_output_tokens=1200,
    )

    raw_output = getattr(response, "output_text", None)
    if raw_output is None:
        raw_output = "\n".join(
            segment.get("content", [{}])[0].get("text", "")
            for segment in getattr(response, "output", [])
        )

    analysis = None
    try:
        analysis = json.loads(raw_output)
    except json.JSONDecodeError:
        trimmed = raw_output[raw_output.find("{") :] if "{" in raw_output else raw_output
        try:
            analysis = json.loads(trimmed)
        except json.JSONDecodeError:
            analysis = None

    if analysis is None:
        return {
            "analysis": {
                "summary": "Unable to parse structured JSON from the policy analyzer.",
                "raw": raw_output,
            },
            "raw": raw_output,
        }

    return {"analysis": analysis, "raw": raw_output}


def build_demo_analysis(policy_text: str) -> dict:
    text = policy_text.lower()
    snippet = " ".join(policy_text.strip().replace("\n", " ").split()[:12])
    snippet = snippet[:120]

    seed = sum(ord(c) for c in text[:20]) % 40
    score = 20 + seed
    risks = []
    highlights = []
    recommendations = []

    def add_risk(category, severity, description, clause, concern, recommendation):
        risks.append({
            "category": category,
            "severity": severity,
            "description": description,
            "clause": clause,
        })
        highlights.append({
            "clause": clause,
            "concern": concern,
            "severity": severity,
        })
        recommendations.append(recommendation)

    if any(word in text for word in ["share", "third party", "partner", "advertiser", "advertising"]):
        score += 20
        add_risk(
            "Data Sharing",
            "High",
            "The policy mentions sharing data with external partners or advertisers.",
            "The service may share your data with third parties.",
            "Sharing data with third parties increases privacy risk.",
            "Avoid sharing personal data with unknown partners."
        )

    if any(word in text for word in ["retain", "store", "keep", "archive", "years"]):
        score += 15
        add_risk(
            "Data Retention",
            "Medium",
            "The policy appears to keep data for an extended period.",
            "The policy retains user data for long durations.",
            "Long retention increases the chance of stale or exposed data.",
            "Only keep data for as long as necessary."
        )

    if any(word in text for word in ["location", "gps", "location data"]):
        score += 15
        add_risk(
            "Location Privacy",
            "High",
            "The policy mentions collecting location data.",
            "Location or GPS data may be collected.",
            "Location tracking is especially sensitive.",
            "Be cautious about apps that collect precise location data."
        )

    if any(word in text for word in ["cookie", "tracking", "analytics"]):
        score += 10
        add_risk(
            "Tracking",
            "Medium",
            "The policy references cookies, tracking, or analytics.",
            "Cookies and tracking technologies may be used.",
            "Tracking can build a profile of your online behavior.",
            "Review tracking and cookie policies carefully."
        )

    if any(word in text for word in ["children", "minor"]):
        score += 10
        add_risk(
            "Children's Data",
            "Medium",
            "The policy mentions children or minors.",
            "The policy handles data for children or minors.",
            "Children's data requires extra legal protections.",
            "Verify that the service follows children's privacy rules."
        )

    if len(text) > 200 and not risks:
        score += 5
        recommendations.append("The policy is long and detailed, so check for hidden data-sharing terms.")

    if not risks:
        score = max(score - 10, 10)
        recommendations.append("This demo review found no strong risk indicators in the provided text.")

    summary = f"Demo analysis for input starting with: '{snippet}...'."
    if risks:
        summary = f"The policy text contains {len(risks)} risk indicator(s) and should be reviewed closely."
    elif "privacy" in text or "data" in text:
        summary = f"The policy text seems mostly informational with no strong risk terms."

    return {
        "summary": summary,
        "risk_score": min(score, 100),
        "risks": risks,
        "highlights": highlights,
        "recommendations": recommendations,
    }

@app.post("/analyze")
async def analyze(file: UploadFile = File(...)):
    policy_text = extract_policy_text(file)
    if not policy_text or not policy_text.strip():
        raise HTTPException(status_code=400, detail="Uploaded file contains no readable content.")
    return analyze_policy_text(policy_text)


@app.post("/analyze-text")
async def analyze_text(request: Request):
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Request body must be valid JSON.")

    text = payload.get("text")
    if text is None:
        raise HTTPException(status_code=400, detail="Provide text in the request body.")
    return analyze_policy_text(str(text))


app.mount("/", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
