# imagor 422 → Sentry (gc-imagor) with a Vector sidecar: POC

Same idea as `../imagor-sentry-poc`, but the forwarder is the **stock Vector image plus
`vector/vector.yaml` and its VRL program `vector/imagor_422_event.vrl`**, with no Python. nginx
is unchanged: it still sends each 422 as one JSON line over UDP to `127.0.0.1:5140`.

| Pod container (dev)       | Here                                                              |
|---------------------------|-------------------------------------------------------------------|
| `image-processor-nginx`   | `nginx:1.28.0` + `nginx/default.conf` (dev ConfigMap, verbatim)   |
| `image-processor`         | `shumc/imagor:1.6.3`, S3 → local files, HTTP loader off, `/unsafe/` URLs |
| `imagor-sentry-forwarder` | `timberio/vector:0.58.0-alpine` + `vector/` (config + VRL)        |
| Sentry `gc-imagor`        | `mock-sentry`: logs each envelope instead of storing it           |

## Pipeline (`vector/vector.yaml`)

```
socket udp 127.0.0.1:5140
  → event        VRL (imagor_422_event.vrl): nginx JSON → image path (options stripped, path normalized) → Sentry envelope
  → per_image    1/hour/image  one event per broken image
  → sentry_cap   60/min        protects the Sentry quota
  → http sink    POST <DSN host>/api/<project>/envelope/, 3 retries max
```

The event is kept minimal: fingerprint `["imagor-422", <image>]` (one Sentry issue per image), message,
level, environment, and the request (URL, Referer, User-Agent). Path variants like `poc//x.gif` and
`poc/./x.gif` share one dedup key.

## Run

```sh
docker compose up -d --build
sh test.sh                 # controls, 422s, dedup, path variants
sh test.sh burst           # 70 distinct broken images vs the 60/min cap
docker compose logs imagor-sentry-forwarder mock-sentry
docker compose down -v
```

Validate the config, no stack needed:

```sh
docker run --rm -v "$PWD/vector:/etc/vector:ro" \
  timberio/vector:0.58.0-alpine validate --no-environment /etc/vector/vector.yaml
```

To recreate only the forwarder or the mock, pass `--no-deps`. Without it, compose also recreates `pod`,
and nginx and imagor lose their network namespace.

## Results (2026-10-14)

| Check | Result |
|---|---|
| `vector validate` | valid |
| `test.sh`: 3 controls + 7 × 422 (incl. dedup + 3 path variants) | **2 events** (wide.png, big-anim.gif) |
| `test.sh burst`: 70 distinct broken images | **60 forwarded**, 10 dropped by the cap |
| `MOCK_STATUS=429` | 1 attempt + 3 retries, then dropped and logged. Image still served, Vector up |
| `IMAGOR_SENTRY_DSN=` | 0 requests, each 422 dropped with an error log, Vector up |
| Memory (`docker stats`) | Vector ≈ 15 MiB (limit 128 MiB) |

## Trade-offs to know

- **`dangerously_allow_unconfined_template_resolution: true`** on the sink. Vector 0.58 refuses
  fully templated URIs (SSRF guard). Here the URI comes only from the `IMAGOR_SENTRY_DSN` env var,
  never from request data, so it's safe, but Vector logs a SECURITY warning at startup. The
  alternative is a second env var with the static Sentry host (`uri: "https://${SENTRY_HOST}/api/..."`).
- **Dedup and caps are in memory, per pod.** They reset on restart, and with two replicas you'd get up to 2×.
- **UDP is best-effort.** Events can be lost under load. Image serving never waits on the forwarder.

## Scenarios

| Scenario | How |
|---|---|
| Sentry failing | `MOCK_STATUS=429 docker compose up -d --no-deps --force-recreate mock-sentry imagor-sentry-forwarder` |
| No DSN | `IMAGOR_SENTRY_DSN= docker compose up -d --no-deps --force-recreate imagor-sentry-forwarder` |
| Sidecar down | `docker compose stop imagor-sentry-forwarder`: images still served |
| Real gc-imagor (careful: sends real events) | `IMAGOR_SENTRY_DSN=<gc-imagor DSN> docker compose up -d --no-deps --force-recreate imagor-sentry-forwarder` |
