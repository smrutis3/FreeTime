# FreeTime

**One line:** FreeTime suggests what to do with your free time right now, and changes what it suggests, how it talks and who gets to approve as the user's age changes.

Built at Build for Everyone (Google + k-ID, San Francisco, 21 Oct 2026). Track: Consumer AI.

## What it does

Three tiers from one gate. Age and jurisdiction come from k-ID, never from a form we trust.

| | Child (below digital consent age) | Teen (below civil age) | Adult |
|---|---|---|---|
| Gate | k-ID age gate → child connects to a grown-up's account (suggested from accounts seen on this device or Wi-Fi) → that grown-up approves and picks topics | k-ID age gate → pass | k-ID age gate → pass |
| Inputs | prompt, weather, parent-managed calendar and settings | prompt, weather, own calendar, 5-question quiz, mood, thumbs | prompt, weather, calendar (.ics), notes, "about me" |
| Filters | parent-allowed topics (educational, entertainment, a hobby to learn) and categories, daily free-time budget, "grown-up joins" toggle, no prices or addresses | school hours blocked, 21:00 cutoff, no 18+ | none |
| Output | 3 picture cards, big text, emoji, read aloud | 3 cards, casual, solo/friends badge, 👍👎 | 3 rows time-boxed to a calendar gap, cost, "why" citing calendar + notes |
| Approval | none by default; every child ask is classified safe / casual / concerning / dangerous and the parent is **notified** only for the last two (optional "approve every idea" switch) | none | none |

k-ID permissions (`ai-chat`, `ai-voice-mode`, `ai-memory`) gate features in both places: the UI hides them, and the backend refuses them with 403.

## The screen

One three-column screen. Left: sessions on this device, the k-ID band, today's free time ring, weather and place, and the k-ID permission switches (read-only: they come from k-ID, not from us). Centre: an iMessage-style chat; the age gate (age slider plus country) sits here until a session exists. Right: for a child, the parent's Family panel (link requests with topic choice, risky-ask notifications, rules); for teens and adults, their context (calendar, free windows, notes or quiz picks). Every tier gets a "What changed for you" list.

A parent can also link a child by typing the 6-digit code shown on the child's waiting screen ("Link a child"), which stands in for k-ID's one-time password.

## Run it

```bash
# backend
cd backend
cp .env.example .env            # add ANTHROPIC_API_KEY and KID_API_KEY
pip install -r requirements.txt
uvicorn main:app --reload --port 8000

# frontend (another terminal)
cd frontend
npm install
npm run dev                     # http://localhost:5173, proxies /api to :8000
```

Without `KID_API_KEY` the backend runs a **mock gate** with the same tiers and a local consent simulator on the Parent page. Without `ANTHROPIC_API_KEY` it picks the top three filtered activities with templated reasons, so the demo never fails.

The gate asks for an age (slider, null until moved, per k-ID guidance) and a country. Judges type their own age. Presets: Mia 8, Leo 14, Sam 30. Leo is a teen in California and a child in Germany; the `/compare` page shows that matrix for any ages and countries side by side, and every chat screen has a "What changed for you" panel listing who decided, the filters, tone, memory and connectors in force.

## How k-ID is used

Server-side, documented pattern (custom age gate, "Shape A, Pattern A"). The browser never sees the API key.

1. `POST /api/kid/age-gate` → k-ID `POST /age-gate/check` with `dateOfBirth` + `jurisdiction`.
2. `PASS` → session with `ageStatus` + `permissions`. `DIGITAL_MINOR` = child, `LEGAL_ADULT` = adult, otherwise teen.
3. `CHALLENGE` → the child picks a grown-up's account. Suggestions come from adults who signed in on the same device or network (`GET /api/kid/link-suggestions`). `POST /api/kid/link-request` calls k-ID `POST /challenge/send-email` so that parent gets a Family Connect link (test mode: Mock Providers; links expire in 7 min). In mock mode the request shows up on that parent's dashboard instead, where they choose topics, categories, budget and voice, then approve.
4. `GET /api/kid/challenge/{id}` polls `GET /challenge/get-status`; on `PASS` it reads `GET /session/get` and creates the user.
5. `POST /api/kid/claim` re-reads the session so permission changes land on tab focus and on the Settings page.

## Endpoints

```
POST /api/kid/age-gate            GET /api/kid/challenge/{id}       POST /api/kid/claim
GET  /api/kid/link-suggestions    POST /api/kid/link-request        POST /api/compare
GET  /api/me/{uid}                POST /api/suggest                  GET  /api/child/{uid}/pending
GET  /api/parent/{email}          PUT  /api/parent/{email}/settings  POST /api/approve
POST /api/feedback (ai-memory)    POST /api/onboard/teen (ai-memory) POST /api/context/adult (ai-memory)
POST /api/transcribe (ai-voice)   POST /api/speak (ai-voice)         GET  /api/weather
```

## Location

Location is a **city**, not a country. The gate asks anyone 16 or older for their city; the list and each city's k-ID jurisdiction, coordinates and region live in `backend/tiers.py` (`CITIES`). Anyone under 16 is asked only for age and name: until a parent connects they are treated with the strictest consent age (16), and on approval they inherit the parent's city and country and their age band is re-derived there. A 14-year-old whose parent is in Milan becomes a teen (Italy's consent age is 14); the same child with a parent in Berlin stays a child. Parents choose their city at login on `/parent`. Weather, the web-search location and the planner all follow the city. The built-in catalogue is San Francisco only; in any other city the at-home activities remain and everything else is found live.

## How suggestions are made

- **Children**: in San Francisco, the catalogue (about 30 parent-filterable activities) ranked by the words in the question, then Claude writes three short picture cards. In other cities, or when the parent's filters leave fewer than four options, the planner searches the web under family-only rules: grown-up present, daytime, museums, parks, pools, libraries, family workshops, within the parent's topics.
- **Teens and adults**: a planning agent with Claude's built-in web search. It gets the date, weekday, time, weather, free windows, quiz picks or notes, and the catalogue as a fallback. If the ask mentions an event, a place type, a day, "tonight" or "this weekend", it must search (up to three queries) and at least two picks must come from real listings with a source link. Teen rules: all-ages only, nothing after 21:00, neighbourhood not address. Takes 20 to 35 seconds; the chat shows "checking the web".
- Repeated asks rotate: the last six catalogue picks are excluded, and results are cached for only 90 seconds.

## Two-device demo

Run both servers on the laptop. The child opens `http://<laptop-LAN-ip>:5173` on one device; the waiting screen prints the exact `/parent` address for the parent's phone. The parent signs in there with any email, enters the child's 6-digit code, picks topics, approves. Both devices poll the same backend, so the child's screen flips within three seconds and any rule the parent flips (voice, topics, minutes) reaches the child within five. The laptop's LAN address is in the backend's `/api/health` as `lan_ip`.

## Child safety

Each child message runs through a keyword pass and a Claude classifier (`safe`, `casual`, `concerning`, `dangerous`) in parallel with the suggestion call. Risky asks get a gentle one-line reply for the child, safe alternatives, and a notification on the parent's dashboard with the category and reason. Ordinary asks never reach the parent. A keyword hit can never be downgraded below `concerning` by the model.

## Voice

Both sit behind the k-ID `ai-voice-mode` permission: the mic button disappears when a parent turns voice off, and the backend returns 403 even if you call it directly.

- **Speech in: Modulate** Velma-2 batch STT. The browser records with `MediaRecorder` (webm in Chrome, mp4 in Safari) and posts the clip to `POST /api/transcribe`, which forwards it to `https://platform.modulate.ai/api/velma-2-stt-batch` with the `X-API-Key` header. The transcript goes straight into the suggestion request.
- **Speech out: Inworld** TTS-2. `POST /api/speak` calls `https://api.inworld.ai/tts/v1/voice` with Basic auth and returns MP3. The voice follows the tier: Ashley at 0.9x for children, Alex for teens, Dennis for adults. Children's approved cards are read out automatically; others have a 🔊 button. If Inworld is unreachable the browser's own speech synthesis reads the card.

## What's mocked

Calendars, notes and "about me" are seeded from `backend/data/`. No database: everything is in memory.

## Roadmap

Google account context (calendar, Maps history) for adults, real booking, and a balanced-day planner.
