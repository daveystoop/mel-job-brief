# Mel's Job Brief

A phone app that finds Melbourne psychology jobs every morning, scores them against Mel's resume, and lets her ask questions about them.

- `scripts/refresh.py` runs daily on GitHub Actions, asks Claude to search and score, and writes `docs/jobs.json`
- `docs/index.html` is the app, served free by GitHub Pages
- `worker/worker.js` is the chat relay on Cloudflare, which keeps the API key out of the page

Your API key lives only in GitHub and Cloudflare secrets. It is never in the code or the page.

## Setup (about 20 minutes)

### 1. GitHub repo
1. Create a new **public** repo called `mel-job-brief` (free GitHub Pages needs public).
2. Upload everything in this folder **except `mel-profile.txt`**.
3. Settings > Secrets and variables > Actions > New repository secret:
   - `ANTHROPIC_API_KEY`: your key
   - `MEL_PROFILE`: paste the contents of `mel-profile.txt` (edit it first if anything's off)
4. Settings > Pages > Source: "Deploy from a branch", branch `main`, folder `/docs`. Save.
   Your app will be at `https://YOUR-USERNAME.github.io/mel-job-brief/`
5. Actions tab > "Daily job brief" > **Run workflow** to do the first run now. After about 2 minutes, reload the app.

### 2. Chat (Cloudflare Worker)
1. Sign up free at cloudflare.com > Workers & Pages > Create > "Hello World" worker. Name it `mel-brief-chat`.
2. Edit code, paste in `worker/worker.js`, Deploy.
3. Worker > Settings > Variables and secrets, add:
   - Secret `ANTHROPIC_API_KEY`: your key
   - Secret `ACCESS_CODE`: any word or phrase Mel will type once on her phone
   - Secret `MEL_PROFILE`: same text as the GitHub secret
   - Text variable `ALLOWED_ORIGIN`: `https://YOUR-USERNAME.github.io` (no trailing slash, no path)
4. Copy the worker's URL, put it in `WORKER_URL` near the top of the script in `docs/index.html`, and commit.

### 3. On Mel's phone
Open the app link in Safari (or Chrome), tap Share > **Add to Home Screen**. It then opens like a normal app.
The first time she asks a question it will ask for the access code.

## Good to know
- **Spend limit:** set a monthly limit on your key in the Anthropic Console. Expect a few dollars a month.
- **Privacy:** the repo and `jobs.json` are public, but hold only a summary of her experience, no contact details.
  The fuller profile sits in secrets.
- **Timing:** runs at 5:30am AEST (6:30am in daylight saving). Change the `cron` line in `.github/workflows/daily.yml` to adjust.
- **If a run fails:** Actions tab shows the log. The most common cause is a missing secret.
