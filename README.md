# ShortURL

A small URL shortener with a JSON API, SQLite persistence, and click analytics.

## Architecture

FastAPI handles requests and validates URLs. `shorturl.storage.SQLiteStore` owns SQL and opens a fresh SQLite connection for each operation. Links have random 10-character base62 codes. A unique database key handles the unlikely collision; creation retries with a new code. Redirects use HTTP 302 with `Cache-Control: no-store` so visits can be counted. Each visit increments the count and records its UTC timestamp in one transaction. The 20 latest timestamps remain in the database; the all-time count remains accurate.

SQLite uses write-ahead logging and a persistent file. `BEGIN IMMEDIATE` serializes concurrent click updates. One application instance and one writable volume are required. The service does not fetch destination URLs or store visitor IP addresses.

## Local setup

Requires Python 3.10 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv sync --locked --all-extras
uv run uvicorn shorturl.api:app --reload
```

Open `http://localhost:8000/docs` for interactive API documentation. The local database is `data/shorturl.sqlite3`. Run tests with `uv run --locked --all-extras pytest -q`.

## API

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/api/links` | Create a short link (`201`) |
| `GET` | `/{code}` | Redirect and record a click (`302`) |
| `HEAD` | `/{code}` | Inspect redirect without recording a click (`302`) |
| `GET` | `/api/links/{code}/stats` | Count and recent UTC click timestamps (`200`) |
| `GET` | `/healthz` | Database readiness (`200`) |

Create a link:

```sh
curl -i -X POST http://localhost:8000/api/links \
  -H 'Content-Type: application/json' \
  -d '{"url":"https://example.org/article"}'
```

The response contains `code`, `url`, `short_url`, and `created_at`. The `Location` header also contains the short URL. A stats response adds `click_count`, `last_clicked_at` (null until first visit), and up to 20 `recent_clicks` timestamps, newest first. For example:

```sh
curl -i http://localhost:8000/REPLACE_WITH_CODE
curl http://localhost:8000/api/links/REPLACE_WITH_CODE/stats
```

Only HTTP and HTTPS destination URLs up to 2,048 characters are accepted. Credentials, whitespace, and control characters in a destination are rejected. The API returns JSON errors: `401` for a missing or invalid configured API key, `404` for an unknown code, `422` for invalid input, and `503` for unavailable storage or code allocation failure.

## Deployment

Build the included Docker image and run it behind a TLS-terminating proxy. Set these environment variables:

| Variable | Purpose |
| --- | --- |
| `SHORTURL_BASE_URL` | Public HTTPS origin, such as `https://go.example.com` |
| `SHORTURL_API_KEY` | Secret of at least 32 characters for create and stats endpoints |
| `SHORTURL_DATABASE_PATH` | SQLite file on a persistent writable volume; defaults to `/data/shorturl.sqlite3` in the image |
| `PORT` | Listening port; defaults to `8000` |

For example, generate an API key with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'`, then supply it as a deployment secret. Pass it as an `X-API-Key` header on create and stats requests. Redirects remain public. A public base URL without HTTPS or an API key fails startup.

```sh
docker build -t shorturl .
docker volume create shorturl-data
docker run --rm -p 8000:8000 -v shorturl-data:/data \
  -e SHORTURL_BASE_URL=https://go.example.com \
  -e SHORTURL_API_KEY="$SHORTURL_API_KEY" shorturl
```

Point the proxy's health check at `/healthz`. Back up the volume, including the SQLite database, before replacing or removing it. Use one running application instance with this SQLite design.

### PythonAnywhere free account

PythonAnywhere's standard WSGI web app can use the optional `a2wsgi` adapter and its persistent home directory. In a Python 3.10 Bash console:

```sh
git clone https://github.com/Cole-Godfrey/shorturl.git ~/shorturl
cd ~/shorturl
mkvirtualenv shorturl --python=python3.10
pip install '.[pythonanywhere]'
mkdir -p ~/shorturl-data
python -c 'import secrets; print(secrets.token_urlsafe(32))' > ~/shorturl-data/api-key
chmod 600 ~/shorturl-data/api-key
```

Create a manual Python 3.10 web app in the **Web** tab and set its virtualenv to `/home/YOUR_USERNAME/.virtualenvs/shorturl`. Replace its WSGI configuration with the following, using your account name and actual HTTPS domain:

```python
import os

os.environ["SHORTURL_BASE_URL"] = "https://YOUR_USERNAME.pythonanywhere.com"
os.environ["SHORTURL_DATABASE_PATH"] = "/home/YOUR_USERNAME/shorturl-data/shorturl.sqlite3"
with open("/home/YOUR_USERNAME/shorturl-data/api-key") as secret_file:
    os.environ["SHORTURL_API_KEY"] = secret_file.read().strip()

from shorturl.wsgi import application
```

Reload the web app. Use the contents of `~/shorturl-data/api-key` as the `X-API-Key` header when creating links or reading stats. Keep that file outside the repository and back up `~/shorturl-data`.

From a trusted shell with `SHORTURL_API_KEY` set, run `python scripts/smoke.py https://YOUR_USERNAME.pythonanywhere.com` to verify the live service. It prints a working short URL after checking health, redirect, and analytics.

## Tradeoffs and rebuild guide

The single-file database keeps setup and operations simple, but it limits write throughput and prevents horizontal scaling. A multi-instance deployment would need a shared database such as PostgreSQL. The WSGI adapter adds a small amount of overhead on PythonAnywhere. All-time counts are retained, while only 20 event timestamps per link are retained. There is no user account system, expiration, custom alias, or abuse reporting. Keep the API key private and rotate it if exposed.

To rebuild the core: create the `links` table with a unique code, validate an HTTP(S) URL, generate a random code and retry collisions, return the public short URL, then look up the code and issue a 302. Record the click and timestamp in the same transaction, and expose a stats query. `settings.py` defines configuration, `storage.py` contains SQL, and `api.py` maps HTTP requests to those operations.
