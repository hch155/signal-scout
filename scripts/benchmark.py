#!/usr/bin/env python3
"""Compare asset sizes before vs after the Node.js removal migration."""

import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Baseline (captured before changes)
BEFORE = {
    "CSS": {
        "build.css": 34_682,
        "output.css": 46_728,
    },
    "JS minified": {
        "common.min.js": 10_804,
        "compass.min.js": 15_682,
        "map-initialization.min.js": 623,
        "tips-interactions.min.js": 339,
        "ui-interactions.min.js": 27_571,
    },
    "Build tooling": {
        "node_modules/": 22_000_000,
    },
}

# Current (measured from disk)
CSS_DIR = os.path.join(PROJECT_ROOT, "src", "static", "css")
JS_DIR = os.path.join(PROJECT_ROOT, "src", "static", "dist", "pages")
NODE_DIR = os.path.join(PROJECT_ROOT, "node_modules")


def file_size(path):
    try:
        return os.path.getsize(path)
    except FileNotFoundError:
        return 0


def dir_size(path):
    total = 0
    if os.path.isdir(path):
        for dirpath, _, filenames in os.walk(path):
            for f in filenames:
                total += os.path.getsize(os.path.join(dirpath, f))
    return total


def fmt(n):
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}MB"
    if n >= 1_000:
        return f"{n / 1_000:.1f}K"
    return f"{n}B"


def pct(before, after):
    if before == 0:
        return "N/A"
    diff = ((after - before) / before) * 100
    sign = "+" if diff > 0 else ""
    return f"{sign}{diff:.1f}%"


def main():
    after_css = {
        "output.css": file_size(os.path.join(CSS_DIR, "output.css")),
    }
    after_js = {
        "common.min.js": file_size(os.path.join(JS_DIR, "common.min.js")),
        "compass.min.js": file_size(os.path.join(JS_DIR, "compass.min.js")),
        "map-initialization.min.js": file_size(os.path.join(JS_DIR, "map-initialization.min.js")),
        "tips-interactions.min.js": file_size(os.path.join(JS_DIR, "tips-interactions.min.js")),
        "ui-interactions.min.js": file_size(os.path.join(JS_DIR, "ui-interactions.min.js")),
    }
    after_tooling = {
        "node_modules/": dir_size(NODE_DIR),
    }

    print("=" * 65)
    print("  BENCHMARK: Before vs After (Node.js removal)")
    print("=" * 65)
    print()

    # CSS
    before_css_total = sum(BEFORE["CSS"].values())
    after_css_total = sum(after_css.values())
    print("CSS Assets:")
    print(f"  {'File':<30} {'Before':>10} {'After':>10} {'Change':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10}")
    for name, bsize in BEFORE["CSS"].items():
        asize = after_css.get(name, 0)
        print(f"  {name:<30} {fmt(bsize):>10} {fmt(asize):>10} {pct(bsize, asize):>10}")
    for name, asize in after_css.items():
        if name not in BEFORE["CSS"]:
            print(f"  {name:<30} {'—':>10} {fmt(asize):>10} {'new':>10}")
    print(f"  {'TOTAL':<30} {fmt(before_css_total):>10} {fmt(after_css_total):>10} {pct(before_css_total, after_css_total):>10}")
    print()

    # JS
    before_js_total = sum(BEFORE["JS minified"].values())
    after_js_total = sum(after_js.values())
    print("JS Minified Assets:")
    print(f"  {'File':<30} {'Before':>10} {'After':>10} {'Change':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10}")
    for name in BEFORE["JS minified"]:
        bsize = BEFORE["JS minified"][name]
        asize = after_js.get(name, 0)
        print(f"  {name:<30} {fmt(bsize):>10} {fmt(asize):>10} {pct(bsize, asize):>10}")
    print(f"  {'TOTAL':<30} {fmt(before_js_total):>10} {fmt(after_js_total):>10} {pct(before_js_total, after_js_total):>10}")
    print()

    # Tooling
    before_tool = BEFORE["Build tooling"]["node_modules/"]
    after_tool = after_tooling["node_modules/"]
    print("Build Tooling:")
    print(f"  {'Item':<30} {'Before':>10} {'After':>10} {'Change':>10}")
    print(f"  {'-'*30} {'-'*10} {'-'*10} {'-'*10}")
    print(f"  {'node_modules/':<30} {fmt(before_tool):>10} {fmt(after_tool):>10} {pct(before_tool, after_tool):>10}")
    print()

    # Summary
    before_total = before_css_total + before_js_total
    after_total = after_css_total + after_js_total
    print("=" * 65)
    print(f"  Total served assets:  {fmt(before_total)} -> {fmt(after_total)} ({pct(before_total, after_total)})")
    print(f"  CSS files served:     2 -> 1 (-1 HTTP request)")
    print(f"  Build tooling:        {fmt(before_tool)} -> {fmt(after_tool)} ({pct(before_tool, after_tool)})")
    print(f"  Node.js required:     Yes -> No")
    print("=" * 65)


if __name__ == "__main__":
    main()
