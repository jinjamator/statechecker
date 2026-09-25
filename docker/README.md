# StateChecker for Synaptic

This branch (`synaptic`) is the Python 3 port that the Synaptic product
`aci-statechecker` ships. It is built from `docker/Dockerfile`:

    docker build -f docker/Dockerfile \
        --build-arg SOURCE_COMMIT=$(git rev-parse --short HEAD) \
        -t synaptic/statechecker:<version> .

The image holds the service and the built UI. MongoDB runs in a container of
its own; the product's compose file (repo `app-aci-statechecker`) wires both.

What differs from upstream:

- Python 3.13, Flask 3, pymongo 4, gunicorn instead of Apache and mod_wsgi.
- The UI is built at image build time, with hash routing and relative paths,
  so it works under any prefix (`/statechecker/`, `/<node>/statechecker/`).
- `STATECHECKER_SECRET` derives the session key and the AES key and IV that
  encrypt stored APIC and SSH passwords. Upstream's defaults are public.
- `DEFAULT_PASSWORD` is required; there is no `admin`/`cisco` default.
- Cookies are named `statechecker_*` and scoped by `APP_PATH`, so they do not
  collide with other apps on the same origin.
- `MONGO_USERNAME` and `MONGO_PASSWORD`, when set, authenticate to MongoDB.
- Single sign-on from the Synaptic portal (`SSO_ENABLED`, `Service/app/models/sso.py`):
  `POST /api/sso/login` with the portal bearer token, checked against the
  portal's `/api/aaa/whoami`. `GET /api/session` lets the UI recognise a session
  it did not start itself. Usernames may contain `-`, `@` and `+`.

MongoDB 8.0 refuses to start on Linux 6.19 or newer, and 8.2 crashes there
(SERVER-121912); the product pins 7.0.

## Tests

    docker run -d --name sc-mongo mongo:7.0.43
    docker run --rm --network container:sc-mongo -v $PWD:/src:ro python:3.13-slim sh -c '
        apt-get -qq update && apt-get -qq install -y procps >/dev/null
        pip install -q -r /src/build/requirements-test.txt
        cp -r /src /work && mkdir -p /home/app/log /home/app/data/snapshots
        cd /work/Service && python -m pytest -q tests'

`tests/api/test_compare.py` compares two snapshot bundles through the API and
the real background worker, so the comparison is covered without an APIC.
