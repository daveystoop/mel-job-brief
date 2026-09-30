"""
Daily refresh for Mel's Job Brief.
Runs on GitHub Actions each morning:
  1. Claude searches the web for open psychology roles in Melbourne and scores them against Mel's profile
  2. A second, tool-free call turns those notes into clean JSON (much more reliable than one step)
  3. Merges them into a running history (docs/jobs.json): every role keeps the date it was first seen,
     the date it was last seen, and whether it still looks open
If anything goes wrong, yesterday's brief is left in place and the log says exactly why.
"""
import json, os, re, sys, datetime
from zoneinfo import ZoneInfo
import anthropic

MODEL = "claude-sonnet-5-5"
OUT = "docs/jobs.json"
STALE_DAYS = 7        # not seen for this many days -> marked "probably closed"
FORGET_DAYS = 90      # closed roles older than this drop out of the history
RECHECK_MAX = 30      # how many known open roles to ask the search to re-confirm

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

MEL_TZ = ZoneInfo("Australia/Melbourne")
today_d = datetime.datetime.now(MEL_TZ).date()
TODAY = today_d.isoformat()

history, profile_rows, runs = {}, [], []
try:
    with open(OUT) as f:
        old = json.load(f)
    profile_rows = old.get("profile", [])
    runs = old.get("runs", [])
    seed_day = (old.get("updated") or TODAY)[:10]
    for j in old.get("jobs", []):
        if j.get("title"):
            j.setdefault("first_seen", seed_day)
            j.setdefault("last_seen", seed_day)
            j.setdefault("times_seen", 1)
            j.pop("is_new", None)
            history[id(j)] = j
except Exception:
    pass


def job_key(j):
    norm = lambda x: re.sub(r"[^a-z0-9]+", "", str(x or "").lower())
    return norm(j.get("employer"))[:40] + "|" + norm(re.sub(r"\(.*?\)", "", j.get("title", "")))[:60]


history = {job_key(j): j for j in history.values()}
by_url = {j.get("url"): k for k, j in history.items() if j.get("url")}
known_open = [j for j in history.values() if j.get("status", "open") == "open"][:RECHECK_MAX]
known_text = "\n".join(f"- {j['title']} | {j.get('employer','')} | {j.get('url','')}" for j in known_open) or "(none yet)"

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
ALSO: these roles were open on earlier days. Check each one quickly and include it again in your notes if it is still open
(say "closed" and skip it if the ad is gone or past its closing date):
{known_text}

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
seen_keys = set()
new_today = 0
for j in jobs:
    j["match"] = j.get("match") if j.get("match") in rank else "maybe"
    k = by_url.get(j.get("url")) or job_key(j)
    if k in seen_keys:
        continue
    seen_keys.add(k)
    prev = history.get(k)
    if prev:
        merged = {**prev, **{f: v for f, v in j.items() if v not in ("", None)}}
        merged["first_seen"] = prev.get("first_seen", TODAY)
        merged["times_seen"] = int(prev.get("times_seen", 1)) + (prev.get("last_seen") != TODAY)
    else:
        merged = {**j, "first_seen": TODAY, "times_seen": 1}
        new_today += 1
    merged["last_seen"] = TODAY
    merged["key"] = k
    history[k] = merged


def closing_passed(j):
    txt = str(j.get("closes") or "")
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%A %d %B %Y", "%A, %d %B %Y"):
        try:
            return datetime.datetime.strptime(re.sub(r"(\d)(st|nd|rd|th)", r"\1", txt.strip()), fmt).date() < today_d
        except ValueError:
            continue
    return False


kept = []
for k, j in history.items():
    last = datetime.date.fromisoformat(j.get("last_seen", TODAY))
    if closing_passed(j):
        j["status"] = "closed"
    elif (today_d - last).days > STALE_DAYS:
        j["status"] = "closed"
    else:
        j["status"] = "open"
    if j["status"] == "closed" and (today_d - last).days > FORGET_DAYS:
        continue
    j["is_new"] = j.get("first_seen") == TODAY
    kept.append(j)

# open first, then newest first, then best match
kept.sort(key=lambda j: rank.get(j["match"], 1))
kept.sort(key=lambda j: j.get("first_seen", ""), reverse=True)
kept.sort(key=lambda j: j["status"] != "open")

open_count = sum(j["status"] == "open" for j in kept)
runs = (runs + [{"date": TODAY, "found": len(seen_keys), "new": new_today, "open": open_count}])
runs = [r for i, r in enumerate(runs) if r["date"] not in {x["date"] for x in runs[i + 1:]}][-90:]

out = {
    "updated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "today": TODAY,
    "summary": data.get("summary", "") or (f"No new {WANTED_GRADE} roles within {RADIUS_KM} km today." if not new_today else ""),
    "criteria": f"{WANTED_GRADE} roles within {RADIUS_KM} km of {HOME}",
    "profile": data.get("profile") or profile_rows,
    "runs": runs,
    "jobs": kept,
}
with open(OUT, "w") as f:
    json.dump(out, f, indent=1, ensure_ascii=False)
print(f"Seen today: {len(seen_keys)} roles ({new_today} new). History now holds {len(kept)} roles, {open_count} open.")
