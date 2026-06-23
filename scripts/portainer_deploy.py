#!/usr/bin/env python3
"""Redeploy a Portainer Edge Stack with a new image tag (CE 2.27).

CE Edge Stacks have no webhook; the redeploy lever is PUT /api/edge_stacks/{id}
with UpdateVersion=true and the full compose content. We fetch the current
compose, swap the image tag, and PUT it back.

Env:
  PORTAINER_URL        e.g. http://INFRA_VM_IP:9000
  PORTAINER_API_TOKEN  X-API-KEY token
Args:
  <edge_stack_id> <edge_group_id> <new_image_tag>
"""
import json, os, re, sys, urllib.request, urllib.error

URL = os.environ["PORTAINER_URL"].rstrip("/")
TOKEN = os.environ["PORTAINER_API_TOKEN"]
STACK_ID, GROUP_ID, NEW_TAG = sys.argv[1], int(sys.argv[2]), sys.argv[3]


def call(method, path, body=None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(URL + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    req.add_header("X-API-KEY", TOKEN)
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            raw = r.read().decode()
            return r.status, (json.loads(raw) if raw.strip() else {})
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code}: {e.read().decode()[:300]}", file=sys.stderr)
        sys.exit(1)


_, filed = call("GET", f"/api/edge_stacks/{STACK_ID}/file")
content = filed["StackFileContent"]
new_content = re.sub(r"(signal-scout/app:)[^\"'\s]+", r"\g<1>" + NEW_TAG, content)
if new_content == content:
    print("WARNING: image tag unchanged after substitution", file=sys.stderr)

status, res = call("PUT", f"/api/edge_stacks/{STACK_ID}", body={
    "StackFileContent": new_content,
    "EdgeGroups": [GROUP_ID],
    "DeploymentType": 0,
    "UpdateVersion": True,
})
print(f"edge stack {STACK_ID} -> tag {NEW_TAG}, version {res.get('Version')}, HTTP {status}")
