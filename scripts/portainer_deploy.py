#!/usr/bin/env python3
"""Redeploy a Portainer standalone (agent) stack with a new image tag.

Standard stacks (unlike CE edge stacks) support pullImage + registry auth by
hostname, so this is a clean: GET stack file -> swap image tag + APP_VERSION
-> PUT with pullImage=true.

Env:
  PORTAINER_URL        e.g. http://INFRA_VM_IP:9000
  PORTAINER_API_TOKEN  X-API-KEY token
Usage:
  portainer_deploy.py gettag <stack_id>
  portainer_deploy.py <stack_id> <endpoint_id> <new_image_tag>
"""
import json, os, re, sys, urllib.request, urllib.error

URL = os.environ["PORTAINER_URL"].rstrip("/")
TOKEN = os.environ["PORTAINER_API_TOKEN"]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-KEY", TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)


if sys.argv[1] == "gettag":
    _, filed = call("GET", f"/api/stacks/{sys.argv[2]}/file")
    m = re.search(r"signal-scout/app:([^\"'\s]+)", filed["StackFileContent"])
    print(m.group(1) if m else "")
    sys.exit(0)

STACK_ID, ENDPOINT_ID, NEW_TAG = sys.argv[1], sys.argv[2], sys.argv[3]
_, filed = call("GET", f"/api/stacks/{STACK_ID}/file")
content = filed["StackFileContent"]
content = re.sub(r"(signal-scout/app:)[^\"'\s]+", r"\g<1>" + NEW_TAG, content)
content = re.sub(r'(APP_VERSION:\s*")[^"]*(")', r"\g<1>" + NEW_TAG + r"\g<2>", content)

status, res = call("PUT", f"/api/stacks/{STACK_ID}?endpointId={ENDPOINT_ID}", body={
    "stackFileContent": content,
    "env": [],
    "pullImage": True,
    "prune": False,
})
print(f"stack {STACK_ID} -> {NEW_TAG}, HTTP {status}")
