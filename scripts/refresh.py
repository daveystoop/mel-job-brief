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

# ---------- Mel's search criteria (edit these to change what she sees) ----------
HOME = "Eltham VIC 3095"
RADIUS_KM = 25
WANTED_GRADE = "Grade 2"      # Victorian public/community health psychologist grade
MAX_SEARCHES = 30

SOURCES = """
Public health services (careers pages): Austin Health (Heidelberg), Mercy Health (Heidelberg), Northern Health (Epping),
Eastern Health (Box Hill, Ringwood, Maroondah), Melbourne Health / Royal Melbourne Hospital (Parkville),
St Vincent's Hospital Melbourne (Fitzroy), Royal Children's Hospital, Forensicare.
Community health services (careers pages): Banyule Community Health, Nillumbik Community Health, DPV Health,
Merri Health, cohealth, EACH, Access Health and Community, Carrington Health, Inspiro, Your Community Health,
Link Health and Community.
Community mental health and NGOs: Neami National, Mind Australia, Uniting, Anglicare Victoria, Berry Street,
headspace (Greensborough, Heidelberg, Epping, Box Hill, Collingwood), Orygen, Jesuit Social Services,
Mental Health and Wellbeing Locals, Mental Health and Wellbeing Hubs.
Government and sector boards: Careers Victoria (careers.vic.gov.au), APS (Australian Psychological Society) career centre,
Ethical Jobs, health sector job boards.
Job boards: SEEK, Indeed, LinkedIn, Jora.
"""
# -------------------------------------------------------------------------------


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

HER HARD CRITERIA (only report roles that meet ALL of these):
1. Psychologist roles advertised at {WANTED_GRADE} (Victorian public / community health classification; also accept
   "Psychologist Grade 2", "Clinical Psychologist Grade 2", "P2", or a combined "Grade 2/3" role). Ignore Grade 1, 3 and 4 roles.
   If a community health or NGO role gives no grade, only include it if the pay or duties clearly match Grade 2, and say "no grade listed".
2. The work location is within {RADIUS_KM} km of {HOME}. As a guide, in range: Heidelberg, Ivanhoe, Greensborough, Bundoora,
   Diamond Creek, Hurstbridge, Epping, Preston, Reservoir, Thomastown, Doncaster, Box Hill, Ringwood, Croydon, Mitcham,
   Nunawading, Lilydale, Fitzroy, Collingwood, Carlton, Parkville, Melbourne CBD, Richmond, Coburg, Brunswick.
   Out of range: the west (Sunshine, St Albans, Footscray, Werribee, Ravenhall) and the far south-east (Clayton, Dandenong, Frankston).
   Telehealth-only roles count only if run by a Victorian employer.

WHERE TO LOOK: search these sources ONE BY ONE rather than relying on general searches, using targeted queries
(the employer's name + "psychologist" + "careers", or site: queries on their careers domain):
{SOURCES}
Prioritise the employer's own job ad over job-board copies. Skip anything closed.

For each qualifying role, note: title, employer, suburb, estimated distance in km from {HOME}, grade as advertised,
work type, pay as listed, closing date, the direct URL, which source you found it on, and a rating:
strong (meets both criteria and suits her experience) or maybe (meets criteria but has a catch, e.g. no grade listed,
fixed-term, a specialty she hasn't done), with one plain sentence on why.
Finish with one or two sentences on today's market for her. It's fine to report only a few roles if that's all that qualifies."""

messages = [{"role": "user", "content": SEARCH_PROMPT}]
tools = [{
    "type": "web_search_20250305", "name": "web_search", "max_uses": MAX_SEARCHES,
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
  "jobs": [{{"title":"","employer":"","location":"","distance_km":0,"grade":"","work_type":"","pay":"","closes":"","url":"","source":"","match":"strong|maybe","why":""}}]}}

Rules: "profile" is 6-8 rows summarising what the jobs were matched on, taken from the profile below, with NO phone,
email, street address or registration numbers. Use "Not listed" for missing pay and "" for missing closing dates.
distance_km is a number (best estimate). grade is as advertised, or "No grade listed". source is the site it was found on (e.g. "Austin Health careers", "SEEK"). Only include URLs that appear in the notes. Keep every role from the notes. Order best matches first.

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


def in_criteria(j):
    try:
        if float(j.get("distance_km") or 0) > RADIUS_KM:
            return False
    except (TypeError, ValueError):
        pass
    g = str(j.get("grade", "")).lower()
    if re.search(r"grade\s*[134]\b", g) and not re.search(r"grade\s*2|2\s*/\s*3|\bp2\b", g):
        return False
    return True


before = len(jobs)
jobs = [j for j in jobs if in_criteria(j)]
print(f"Kept {len(jobs)} of {before} roles after the grade and distance check.")
for j in jobs:
    j["match"] = j.get("match") if j.get("match") in rank else "maybe"
    j["is_new"] = bool(previous_urls) and j.get("url") not in previous_urls
jobs.sort(key=lambda j: (rank[j["match"]], not j["is_new"]))

out = {
    "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "summary": data.get("summary", "") or (f"No {WANTED_GRADE} roles within {RADIUS_KM} km today." if not jobs else ""),
    "criteria": f"{WANTED_GRADE} roles within {RADIUS_KM} km of {HOME}",
    "profile": data.get("profile", []),
    "jobs": jobs,
}
with open(OUT, "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print(f"Wrote {len(jobs)} roles ({sum(j['match']=='strong' for j in jobs)} strong, "
      f"{sum(j['is_new'] for j in jobs)} new).")
