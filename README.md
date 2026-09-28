# Clew

Clew shortens URLs and counts visits. It has a JSON API and stores links in SQLite.

The live API documentation is at [colegodfrey.pythonanywhere.com/docs](https://colegodfrey.pythonanywhere.com/docs).

## How it works

FastAPI handles requests and URL validation. `clew.storage.SQLiteStore` handles SQL, opening a new connection for each operation. New links get random 10-character base62 codes. If a code already exists, Clew tries another one.

Redirects return HTTP 302 with `Cache-Control: no-store` so visits can be counted. A click updates the count and UTC timestamp in one transaction. Clew keeps the 20 most recent click timestamps for each link and its total count. SQLite uses write-ahead logging, and `BEGIN IMMEDIATE` prevents concurrent updates from losing clicks. Run one application instance with one writable database volume. Clew does not fetch destination URLs or store visitor IP addresses.

## Run locally

You need Python 3.10 or newer and [uv](https://docs.astral.sh/uv/getting-started/installation/).

```sh
uv sync --locked --all-extras
export CLEW_API_KEY="$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')"
uv run uvicorn clew.api:app --reload
```

Open `http://localhost:8000/docs` to try the API. The local database is `data/clew.sqlite3`. Run the tests with `uv run --locked --all-extras pytest -q`.

For unauthenticated local development, unset `CLEW_API_KEY` and `SHORTURL_API_KEY`, then run `CLEW_ALLOW_UNAUTHENTICATED_LOCAL=true uv run uvicorn clew.api:app --host 127.0.0.1 --reload`. This setting only works with a localhost `CLEW_BASE_URL` and should not be used in a public deployment.

## API

| Method | Path | Result |
| --- | --- | --- |
| `POST` | `/api/links` | Create a short link (`201`) |
| `GET` | `/{code}` | Redirect and record a click (`302`) |
| `HEAD` | `/{code}` | Inspect a redirect without recording a click (`302`) |
| `GET` | `/api/links/{code}/stats` | Get the count and recent UTC click timestamps (`200`) |
| `GET` | `/healthz` | Check database readiness (`200`) |

Create a link with:

```sh
curl -i -X POST http://localhost:8000/api/links \
  -H 'Content-Type: application/json' \
  -H "X-API-Key: $CLEW_API_KEY" \
  -d '{"url":"https://example.org/article"}'
```

The response includes `code`, `url`, `short_url`, and `created_at`. The `Location` header holds the short URL too. Stats include `click_count`, `last_clicked_at` (null until the first visit), and up to 20 `recent_clicks` timestamps, newest first.

```sh
curl -i http://localhost:8000/REPLACE_WITH_CODE
curl -H "X-API-Key: $CLEW_API_KEY" http://localhost:8000/api/links/REPLACE_WITH_CODE/stats
```

Destinations must use HTTP or HTTPS and be at most 2,048 characters long. Clew rejects credentials, whitespace, and control characters in a destination. Errors are JSON: `401` for a missing or invalid API key, `404` for an unknown code, `422` for invalid input, and `503` for storage trouble or exhausted code attempts.

## Deploy

Run the included Docker image behind a proxy that handles TLS. Set these environment variables:

| Variable | Purpose |
| --- | --- |
| `CLEW_BASE_URL` | Public HTTPS origin, such as `https://go.example.com` |
| `CLEW_API_KEY` | Secret of at least 32 characters for creating links and reading stats |
| `CLEW_ALLOW_UNAUTHENTICATED_LOCAL` | Optional; set to `true` only for unauthenticated local development; defaults to `false` |
| `CLEW_DATABASE_PATH` | SQLite file on a persistent writable volume; defaults to `/data/clew.sqlite3` in the image |
| `PORT` | Listening port; defaults to `8000` |

Generate an API key with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` and supply it as a deployment secret. Send it in the `X-API-Key` header for create and stats requests. Redirects are public. Without a key, create and stats requests return `401` even when `CLEW_BASE_URL` is localhost. A public deployment requires HTTPS and an API key.

```sh
docker build -t clew .
docker volume create clew-data
docker run --rm -p 8000:8000 -v clew-data:/data \
  -e CLEW_BASE_URL=https://go.example.com \
  -e CLEW_API_KEY="$CLEW_API_KEY" clew
```

Use `/healthz` for the proxy's health check. Back up the volume before replacing or removing it. This SQLite setup supports one running application instance.

### PythonAnywhere free account

PythonAnywhere can run Clew through the optional `a2wsgi` adapter. In a Python 3.10 Bash console:

```sh
git clone https://github.com/Cole-Godfrey/Clew.git ~/Clew
cd ~/Clew
mkvirtualenv clew --python=python3.10
pip install '.[pythonanywhere]'
mkdir -p ~/clew-data
python -c 'import secrets; print(secrets.token_urlsafe(32))' > ~/clew-data/api-key
chmod 600 ~/clew-data/api-key
```

Create a manual Python 3.10 web app in the `Web` tab. Set its virtualenv to `/home/YOUR_USERNAME/.virtualenvs/clew`. Replace its WSGI configuration with this code, using your account name and HTTPS domain:

```python
import os

os.environ["CLEW_BASE_URL"] = "https://YOUR_USERNAME.pythonanywhere.com"
os.environ["CLEW_DATABASE_PATH"] = "/home/YOUR_USERNAME/clew-data/clew.sqlite3"
with open("/home/YOUR_USERNAME/clew-data/api-key") as secret_file:
    os.environ["CLEW_API_KEY"] = secret_file.read().strip()

from clew.wsgi import application
```

Reload the web app. Use the contents of `~/clew-data/api-key` as the `X-API-Key` header for creating links or reading stats. Keep the key outside the repository and back up `~/clew-data`. Free PythonAnywhere sites need renewal each month in the `Web` tab.

From the Bash console, run `CLEW_API_KEY="$(cat ~/clew-data/api-key)" python scripts/smoke.py https://YOUR_USERNAME.pythonanywhere.com` to check the live service. It prints a working short URL after testing health, a redirect, and click stats. The WSGI adapter starts its event loop on the first request, after a prefork server such as uWSGI creates its worker.

When updating a ShortURL installation, point `CLEW_DATABASE_PATH` at its existing database and read `CLEW_API_KEY` from its existing key file. The old `SHORTURL_*` environment variables also work during migration.

## Limits

SQLite keeps deployment simple, but write throughput is limited and the service cannot run across multiple instances. That would require a shared database such as PostgreSQL. The WSGI adapter adds some overhead on PythonAnywhere. Clew retains total click counts but only the latest 20 timestamps per link. It has no user accounts, expiration, custom aliases, or abuse reporting. Keep the API key private and rotate it if it is exposed.

## License

Clew is licensed under the [MIT License](LICENSE).
