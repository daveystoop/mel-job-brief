"""
Daily refresh for Mel's Job Brief.
Runs on GitHub Actions each morning:
  1. Asks Claude (with web search) to find currently open psychologist roles in Melbourne
  2. Scores each against Mel's profile
  3. Writes docs/jobs.json, which the phone app reads
"""
import json, os, re, sys, datetime
import anthropic

MODEL = "claude-sonnet-5-5"
OUT = "docs/jobs.json"

profile_text = os.environ.get("MEL_PROFILE", "").strip()
if not profile_text:
    sys.exit("MEL_PROFILE secret is missing. Add it in GitHub > Settings > Secrets > Actions.")

# Remember what we showed yesterday so we can flag what's new
previous_urls = set()
try:
    with open(OUT) as f:
        previous_urls = {j.get("url") for j in json.load(f).get("jobs", [])}
except Exception:
    pass

today = datetime.date.today().strftime("%A %d %B %Y")

PROMPT = f"""Today is {today}. You are a job-search agent for a clinical psychologist in Melbourne, Australia.

Her profile:
<profile>
{profile_text}
</profile>

Step 1. Search the web for psychologist and clinical psychologist roles in Greater Melbourne that are open right now.
Cover SEEK, Indeed, LinkedIn, and the careers pages of public health services (Northern Health, Austin Health,
Eastern Health, Mercy Health, Melbourne Health/RMH, Alfred Health, Monash Health, Western Health), plus
community mental health organisations. Prefer individual job ads over search-result pages. Skip anything
clearly closed or outside Victoria (telehealth roles open to Victorians are fine).

Step 2. Score each role against her profile:
- "strong": fits her endorsement, experience level and preferred settings, commutable from her home base
- "maybe": good fit with one catch (distance, setting, pay model, specialty)
- "skip": wrong level (graduate/registrar), wrong specialty, or not a psychology role

Step 3. Reply with ONLY a JSON object, no other text, in exactly this shape:
{{
  "summary": "one or two plain sentences on today's market for her",
  "profile": [["label","short value"], ...],   // 6-8 rows summarising what you match on; NO phone, email, address or registration numbers
  "jobs": [
    {{"title":"", "employer":"", "location":"suburb", "work_type":"Full-time/Part-time/Contract/etc",
      "pay":"as listed, or 'Not listed'", "closes":"closing date or ''", "url":"direct link to the ad",
      "match":"strong|maybe|skip", "why":"one plain sentence, written to her, on why it fits or doesn't"}}
  ]
}}
Aim for 10-25 roles, best matches first. Only include URLs you actually found."""

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
messages = [{"role": "user", "content": PROMPT}]
tools = [{
    "type": "web_search_20250305", "name": "web_search", "max_uses": 12,
    "user_location": {"type": "approximate", "city": "Melbourne", "region": "Victoria",
                      "country": "AU", "timezone": "Australia/Melbourne"},
}]

# Server-side search can pause long turns; keep going until it finishes
for _ in range(5):
    resp = client.messages.create(model=MODEL, max_tokens=8000, tools=tools, messages=messages)
    if resp.stop_reason != "pause_turn":
        break
    messages.append({"role": "assistant", "content": resp.content})

text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
match = re.search(r"\{.*\}", text, re.S)
if not match:
    sys.exit("Claude didn't return JSON. Raw reply:\n" + text[:2000])
data = json.loads(match.group(0))

rank = {"strong": 0, "maybe": 1, "skip": 2}
jobs = [j for j in data.get("jobs", []) if j.get("title")]
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
