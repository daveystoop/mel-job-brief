// Mel's Job Brief — app logic
const WORKER_URL = "https://mel-brief-chat.dave-b-stepancic.workers.dev";

const LABEL = {strong:"Strong match", maybe:"Worth a look", skip:"Skipped"};
const $ = s => document.querySelector(s);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
let JOBS = [], PROFILE = [], META = {}, TODAY = "";

// ---------- dates ----------
const melToday = () => new Date().toLocaleDateString("en-CA", {timeZone: "Australia/Melbourne"}); // YYYY-MM-DD
const daysAgo = iso => iso ? Math.round((Date.parse(TODAY) - Date.parse(iso)) / 864e5) : 99;
function ago(iso){
  const d = daysAgo(iso);
  if (d <= 0) return "today";
  if (d === 1) return "yesterday";
  if (d < 7) return new Date(iso).toLocaleDateString("en-AU", {weekday: "long"});
  return new Date(iso).toLocaleDateString("en-AU", {day: "numeric", month: "short"});
}
const isOpen = j => (j.status || "open") === "open";
const isNewToday = j => isOpen(j) && daysAgo(j.first_seen) <= 0;
const isNewWeek = j => isOpen(j) && daysAgo(j.first_seen) < 7;

// ---------- header ----------
const now = new Date();
$("#date").textContent = now.toLocaleDateString("en-AU", {weekday:"long", day:"numeric", month:"long"});
const hr = now.getHours();
$("#hello").textContent = (hr < 12 ? "Morning" : hr < 18 ? "Afternoon" : "Evening") + ", Mel";

// ---------- load ----------
fetch("jobs.json?t=" + Date.now()).then(r => r.json()).then(d => {
  JOBS = d.jobs || []; PROFILE = d.profile || []; META = d;
  TODAY = d.today || melToday();
  render();
}).catch(() => { $("#snapNote").textContent = "Today's brief couldn't load. Check your connection and reopen the app."; });

// ---------- rows ----------
function row(j){
  const i = JOBS.indexOf(j), open = isOpen(j);
  const badge = !open ? `<span class="badge closed">closed</span>` : isNewToday(j) ? `<span class="badge">new</span>` : "";
  const km = j.distance_km ? ` · ${Math.round(j.distance_km)} km` : "";
  const when = open ? `Found ${ago(j.first_seen)}` : `Last seen ${ago(j.last_seen)}`;
  return `<button class="row${open ? "" : " closed"}" data-i="${i}">
    <span class="dot ${open ? j.match : "skip"}" aria-label="${LABEL[j.match] || ""}"></span>
    <span><h4>${esc(j.title)}${badge}</h4>
    <div class="meta">${esc(j.employer)}, ${esc(j.location)}${km}</div>
    <div class="meta">${when}${j.source ? ` · via ${esc(j.source)}` : ""}</div>
    ${j.pay && !/not listed/i.test(j.pay) ? `<div class="pay">${esc(j.pay)}</div>` : ""}</span>
  </button>`;
}
const empty = t => `<p class="ask-intro">${t}</p>`;

// ---------- Today ----------
function render(){
  const open = JOBS.filter(isOpen);
  const today = open.filter(isNewToday);
  const week = open.filter(j => isNewWeek(j) && !isNewToday(j));

  $("#strongCount").textContent = today.length;
  $("#dialText").textContent = `new today · ${open.length} open role${open.length === 1 ? "" : "s"} in total`;
  requestAnimationFrame(() => requestAnimationFrame(() => {
    $("#ring").style.strokeDashoffset = 226.2 * (1 - (open.length ? Math.max(today.length, .02 * open.length) / open.length : 0));
  }));

  let rail = today;
  if (!rail.length){ rail = open.filter(j => j.match === "strong").slice(0, 5); $("#railTitle").textContent = "Nothing new today · best open roles"; }
  $("#rail").innerHTML = rail.map(j => `
    <button class="hl" data-i="${JOBS.indexOf(j)}">
      <span class="score">${isNewToday(j) ? "New · " : ""}${LABEL[j.match] || ""}</span>
      <h3>${esc(j.title)}</h3>
      <span class="org">${esc(j.employer)}, ${esc(j.location)}</span>
      <span class="why">${esc(j.why)}</span>
    </button>`).join("") || empty("No open roles match yet. New ones are checked every morning.");

  $("#weekList").innerHTML = week.map(row).join("") || empty("Nothing else new in the last 7 days.");
  $("#seeAll").textContent = `See all ${open.length} open roles`;

  const when = META.updated ? new Date(META.updated).toLocaleString("en-AU", {weekday:"short", hour:"numeric", minute:"2-digit"}) : "";
  $("#snapNote").textContent = `Updated ${when}. ${META.criteria ? `Showing ${META.criteria}. ` : ""}${META.summary || ""}`;

  renderAll();
  $("#profile").innerHTML = PROFILE.map(([k, v]) => `
    <div class="row" style="cursor:default"><span class="dot strong"></span><span><h4>${esc(k)}</h4><div class="meta">${esc(v)}</div></span></div>`).join("");
}
$("#seeAll").onclick = () => go("all");

// ---------- All jobs ----------
let filter = "open", query = "";
function renderAll(){
  const runs = (META.runs || []).slice(-30);
  const max = Math.max(1, ...runs.map(r => r.new));
  $("#spark").innerHTML = runs.length > 1 ? runs.map(r =>
    `<span class="${r.date === TODAY ? "today" : ""}" style="height:${Math.max(6, 100 * r.new / max)}%" title="${r.date}: ${r.new} new"></span>`).join("") : "";
  const first = runs[0]?.date || JOBS.map(j => j.first_seen).sort()[0];
  const openN = JOBS.filter(isOpen).length;
  $("#allIntro").textContent = `${JOBS.length} roles found${first ? ` since ${new Date(first).toLocaleDateString("en-AU", {day:"numeric", month:"long"})}` : ""}, ${openN} still open.${runs.length > 1 ? " Bars show new roles per day." : ""}`;

  const q = query.toLowerCase();
  const list = JOBS.filter(j =>
    (filter === "open" ? isOpen(j) : filter === "week" ? isNewWeek(j) : filter === "strong" ? isOpen(j) && j.match === "strong" : !isOpen(j)) &&
    (!q || `${j.title} ${j.employer} ${j.location} ${j.source}`.toLowerCase().includes(q)));
  $("#list").innerHTML = list.map(row).join("") || empty(filter === "closed" ? "No closed roles yet." : "Nothing matches that.");
}
document.querySelectorAll("#view-all .chip[data-f]").forEach(c => c.onclick = () => {
  filter = c.dataset.f;
  document.querySelectorAll("#view-all .chip[data-f]").forEach(x => x.setAttribute("aria-pressed", x === c));
  renderAll();
});
$("#search").addEventListener("input", e => { query = e.target.value; renderAll(); });

// ---------- detail sheet ----------
function openJob(i){
  const j = JOBS[i];
  const safeUrl = /^https?:\/\//.test(j.url || "") ? j.url : "#";
  const open = isOpen(j);
  $("#sheetBody").innerHTML = `
    <span class="tag ${open ? j.match : "skip"}">${open ? LABEL[j.match] : "Probably closed"}</span>
    <h3 id="sTitle">${esc(j.title)}</h3>
    <div class="meta" style="color:var(--ink-soft)">${esc(j.employer)}, ${esc(j.location)}. ${esc(j.work_type)}</div>
    <p><strong>Grade:</strong> ${esc(j.grade || "Not stated")}${j.distance_km ? ` &nbsp; <strong>Distance:</strong> about ${Math.round(j.distance_km)} km from home` : ""}</p>
    <p><strong>Pay:</strong> ${esc(j.pay || "Not listed")}</p>
    <p><strong>Why:</strong> ${esc(j.why)}</p>
    ${j.closes ? `<p><strong>Closes:</strong> ${esc(j.closes)}</p>` : ""}
    <p><strong>History:</strong> first found ${ago(j.first_seen)}, last seen ${ago(j.last_seen)}${j.times_seen > 1 ? `, spotted on ${j.times_seen} days` : ""}.${j.source ? ` Found on ${esc(j.source)}.` : ""}</p>
    <a class="btn" href="${esc(safeUrl)}" target="_blank" rel="noopener">Open the listing</a>
    <button class="btn ghost" id="askAbout">Ask about this role</button>`;
  $("#askAbout").onclick = () => { closeSheet(); go("ask"); ask(`Tell me more about the "${j.title}" role at ${j.employer} and how Mel should pitch herself for it.`); };
  $("#scrim").classList.add("on"); $("#sheet").classList.add("on");
}
function closeSheet(){ $("#scrim").classList.remove("on"); $("#sheet").classList.remove("on"); }
$("#scrim").onclick = closeSheet;
document.addEventListener("keydown", e => { if (e.key === "Escape") closeSheet(); });
document.addEventListener("click", e => { const b = e.target.closest("[data-i]"); if (b) openJob(+b.dataset.i); });

// ---------- tabs ----------
function go(v){
  document.querySelectorAll(".tab").forEach(t => t.setAttribute("aria-selected", t.dataset.v === v));
  ["today", "all", "ask", "me"].forEach(n => $("#view-" + n).hidden = n !== v);
  $("#composer").hidden = v !== "ask";
  window.scrollTo(0, 0);
}
document.querySelectorAll(".tab").forEach(t => t.onclick = () => go(t.dataset.v));

// ---------- Ask (goes through the Cloudflare Worker, which holds the API key) ----------
const SUGG = ["What's new this week?", "What trends are you seeing?", "What do these roles pay?", "Which should she apply for first?"];
$("#sugg").innerHTML = SUGG.map(s => `<button class="chip">${s}</button>`).join("");
document.querySelectorAll("#sugg .chip").forEach(c => c.onclick = () => ask(c.textContent));
let chat = [], busy = false;

// Send open roles first, each tagged with its history so the chat can talk about what's new
function jobsForChat(){
  const ordered = [...JOBS.filter(isOpen), ...JOBS.filter(j => !isOpen(j))].slice(0, 40);
  return ordered.map(j => ({...j,
    why: `[${isOpen(j) ? "open" : "probably closed"}; first seen ${j.first_seen}; last seen ${j.last_seen}; ${j.grade || "grade not stated"}; ${j.distance_km ? Math.round(j.distance_km) + " km" : ""}] ${j.why || ""}`}));
}
function accessCode(){
  let c = null; try { c = localStorage.getItem("brief-code"); } catch(e){}
  if (!c){ c = prompt("Enter the access code David gave you"); if (c){ try { localStorage.setItem("brief-code", c); } catch(e){} } }
  return c;
}
async function ask(text){
  text = (text || "").trim(); if (!text || busy) return;
  const code = accessCode(); if (!code) return;
  busy = true; $("#q").value = "";
  addMsg("me", text);
  const bubble = addMsg("ai", "Thinking…");
  chat.push({role: "user", content: `(Today is ${TODAY}.) ${text}`});
  try {
    const r = await fetch(WORKER_URL, {method: "POST", headers: {"Content-Type": "application/json", "X-Access-Code": code},
      body: JSON.stringify({messages: chat.slice(-8), jobs: jobsForChat(), updated: META.updated})});
    if (r.status === 401){ try { localStorage.removeItem("brief-code"); } catch(e){} throw new Error("code"); }
    if (!r.ok) throw new Error("http");
    const d = await r.json();
    bubble.textContent = d.text; chat.push({role: "assistant", content: d.text});
  } catch(e){
    bubble.textContent = e.message === "code" ? "That access code didn't work. Tap a question to try again." : "That question didn't go through. Try again in a moment.";
    chat.pop();
  }
  busy = false; window.scrollTo(0, document.body.scrollHeight);
}
function addMsg(who, t){ const d = document.createElement("div"); d.className = "msg " + who; d.textContent = t; $("#msgs").appendChild(d); window.scrollTo(0, document.body.scrollHeight); return d; }
$("#send").onclick = () => ask($("#q").value);
$("#q").addEventListener("keydown", e => { if (e.key === "Enter") ask($("#q").value); });

// ---------- offline support + installable app ----------
if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").catch(() => {});
