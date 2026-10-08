# Assignment Helping Agency

A Django application with client, writer, and staff workflows for managing
assignment orders and submissions.

## Requirements

- Python 3.12 or newer, using a Django-supported Python release.
- `requirements.txt` pins Django, the production Gunicorn server, and their
  runtime dependencies.
- SQLite is configured for local development.

## Development setup

From the project directory, create and activate a virtual environment.

### Windows PowerShell

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
```

If PowerShell blocks activation, use the Python executable directly:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

### Linux/macOS shell

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

The application does not load `.env` files automatically. Set environment
variables in the current shell or your process manager. For local development,
the defaults are intended for HTTP on localhost. `DEBUG` defaults to `false`,
so set it to `true` for development. When `DEBUG=true`, an unset `SECRET_KEY`
gets an ephemeral development-only key; it changes on each process start. Supply
a private local development key through the environment if a stable local key
is needed. Never use that development key in production.

PowerShell example:

```powershell
$env:DEBUG = "true"
$env:ALLOWED_HOSTS = "localhost,127.0.0.1,[::1]"
$env:CSRF_TRUSTED_ORIGINS = ""
```

Linux/macOS example:

```sh
export DEBUG=true
export ALLOWED_HOSTS='localhost,127.0.0.1,[::1]'
export CSRF_TRUSTED_ORIGINS=''
```

See [`.env.example`](./.env.example) for the supported setting names and
production-oriented examples. It is documentation only, contains no secrets,
and is not read by Django.

Apply database migrations, optionally create an administrator, run tests, and
start the development server:

```sh
python manage.py migrate
python manage.py createsuperuser
python manage.py test
python manage.py runserver
```

The development server is for local development only.

## Production deployment

This deployment outline assumes a Linux host. It does not assume a particular
hosting provider. Configure the application environment in the deployment
platform or process manager, not in committed files.

### Required environment configuration

At minimum, provide:

- A unique, strong `SECRET_KEY` from a secret store.
- `DEBUG=false`.
- `ALLOWED_HOSTS` as a comma-separated list of exact public hostnames. Do not
  use `*`.
- HTTPS settings appropriate to the actual proxy topology:
  `SECURE_SSL_REDIRECT=true`, `SESSION_COOKIE_SECURE=true`, and
  `CSRF_COOKIE_SECURE=true` when HTTPS is correctly available.
- `CSRF_TRUSTED_ORIGINS` only for required cross-origin HTTPS origins, including
  their scheme, for example `https://app.example.com`.
- SMTP settings (`EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_HOST_USER`,
  `EMAIL_HOST_PASSWORD`, `EMAIL_USE_TLS` or `EMAIL_USE_SSL`, and
  `DEFAULT_FROM_EMAIL`) if the deployment needs email delivery. Do not set both
  TLS and SSL.

HSTS is disabled by default. Set `SECURE_HSTS_SECONDS` only after confirming
HTTPS works reliably for the whole intended scope. Enable
`SECURE_HSTS_INCLUDE_SUBDOMAINS` or `SECURE_HSTS_PRELOAD` only after confirming
that every affected subdomain is HTTPS-ready and the preload implications are
understood.

If TLS terminates at a reverse proxy, configure that proxy to forward the
original scheme securely. Any Django proxy-header trust setting must be
configured only when requests can reach the application through that trusted
proxy; incorrect proxy trust can undermine HTTPS handling.

### Deployment commands

Install dependencies in the Linux deployment environment:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

After setting the production environment variables, run migrations and collect
static assets as a release/deployment step:

```sh
python manage.py migrate
python manage.py collectstatic --noinput
```

Start the WSGI application with Gunicorn, for example:

```sh
gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 3
```

Choose worker count based on the host’s CPU and memory. Run Gunicorn under the
platform’s process manager and place a reverse proxy/web server in front of it.
The proxy should terminate HTTPS, redirect HTTP to HTTPS, and forward requests
to Gunicorn. It should serve the collected files from `STATIC_ROOT` publicly
(or use an equivalent private deployment-managed static asset origin).

### Static assets and private submissions

`collectstatic` writes static assets to the project-relative `staticfiles/`
directory (`STATIC_ROOT`). Configure the web server to expose that directory
as the static URL path. Do not expose the project root.

Uploaded assignment submissions are private. **Never serve the `media/`
directory, the submissions subdirectory, or a storage bucket containing these
files through a generic public media URL.** Clients and writers must access
submission files only through the application's authenticated,
authorization-controlled download endpoint. That endpoint checks the user's
relationship to the order and enforces client approval rules before returning
a file. Preserve those checks if changing storage or adding a proxy.

Keep media storage persistent and protected from public access, and include it
in an appropriately secured backup/retention plan. Do not put private uploads
inside `STATIC_ROOT`.

### Database

The project currently uses SQLite at `db.sqlite3`. It is appropriate for local
development and small, single-host deployments with persistent storage and
backups, but it is not a good fit for multiple application instances, ephemeral
disks, or higher concurrent write volume. A move to PostgreSQL would require a
separately planned settings, driver, data migration, and backup/restore change;
that work is outside this setup and has not been performed.

## Checks

Run Django's system checks, tests, and migration-drift check with:

```sh
python manage.py check
python manage.py test
python manage.py makemigrations --check --dry-run
```

`python manage.py check --deploy` reports deployment-specific warnings until
required production values (such as HSTS duration and real hosts/secret) are
configured. Resolve those warnings against the actual HTTPS and proxy setup
before launch; do not silence them by weakening security settings.
