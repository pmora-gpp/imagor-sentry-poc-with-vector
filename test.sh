#!/bin/sh
# Fire requests at the local image-processor pod and print each HTTP status next to the expected one.
#   sh test.sh          happy path, dedup and dedup-bypass variants
#   sh test.sh burst    70 distinct broken images in a few seconds (Sentry cap is 60/min)
BASE="${BASE:-http://localhost:8081}"

req() {
  code=$(curl -sg --path-as-is -o /dev/null -w '%{http_code}' -H 'Referer: https://poc.local/some-page' "$BASE$1")
  printf '%s (expect %s)  %s\n' "$code" "$2" "$1"
}

if [ "$1" = "burst" ]; then
  echo "== burst: 70 distinct broken images"
  i=1
  while [ "$i" -le 70 ]; do
    code=$(curl -s -o /dev/null -w '%{http_code}' "$BASE/unsafe/fit-in/100x100/poc/burst/wide-$(printf '%02d' "$i").png")
    [ "$code" = "422" ] || echo "unexpected $code for wide-$i"
    i=$((i + 1))
  done
  echo "done; count forwarded events with:"
  echo "  docker compose logs mock-sentry | grep -c 'POST /api/'"
  exit 0
fi

echo "== controls: served normally, nothing forwarded"
req /healthcheck 200
req /unsafe/fit-in/300x300/poc/small.png 200
req /unsafe/fit-in/150x150/poc/small-anim.gif 200

echo "== maximum resolution exceeded: one Sentry event per image"
req /unsafe/fit-in/300x300/poc/wide.png 422
req /unsafe/fit-in/300x300/poc/big-anim.gif 422

echo "== same images, different options: still 422, deduplicated (no new event)"
req '/unsafe/200x200/filters:format(webp)/poc/wide.png' 422
req /unsafe/100x100/smart/poc/big-anim.gif 422

echo "== path variants that bypassed the Python forwarder's dedup: normalized, no new event"
req /unsafe/fit-in/300x300/poc//big-anim.gif 422
req /unsafe/fit-in/300x300/poc/./big-anim.gif 422
req /unsafe/fit-in/300x300//poc/big-anim.gif 422

echo
echo "Check what was forwarded:  docker compose logs imagor-sentry-forwarder mock-sentry"
