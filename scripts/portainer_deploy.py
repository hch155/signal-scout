#!/usr/bin/env python3
"""Redeploy a Portainer standalone (agent) stack with a new image tag.

Standard stacks (unlike CE edge stacks) support pullImage + registry auth by
hostname, so this is a clean: GET stack file -> swap image tag + APP_VERSION
-> PUT. The live stack keeps its secrets (OAuth, SendGrid, …) in the stored
compose's `environment:` block; we preserve the compose body verbatim except
for the tag swap, and preserve the stack's Env array, so a deploy can never
strip secrets.

FAIL-CLOSED: a transient `GET .../file` failure (HTTP 5xx — routine on the
flaky WiFi / after a Harbor/Portainer restart) is retried; if it still fails
the deploy ABORTS instead of silently substituting the in-repo compose, which
lacks the OAuth secrets and would ship a login-broken prod (the 2026-07-04
incident, automated). The repo fallback is only used when explicitly opted in
via ALLOW_FALLBACK=1 (a human knowingly restoring a genuinely-lost file), and
even then we refuse to PUT a body missing the OAuth keys the stack expects.

Env:
  PORTAINER_URL        e.g. http://INFRA_VM_IP:9000
  PORTAINER_API_TOKEN  X-API-KEY token
  PORTAINER_PULL       "false" -> pullImage=False (Harbor-independent rollback
                       using the locally-cached image). Default true.
  ALLOW_FALLBACK       "1" -> permit the in-repo fallback compose on a GET failure.
Usage:
  portainer_deploy.py gettag <stack_id>
  portainer_deploy.py <stack_id> <endpoint_id> <new_image_tag> [fallback_compose]
"""
import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
import urllib.parse

URL = os.environ["PORTAINER_URL"].rstrip("/")
TOKEN = os.environ["PORTAINER_API_TOKEN"]

# Secret keys the live stack is known to carry; a deploy body missing these is
# rejected so we never ship a secret-stripped prod.
REQUIRED_SECRET_KEYS = ("GOOGLE_OAUTH_CLIENT_ID", "GITHUB_OAUTH_CLIENT_ID",
                        "FACEBOOK_OAUTH_CLIENT_ID")


def call(method, path, body=None, allow_fail=False, retries=1):
    data = json.dumps(body).encode() if body is not None else None
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(URL + path, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        req.add_header("X-API-KEY", TOKEN)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.strip() else {})
        except urllib.error.HTTPError as e:
            code = e.code
            msg = e.read().decode()[:300]
            last = (code, {"_error": msg})
            # Retry only transient server errors; 4xx are definitive.
            if code >= 500 and attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            if allow_fail:
                return last
            print(f"HTTP {code}: {msg}", file=sys.stderr)
            sys.exit(1)
        except urllib.error.URLError as e:
            last = (0, {"_error": str(e)})
            if attempt < retries - 1:
                time.sleep(3 * (attempt + 1))
                continue
            if allow_fail:
                return last
            print(f"URLError: {e}", file=sys.stderr)
            sys.exit(1)
    return last


def stack_file(stack_id):
    """Return (status, content-or-None). Retries transient 5xx/network errors."""
    status, filed = call("GET", f"/api/stacks/{stack_id}/file",
                         allow_fail=True, retries=4)
    if status == 200 and filed.get("StackFileContent"):
        return status, filed["StackFileContent"]
    return status, None


if sys.argv[1] == "gettag":
    status, content = stack_file(sys.argv[2])
    if content is None:
        # Fail-closed: never hand back an empty rollback target that silently
        # disarms the rollback guard (`tag != ''`) in CI.
        print(f"gettag: could not read stack {sys.argv[2]} file (HTTP {status})",
              file=sys.stderr)
        sys.exit(1)
    m = re.search(r"signal-scout/app:([^\"'\s]+)", content)
    if not m:
        print(f"gettag: no image tag found in stack {sys.argv[2]}", file=sys.stderr)
        sys.exit(1)
    print(m.group(1))
    sys.exit(0)

STACK_ID, ENDPOINT_ID, NEW_TAG = sys.argv[1], sys.argv[2], sys.argv[3]
FALLBACK = sys.argv[4] if len(sys.argv) > 4 else None
PULL = os.environ.get("PORTAINER_PULL", "true").lower() != "false"

status, content = stack_file(STACK_ID)
used_fallback = False
if content is None:
    # Fail-closed. Do NOT silently deploy the repo compose — it lacks the
    # OAuth/secret environment the live stack carries and would break login.
    if not (FALLBACK and os.environ.get("ALLOW_FALLBACK") == "1"):
        print(f"stack {STACK_ID} compose unreadable (HTTP {status}); aborting "
              f"rather than deploying a secret-stripped fallback. "
              f"Set ALLOW_FALLBACK=1 to override knowingly.", file=sys.stderr)
        sys.exit(1)
    print(f"ALLOW_FALLBACK=1: restoring stack {STACK_ID} from {FALLBACK}",
          file=sys.stderr)
    with open(FALLBACK) as f:
        content = f.read()
    used_fallback = True

content = re.sub(r"(signal-scout/app:)[^\"'\s]+", r"\g<1>" + NEW_TAG, content)
content = re.sub(r'(APP_VERSION:\s*")[^"]*(")', r"\g<1>" + NEW_TAG + r"\g<2>", content)

# Preserve the stack's env (secrets, ADDRESSES_DB_PATH, …); sending [] wipes it.
_, stack = call("GET", f"/api/stacks/{STACK_ID}", retries=4)
current_env = stack.get("Env", []) or []

# Only when we substituted the repo fallback do we second-guess the secret set:
# a fallback body that lacks the OAuth keys (present in neither the compose nor
# the preserved Env) would ship a login-broken prod. The normal path re-deploys
# the live stack's own compose verbatim, so its secret set is by definition
# correct and must not be second-guessed (staging may legitimately carry fewer
# providers than prod).
if used_fallback:
    env_names = {e.get("name") for e in current_env}
    for key in REQUIRED_SECRET_KEYS:
        if key not in content and key not in env_names:
            print(f"refusing fallback deploy: required secret {key} is present in "
                  f"neither the fallback compose nor the stack Env — this would "
                  f"break login. Fix the Env array first.", file=sys.stderr)
            sys.exit(1)

status, res = call("PUT", f"/api/stacks/{STACK_ID}?endpointId={ENDPOINT_ID}",
                   retries=3, body={
    "stackFileContent": content,
    "env": current_env,
    "pullImage": PULL,
    "prune": False,
})
print(f"stack {STACK_ID} -> {NEW_TAG}, pullImage={PULL}, HTTP {status}")

# Old image tags pile up on the Docker host and filled the 16 GB LXC root.
# Prune only DANGLING (untagged) images — tagged prod images stay so a
# pullImage=False rollback always has a locally-cached last-good image, even
# when Harbor is down.
_prune_q = urllib.parse.quote(json.dumps({"dangling": ["true"]}))
_pstatus, _ = call("POST",
                   f"/api/endpoints/{ENDPOINT_ID}/docker/images/prune?filters={_prune_q}",
                   allow_fail=True)
print(f"image prune (dangling-only) HTTP {_pstatus}")
