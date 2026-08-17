# oneread

A private text-to-speech library. Paste text or drop in a file, pick a voice, get
back a wav with subtitles timed to the audio.

Speech comes from [Supertonic 3](https://github.com/supertone-inc/supertonic),
running as ONNX inside the app. No API keys, nothing leaves the machine, no
per-character billing. The model is ~385 MB and is baked into the Docker image.

## What it does

- **Entries.** Title, text, tags, voice settings. Text is read as plain or as
  markdown; markdown is flattened first — headings and list items become their
  own lines, links read their label, tables are read as `"Row 2. Name: Grace."`,
  code fences are announced rather than dictated, and symbols become words
  (`≥` → "greater than or equal to"). Ceiling is 100,000 characters.
- **Search.** One box over title, text and tags, backed by SQLite FTS5.
- **File upload.** Word, slides, spreadsheets, CSV, PDF (text, not scans),
  markdown, plain text, OpenDocument, RTF, saved web pages. The extracted words
  go back to the editor before anything is saved; the original file is kept and
  downloadable. `.doc` and `.ppt` need LibreOffice via `ONEREAD_SOFFICE_PATH`.
  No OCR — an image-only PDF is refused with a reason.
- **Readings.** An entry collects them: a 1/3/5-minute sample, a sentence range
  picked with a two-handled slider, or the whole document. Each has its own
  player, subtitles and delete button. A new entry gets a sample automatically,
  so nobody spends half an hour of CPU to find out the voice was wrong.
- **Estimates.** Audio length and wall clock, shown before you commit and
  calibrated from readings this machine has already finished.
- **Stopping.** A full reading freezes the entry while it runs. Stop keeps what
  was read and downloads as `title-partial.wav`. A restart resumes rather than
  discarding.
- **Subtitles.** Cue boundaries come from the sample count of the audio written,
  not from a duration predictor, so `.srt`/`.wav` line up exactly. "Follow along"
  in the player highlights each line as it is spoken.
- **Accounts.** A user id and a password; a new id creates the account. Entries
  are per-user. The session cookie lasts a month and renews on use. Its signing
  key is generated once into `data/secret.key` (mode 0600) so restarts don't sign
  everybody out; `ONEREAD_SECRET_KEY` overrides it.
- **Analytics.** Microsoft Clarity, off until asked for, revocable from the
  account menu.

Audio is streamed to disk a sentence at a time, so a two-hour entry costs no more
memory than a two-minute one. Measured on an M-series laptop: 3,120 characters →
231 s of audio in 53 s, under 100 MB of process growth.

## Running it

### Docker

```sh
cp .env.example .env
docker compose up --build -d
```

The first build downloads the model. Then open http://localhost:8000.

Database and audio live in `./data`, mounted into the container — back that up
and you've backed up everything. Upgrading in place works: missing columns are
added to the existing SQLite file at startup.

### Local development

Python 3.12 and Node 22.

```sh
make install
make dev-backend     # API on :8000
make dev-frontend    # Vite on :5173, proxying /api
make serve           # build the frontend, serve everything from :8000
make test            # 169 tests, no model needed
make lint
```

Tests swap in a fake engine that writes silent wavs, so they take about a second.
Real audio needs the model, which downloads to `~/.cache/supertonic3` on first
use.

The Docker image installs from `backend/requirements.txt`, which pins every
transitive package with a hash under `pip --require-hashes`. Regenerate it when a
dependency changes:

```sh
cd backend && uv pip compile pyproject.toml --generate-hashes --universal \
  --python-version 3.12 -o requirements.txt
```

## Deploying

`docker-compose.prod.yml` is the whole stack: the app, nginx terminating TLS, and
certbot keeping the certificate current. Point the domain's A record at the host
first — the certificate is issued over http, so the name has to resolve.

```sh
cp .env.prod.example .env.prod
$EDITOR .env.prod          # domain and email, at least
make prod-init             # data dir, first certificate, everything up
make prod-update           # rebuild and roll forward — this is the deploy
```

`CERTBOT_STAGING=1` does a dry run against Let's Encrypt staging, where a typo in
the domain costs nothing.

```sh
make prod-logs             # follow everything
make prod-ps               # what's running, and is it healthy
make prod-backup           # snapshot ./data into backups/
make prod-cert-renew       # renew now rather than waiting for the timer
make prod-nginx-check      # parse the nginx config as the container sees it
```

`prod-backup` takes the database through SQLite's online backup instead of
tarring a file that is being written to. To restore:

```sh
tar -xzf backups/oneread-20260101-120000.tar.gz
mv data/backup/oneread.db data/oneread.db && rmdir data/backup
```

The archive holds `secret.key`, so it can sign any session cookie the app has
issued. Keep it where you'd keep a password.

Certbot renews twice a day inside the thirty-day window and nginx reloads every
six hours to pick it up. Neither needs the docker socket.

### What production adds

- Port 8000 unpublished, on an `internal: true` network: nginx is the only thing
  that can reach the app, and the app cannot make outbound connections.
- `ONEREAD_COOKIE_SECURE=true` and `ONEREAD_ALLOWED_HOSTS` set to the domain.
- Proxy headers on, trusting the internal subnet only. nginx *overwrites*
  `X-Forwarded-For` rather than appending — the append form would let a client
  put an address of its choosing first, and first is what rate limits key on.
- Read-only root filesystems, capabilities dropped, `no-new-privileges`.
- TLS 1.2/1.3, forward-secret AEAD ciphers only, session tickets off, HSTS from
  nginx so it covers 502s and 429s too. No `preload` — that is a one-way door.
- Unknown Host: connection closed on http, handshake rejected on https.
- Edge rate limits on top of the app's own.

Two knobs that move together: `ONEREAD_MAX_UPLOAD_BYTES` in `.env.prod` and
`client_max_body_size` in `deploy/nginx/nginx.conf`. Raise one without the other
and nginx refuses uploads the app would have taken.

Set `ONEREAD_ALLOW_REGISTRATION=false` once the accounts that need to exist do.

**No horizontal scale.** The model sits in one process's memory and synthesis
runs on a single thread, so run one worker and give it CPU. Watch disk too: an
hour of audio is about 300 MB.

## Settings

Every setting is an environment variable prefixed `ONEREAD_`, or a line in
`.env`. Full list with defaults in `.env.example`. The ones most likely to move:

| Variable | Default | What it does |
| --- | --- | --- |
| `ONEREAD_SECRET_KEY` | generated into `data/secret.key` | Signs session cookies. |
| `ONEREAD_DATA_DIR` | `./data` | Database and audio files. |
| `ONEREAD_MAX_TEXT_CHARS` | `100000` | Ceiling on one entry's text. |
| `ONEREAD_MAX_UPLOAD_BYTES` | `26214400` | Biggest file that will be read. |
| `ONEREAD_SOFFICE_PATH` | empty | LibreOffice, which adds `.doc` and `.ppt`. |
| `ONEREAD_SAMPLE_MINUTES` | `1` | How much of a new entry is read straight away. |
| `ONEREAD_GENERATE_PER_HOUR` | `30` | Per user. |
| `ONEREAD_PREVIEW_PER_HOUR` | `120` | Voice samples, per user. |
| `ONEREAD_TEXT_PER_MINUTE` | `120` | Routes that reflow text without making audio. |
| `ONEREAD_CORS_ORIGINS` | empty | Only for a frontend on another origin. `*` is refused. |
| `ONEREAD_TTS_STEPS` | `8` | More steps, slightly better audio, more CPU. |
| `ONEREAD_PRELOAD_MODEL` | `true` | Load ONNX at startup. |

## Layout

```
backend/oneread/
  main.py             app factory, lifespan, serves the built frontend
  config.py           settings
  db.py               SQLite engine, FTS5 table and its triggers
  models.py           User, Entry, Rendition, Upload
  estimates.py        reading length, calibrated from finished ones
  auth.py             argon2, signed cookies, the CSRF check
  markdown_speech.py  markdown flattened into words a voice can say
  extract.py          uploaded files into speakable text, with the zip guards
  segmenter.py        text into sentence-sized pieces, one per cue
  tts_engine.py       Supertonic held open, per-segment synthesis, cue timings
  subtitles.py        cues into SRT and WebVTT
  worker.py           the job queue and its one thread
  routers/            auth, entries, renditions, meta, preview, uploads
frontend/src/
  screens/            AuthGate, Library, EntryPage
  components/         cards, players, editor, pickers
  styles/             tokens.css, glass.css, app.css
```

The interface uses translucent materials: `backdrop-filter` over a soft colour
field, a bright top edge, springs rather than fixed-duration slides. It respects
`prefers-reduced-motion`, `prefers-reduced-transparency`, `prefers-contrast`, and
the system light/dark setting.

## API

| Route | |
| --- | --- |
| `POST /api/auth/login` | Sign in, or create the account if the id is new |
| `POST /api/auth/logout` | |
| `POST /api/auth/revoke-sessions` | Sign out every other session |
| `GET /api/auth/me` | |
| `GET /api/entries?q=&tag=` | Search and filter. Summaries, not full text |
| `POST /api/entries` | Create and queue a sample |
| `GET /api/entries/{id}` | Full entry: text, spoken version, every reading |
| `PUT,DELETE /api/entries/{id}` | 409 while a full reading runs |
| `GET /api/entries/{id}/source` | The uploaded file, unchanged |
| `GET /api/entries/{id}/text.txt` | The words the voice reads |
| `GET /api/entries/{id}/segments` | Every sentence with its place on the timeline |
| `GET /api/entries/{id}/estimate?scope=` | Audio length and wall clock |
| `POST /api/entries/{id}/renditions` | Start a reading: `sample`, `range` or `full` |
| `GET /api/renditions/{id}` | One reading, with its cues |
| `POST /api/renditions/{id}/stop` | Stop it, keep what's been read |
| `DELETE /api/renditions/{id}` | Refused for the reading an entry leads with |
| `GET /api/renditions/{id}/audio?download=1` | Range requests supported |
| `GET /api/renditions/{id}/subtitles.srt` | |
| `GET /api/renditions/{id}/subtitles.vtt` | |
| `POST /api/uploads` | Read a file. Returns its words; saves nothing yet |
| `DELETE /api/uploads/{id}` | Discard a file that never became an entry |
| `POST /api/preview` | A few seconds of the chosen voice, as wav |
| `POST /api/preview/text` | The flattened text, no synthesis |
| `GET /api/meta` | Voices, languages, limits |
| `GET /healthz` | |

Writes require the header `X-Requested-With: oneread`, which a cross-site form
cannot set. Passwords are argon2; the session cookie is HttpOnly and signed;
sign-in and generation are rate-limited; the CSP blocks remote scripts.

## Licence

The app is yours to do what you like with. Supertonic and its model weights come
under their own licence, in the
[Supertonic repository](https://github.com/supertone-inc/supertonic).
