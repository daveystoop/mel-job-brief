"""
Daily refresh for Mel's Job Brief.
Runs on GitHub Actions each morning:
  1. Claude searches the web for open psychology roles in Melbourne and scores them against Mel's profile
  2. A second, tool-free call turns those notes into clean JSON (much more reliable than one step)
  3. Writes docs/jobs.json, which the phone app reads
If anything goes wrong, yesterday's brief is left in place and the log says exactly why.
"""
import json, os, re, sys, datetime
import anthropic

MODEL = "claude-sonnet-5-5"
OUT = "docs/jobs.json"


def fail(msg):
    print("\n*** REFRESH FAILED ***\n" + msg + "\nYesterday's brief has been left in place.")
    sys.exit(1)


profile_text = os.environ.get("MEL_PROFILE", "").strip()
if not profile_text:
    fail("MEL_PROFILE secret is missing or empty. Add it in GitHub > Settings > Secrets and variables > Actions.")
if not os.environ.get("ANTHROPIC_API_KEY", "").strip():
    fail("ANTHROPIC_API_KEY secret is missing or empty.")

previous_urls = set()
try:
    with open(OUT) as f:
        previous_urls = {j.get("url") for j in json.load(f).get("jobs", [])}
except Exception:
    pass

today = datetime.date.today().strftime("%A %d %B %Y")
client = anthropic.Anthropic()


def call(**kw):
    try:
        return client.messages.create(model=MODEL, **kw)
    except anthropic.APIStatusError as e:
        hint = ""
        if e.status_code == 401: hint = " (API key is wrong or revoked)"
        elif e.status_code in (400, 402) and "credit" in str(e).lower(): hint = " (out of API credit: top up in the Anthropic Console)"
        elif e.status_code == 429: hint = " (rate limited: try again later)"
        elif e.status_code == 404: hint = f" (model '{MODEL}' not available to this key)"
        fail(f"Anthropic API error {e.status_code}{hint}:\n{e}")
    except anthropic.APIConnectionError as e:
        fail(f"Couldn't reach the Anthropic API: {e}")


# ---------- Step 1: search and score (free text) ----------
SEARCH_PROMPT = f"""Today is {today}. You are a job-search agent for a clinical psychologist in Melbourne, Australia.

Her profile (from her resume):
<profile>
{profile_text}
</profile>

Search the web for psychologist and clinical psychologist roles in Greater Melbourne that are open now and suit
what's on her resume. Cover SEEK, Indeed, LinkedIn, public health service careers pages (e.g. Northern, Austin,
Eastern, Mercy, RMH, Alfred, Monash, Western Health) and community mental health organisations.
Prefer individual job ads over search-results pages. Skip anything closed or outside Victoria
(telehealth roles open to Victorians are fine). Do not focus on any single employer or program.

For each role, note: title, employer, suburb, work type, pay as listed, closing date, the direct URL,
and a rating: strong (fits her endorsement, experience level and settings, commutable), maybe (one catch),
or skip (wrong level, wrong specialty, not a psychology role), with one plain sentence on why.
Finish with one or two sentences on today's market for her. Aim for 10-25 roles."""

messages = [{"role": "user", "content": SEARCH_PROMPT}]
tools = [{
    "type": "web_search_20250305", "name": "web_search", "max_uses": 12,
    "user_location": {"type": "approximate", "city": "Melbourne", "region": "Victoria",
                      "country": "AU", "timezone": "Australia/Melbourne"},
}]
notes = ""
for _ in range(6):
    resp = call(max_tokens=12000, tools=tools, messages=messages)
    notes += "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    if resp.stop_reason != "pause_turn":
        break
    messages.append({"role": "assistant", "content": resp.content})
print(f"Search finished (stop reason: {resp.stop_reason}, {len(notes)} chars of notes).")
if len(notes.strip()) < 200:
    fail("The search step came back almost empty:\n" + notes[:1500])

# ---------- Step 2: convert to strict JSON (no tools) ----------
JSON_PROMPT = f"""Convert these job-search notes into a single JSON object. Output ONLY the JSON: no code fences, no commentary.

Shape:
{{"summary": "1-2 plain sentences on today's market for her",
  "profile": [["label","short value"]],
  "jobs": [{{"title":"","employer":"","location":"","work_type":"","pay":"","closes":"","url":"","match":"strong|maybe|skip","why":""}}]}}

Rules: "profile" is 6-8 rows summarising what the jobs were matched on, taken from the profile below, with NO phone,
email, street address or registration numbers. Use "Not listed" for missing pay and "" for missing closing dates.
Only include URLs that appear in the notes. Keep every role from the notes. Order best matches first.

<profile>
{profile_text}
</profile>

<notes>
{notes}
</notes>"""


def parse(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("no JSON object found")
    return json.loads(text[start:end + 1])


data, last_err, last_text = None, None, ""
for attempt in range(2):
    r = call(max_tokens=10000, messages=[{"role": "user", "content": JSON_PROMPT}])
    last_text = "".join(b.text for b in r.content if getattr(b, "type", "") == "text")
    try:
        data = parse(last_text)
        break
    except Exception as e:
        last_err = e
        print(f"JSON attempt {attempt + 1} failed ({e}, stop reason {r.stop_reason}); retrying...")
if data is None:
    fail(f"Couldn't get valid JSON ({last_err}). Start of reply:\n{last_text[:1500]}")

# ---------- Step 3: tidy and write ----------
rank = {"strong": 0, "maybe": 1, "skip": 2}
jobs = [j for j in data.get("jobs", []) if isinstance(j, dict) and j.get("title")]
if not jobs:
    fail("No roles came back today, so the old brief was kept.")
for j in jobs:
    j["match"] = j.get("match") if j.get("match") in rank else "maybe"
    j["is_new"] = bool(previous_urls) and j.get("url") not in previous_urls
jobs.sort(key=lambda j: (rank[j["match"]], not j["is_new"]))

out = {
    "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "summary": data.get("summary", ""),
    "profile": data.get("profile", []),
    "jobs": jobs,
}
with open(OUT, "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print(f"Wrote {len(jobs)} roles ({sum(j['match']=='strong' for j in jobs)} strong, "
      f"{sum(j['is_new'] for j in jobs)} new).")
