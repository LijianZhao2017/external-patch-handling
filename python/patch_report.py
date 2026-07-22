#!/usr/bin/env python3
"""
Step 5: Generate Markdown and HTML review reports

Usage:
    python patch_report.py                         # report for today's patches
    python patch_report.py --date 2026-03-25

Collects data from all prior steps and generates REVIEW_REPORT.md and
REVIEW_REPORT.html.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from html import escape
from pathlib import Path

from config import Config
from utils import format_table, today_str


def load_json(path: Path) -> dict | list | None:
    """Load a JSON file, return None if missing."""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _short(value: object, max_len: int) -> str:
    text = str(value or "")
    return text[:max_len]


def _load_report_data(staging_dir: Path) -> dict[str, dict | list | None]:
    return {
        "review": load_json(staging_dir / "review_data.json"),
        "apply": load_json(staging_dir / "apply_data.json"),
        "check": load_json(staging_dir / "check_data.json"),
        "tests": load_json(staging_dir / "test_data.json"),
    }


def generate_report(staging_dir: Path, cfg: Config) -> str:
    """Generate a markdown review report from all collected data."""
    date_str = staging_dir.name
    data = _load_report_data(staging_dir)
    review = data["review"]
    apply = data["apply"]
    check = data["check"]
    tests = data["tests"]

    lines = []
    lines.append(f"# Patch Review Report — {cfg.release} — {date_str}")
    lines.append(f"")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"")

    # Section 1: Patches Received
    lines.append(f"## Patches Received")
    lines.append(f"")
    if review and review.get("patches"):
        rows = []
        for i, p in enumerate(review["patches"], 1):
            rows.append([
                str(i),
                _short(p.get("subject", ""), 55),
                _short(p.get("author", ""), 30),
                str(p.get("files_changed", "?")),
                f"+{p.get('insertions', 0)}/-{p.get('deletions', 0)}",
            ])
        lines.append(format_table(["#", "Subject", "Author", "Files", "+/-"], rows))
    else:
        lines.append("_(No review data found — run patch_receive.py first)_")
    lines.append(f"")

    # Section 2: Review Notes & Warnings
    lines.append(f"## Review Notes")
    lines.append(f"")
    if review:
        warnings = review.get("all_warnings", []) or []
        if warnings:
            lines.append(f"### ⚠️ Warnings ({len(warnings)})")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append(f"")

        notes = review.get("reviewer_notes", {})
        if notes:
            lines.append(f"### Reviewer Notes")
            for patch_name, note in notes.items():
                lines.append(f"- **{patch_name}**: {note}")
            lines.append(f"")
        elif not warnings:
            lines.append(f"No warnings. No reviewer notes.")
            lines.append(f"")
    else:
        lines.append("_(No review data)_")
        lines.append(f"")

    # Section 3: Apply Result
    lines.append(f"## Apply Result")
    lines.append(f"")
    if apply:
        lines.append(f"- **Branch**: `{apply.get('branch', '?')}`")
        lines.append(f"- **Base**: `{apply.get('base', '?')}`")
        applied = apply.get("applied", [])
        lines.append(f"- **Commits applied**: {len(applied)} / {apply.get('total', '?')}")

        if apply.get("failed"):
            fail = apply["failed"]
            lines.append(f"- **⚠️ Conflict**: Stopped at patch {fail.get('index', '?')} (`{fail.get('patch', '?')}`)")
            if fail.get("stripped_prefix"):
                lines.append(f"- **Root prefix mismatch**: Detected leading `{fail['stripped_prefix']}/` and stripped it for diagnostics")
            if fail.get("apply_check_error"):
                lines.append(f"- **Plain apply check**: `{_short(fail['apply_check_error'], 240)}`")
        else:
            lines.append(f"- **Conflicts**: None ✅")

        if applied:
            lines.append(f"")
            lines.append(f"### Commits")
            for c in applied:
                lines.append(f"- `{c['hash']}` {_short(c['subject'], 65)}")
    else:
        lines.append("_(No apply data — run patch_apply.py first)_")
    lines.append(f"")

    # Section 4: Functional Equivalence Check
    lines.append(f"## Functional Equivalence Check")
    lines.append(f"")
    if check:
        summary = check.get("summary", {})
        overall = check.get("overall", "UNKNOWN")
        icon = "✅" if overall == "PASS" else "⚠️"
        lines.append(f"**Overall: {icon} {overall}**  "
                     f"({summary.get('match',0)} MATCH, {summary.get('partial',0)} PARTIAL, "
                     f"{summary.get('mismatch',0)} MISMATCH, {summary.get('missing',0)} MISSING, "
                     f"{summary.get('extra',0)} EXTRA)")
        lines.append(f"")
        file_rows = []
        for fr in check.get("files", []):
            status_icon = {"MATCH":"✅","PARTIAL":"⚠️","MISMATCH":"❌","MISSING":"🔴","EXTRA":"➕"}.get(fr["status"],"❓")
            sim = f"{fr['similarity']:.0%}" if fr["status"] != "EXTRA" else "—"
            file_rows.append([fr["file"][-55:], f"{status_icon} {fr['status']}", sim])
        if file_rows:
            lines.append(format_table(["File", "Status", "Similarity"], file_rows))
        if overall != "PASS":
            lines.append(f"")
            lines.append(f"> ⚠️ MISMATCH or MISSING files indicate the sender's intended changes may not have "
                         f"landed correctly due to codebase differences. Confirm with sender before integrating.")
    else:
        lines.append("_(No check data — run patch_check.py first)_")
    lines.append(f"")

    # Section 5: Test Results
    lines.append(f"## Test Results")
    lines.append(f"")
    if tests:
        icon_map = {"PASS": "✅", "FAIL": "❌", "SKIPPED": "⏭️", "PENDING": "⏳", "TIMEOUT": "⏰", "ERROR": "💥"}
        rows = []
        for t in tests:
            icon = icon_map.get(t["result"], "❓")
            rows.append([t["test"], f"{icon} {t['result']}", _short(t.get("notes", ""), 80)])
        lines.append(format_table(["Test", "Result", "Notes"], rows))
    else:
        lines.append("_(No test data — run patch_test.py first)_")
    lines.append(f"")

    # Section 6: Recommendation
    lines.append(f"## Reviewer Recommendation")
    lines.append(f"")
    lines.append(f"- [ ] **LGTM** — Ready for sender blessing. Recommend cherry-pick to working branch.")
    lines.append(f"- [ ] **Changes Requested** — See notes above. Sender should revise and resubmit.")
    lines.append(f"")
    lines.append(f"---")

    return "\n".join(lines)


def _html_table(headers: list[str], rows: list[list[object]]) -> str:
    head = "".join(f"<th>{escape(str(header))}</th>" for header in headers)
    body_rows = []
    for row in rows:
        cells = []
        for i in range(len(headers)):
            cell = row[i] if i < len(row) else ""
            cells.append(f"<td>{escape(str(cell))}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        "<div class=\"table-wrap\"><table>"
        f"<thead><tr>{head}</tr></thead>"
        f"<tbody>{''.join(body_rows)}</tbody>"
        "</table></div>"
    )


def _status_class(status: str) -> str:
    status_map = {
        "PASS": "good",
        "MATCH": "good",
        "FAIL": "bad",
        "MISMATCH": "bad",
        "MISSING": "bad",
        "ERROR": "bad",
        "PARTIAL": "warn",
        "PENDING": "warn",
        "TIMEOUT": "warn",
        "SKIPPED": "muted",
        "EXTRA": "info",
    }
    return status_map.get(status.upper(), "muted")


def _badge(label: object, status: str) -> str:
    return f"<span class=\"badge {_status_class(status)}\">{escape(str(label))}</span>"


def generate_html_report(staging_dir: Path, cfg: Config) -> str:
    """Generate a self-contained HTML review report from all collected data."""
    date_str = staging_dir.name
    generated = datetime.now().strftime("%Y-%m-%d %H:%M")
    data = _load_report_data(staging_dir)
    review = data["review"]
    apply = data["apply"]
    check = data["check"]
    tests = data["tests"]

    sections: list[str] = []
    summary_cards: list[str] = []

    if check:
        overall = str(check.get("overall", "UNKNOWN"))
        summary_cards.append(
            f"<div class=\"card\"><span>Equivalence</span>{_badge(overall, overall)}</div>"
        )
    else:
        summary_cards.append(
            f"<div class=\"card\"><span>Equivalence</span>{_badge('Not run', 'SKIPPED')}</div>"
        )

    if apply:
        conflict = "Conflict" if apply.get("failed") else "No conflicts"
        status = "FAIL" if apply.get("failed") else "PASS"
        summary_cards.append(
            f"<div class=\"card\"><span>Apply</span>{_badge(conflict, status)}</div>"
        )
        summary_cards.append(
            "<div class=\"card\"><span>Commits applied</span>"
            f"<strong>{len(apply.get('applied', []))} / {escape(str(apply.get('total', '?')))}</strong></div>"
        )
    else:
        summary_cards.append(
            f"<div class=\"card\"><span>Apply</span>{_badge('No data', 'SKIPPED')}</div>"
        )

    if review:
        warnings = review.get("all_warnings", []) or []
        status = "PARTIAL" if warnings else "PASS"
        summary_cards.append(
            f"<div class=\"card\"><span>Warnings</span>{_badge(len(warnings), status)}</div>"
        )
    else:
        summary_cards.append(
            f"<div class=\"card\"><span>Warnings</span>{_badge('No data', 'SKIPPED')}</div>"
        )

    sections.append(
        "<section id=\"summary\">"
        "<h2>Summary</h2>"
        f"<div class=\"summary-grid\">{''.join(summary_cards)}</div>"
        "</section>"
    )

    patch_content = []
    if review and review.get("patches"):
        rows = []
        for i, patch in enumerate(review["patches"], 1):
            rows.append([
                i,
                _short(patch.get("subject", ""), 55),
                _short(patch.get("author", ""), 30),
                patch.get("files_changed", "?"),
                f"+{patch.get('insertions', 0)}/-{patch.get('deletions', 0)}",
            ])
        patch_content.append(_html_table(["#", "Subject", "Author", "Files", "+/-"], rows))
    else:
        patch_content.append("<p class=\"empty\">No review data found — run patch_receive.py first.</p>")
    sections.append(
        "<section id=\"patches\"><h2>Patches Received</h2>"
        f"{''.join(patch_content)}</section>"
    )

    notes_content = []
    if review:
        warnings = review.get("all_warnings", []) or []
        if warnings:
            notes_content.append(f"<h3>Warnings ({len(warnings)})</h3>")
            notes_content.append("<ul class=\"warning-list\">")
            for warning in warnings:
                notes_content.append(f"<li>{escape(str(warning))}</li>")
            notes_content.append("</ul>")

        notes = review.get("reviewer_notes", {})
        if notes:
            notes_content.append("<h3>Reviewer Notes</h3><ul>")
            for patch_name, note in notes.items():
                notes_content.append(
                    f"<li><strong>{escape(str(patch_name))}</strong>: {escape(str(note))}</li>"
                )
            notes_content.append("</ul>")
        elif not warnings:
            notes_content.append("<p>No warnings. No reviewer notes.</p>")
    else:
        notes_content.append("<p class=\"empty\">No review data.</p>")
    sections.append(
        "<section id=\"notes\"><h2>Review Notes</h2>"
        f"{''.join(notes_content)}</section>"
    )

    apply_content = []
    if apply:
        apply_content.append("<dl class=\"meta-list\">")
        apply_content.append(f"<dt>Branch</dt><dd><code>{escape(str(apply.get('branch', '?')))}</code></dd>")
        apply_content.append(f"<dt>Base</dt><dd><code>{escape(str(apply.get('base', '?')))}</code></dd>")
        applied = apply.get("applied", [])
        apply_content.append(
            f"<dt>Commits applied</dt><dd>{len(applied)} / {escape(str(apply.get('total', '?')))}</dd>"
        )
        if apply.get("failed"):
            fail = apply["failed"]
            apply_content.append(
                "<dt>Conflict</dt><dd>"
                f"{_badge('Conflict', 'FAIL')} Stopped at patch {escape(str(fail.get('index', '?')))} "
                f"(<code>{escape(str(fail.get('patch', '?')))}</code>)</dd>"
            )
            if fail.get("stripped_prefix"):
                apply_content.append(
                    "<dt>Root prefix mismatch</dt><dd>"
                    f"Detected leading <code>{escape(str(fail['stripped_prefix']))}/</code> "
                    "and stripped it for diagnostics</dd>"
                )
            if fail.get("apply_check_error"):
                apply_content.append(
                    "<dt>Plain apply check</dt>"
                    f"<dd><code>{escape(_short(fail['apply_check_error'], 240))}</code></dd>"
                )
        else:
            apply_content.append(f"<dt>Conflicts</dt><dd>{_badge('None', 'PASS')}</dd>")
        apply_content.append("</dl>")

        if applied:
            apply_content.append("<h3>Commits</h3><ul class=\"commit-list\">")
            for commit in applied:
                apply_content.append(
                    f"<li><code>{escape(str(commit['hash']))}</code> "
                    f"{escape(_short(commit['subject'], 65))}</li>"
                )
            apply_content.append("</ul>")
    else:
        apply_content.append("<p class=\"empty\">No apply data — run patch_apply.py first.</p>")
    sections.append(
        "<section id=\"apply\"><h2>Apply Result</h2>"
        f"{''.join(apply_content)}</section>"
    )

    check_content = []
    if check:
        summary = check.get("summary", {})
        overall = str(check.get("overall", "UNKNOWN"))
        check_content.append(
            "<p class=\"overall\">"
            f"Overall: {_badge(overall, overall)} "
            f"({summary.get('match', 0)} MATCH, {summary.get('partial', 0)} PARTIAL, "
            f"{summary.get('mismatch', 0)} MISMATCH, {summary.get('missing', 0)} MISSING, "
            f"{summary.get('extra', 0)} EXTRA)</p>"
        )
        file_rows = []
        for file_result in check.get("files", []):
            status = str(file_result["status"])
            status_icon = {
                "MATCH": "✅",
                "PARTIAL": "⚠️",
                "MISMATCH": "❌",
                "MISSING": "🔴",
                "EXTRA": "➕",
            }.get(status, "❓")
            sim = f"{file_result['similarity']:.0%}" if status != "EXTRA" else "—"
            file_rows.append([file_result["file"][-55:], f"{status_icon} {status}", sim])
        if file_rows:
            check_content.append(_html_table(["File", "Status", "Similarity"], file_rows))
        if overall != "PASS":
            check_content.append(
                "<blockquote>MISMATCH or MISSING files indicate the sender's intended changes may not "
                "have landed correctly due to codebase differences. Confirm with sender before integrating."
                "</blockquote>"
            )
    else:
        check_content.append("<p class=\"empty\">No check data — run patch_check.py first.</p>")
    sections.append(
        "<section id=\"equivalence\"><h2>Functional Equivalence Check</h2>"
        f"{''.join(check_content)}</section>"
    )

    test_content = []
    if tests:
        icon_map = {
            "PASS": "✅",
            "FAIL": "❌",
            "SKIPPED": "⏭️",
            "PENDING": "⏳",
            "TIMEOUT": "⏰",
            "ERROR": "💥",
        }
        rows = []
        for test in tests:
            icon = icon_map.get(test["result"], "❓")
            rows.append([test["test"], f"{icon} {test['result']}", _short(test.get("notes", ""), 80)])
        test_content.append(_html_table(["Test", "Result", "Notes"], rows))
    else:
        test_content.append("<p class=\"empty\">No test data — run patch_test.py first.</p>")
    sections.append(
        "<section id=\"tests\"><h2>Test Results</h2>"
        f"{''.join(test_content)}</section>"
    )

    sections.append(
        "<section id=\"recommendation\"><h2>Reviewer Recommendation</h2>"
        "<label class=\"checkline\"><input type=\"checkbox\"> "
        "<strong>LGTM</strong> — Ready for sender blessing. Recommend cherry-pick to working branch.</label>"
        "<label class=\"checkline\"><input type=\"checkbox\"> "
        "<strong>Changes Requested</strong> — See notes above. Sender should revise and resubmit.</label>"
        "</section>"
    )

    nav_items = [
        ("summary", "Summary"),
        ("patches", "Patches"),
        ("notes", "Review Notes"),
        ("apply", "Apply Result"),
        ("equivalence", "Equivalence"),
        ("tests", "Test Results"),
        ("recommendation", "Recommendation"),
    ]
    nav = "".join(f"<a href=\"#{anchor}\">{label}</a>" for anchor, label in nav_items)
    title = f"Patch Review Report — {cfg.release} — {date_str}"

    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{escape(title)}</title>
  <style>
    :root {{
      --ink: #182026;
      --muted: #6a747c;
      --paper: #f6f1e8;
      --panel: #fffaf1;
      --line: #dfd2bd;
      --accent: #b45f06;
      --good: #146c43;
      --warn: #9a6700;
      --bad: #b42318;
      --info: #175cd3;
      --shadow: 0 18px 45px rgba(65, 47, 25, 0.13);
    }}
    * {{ box-sizing: border-box; }}
    html {{ scroll-behavior: smooth; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, rgba(180, 95, 6, 0.15), transparent 30rem),
        linear-gradient(135deg, #f8f2e7 0%, #efe3d0 100%);
      font-family: Georgia, "Times New Roman", serif;
      line-height: 1.55;
    }}
    .layout {{
      display: grid;
      grid-template-columns: 18rem minmax(0, 1fr);
      min-height: 100vh;
    }}
    aside {{
      position: sticky;
      top: 0;
      height: 100vh;
      padding: 2rem 1.5rem;
      background: #211a14;
      color: #fff4df;
      border-right: 6px solid var(--accent);
    }}
    aside h1 {{
      margin: 0 0 0.5rem;
      font-size: 1.35rem;
      line-height: 1.2;
    }}
    aside p {{
      margin: 0 0 1.5rem;
      color: #dcc7a8;
      font-size: 0.92rem;
    }}
    nav a {{
      display: block;
      padding: 0.55rem 0;
      color: #fff4df;
      text-decoration: none;
      border-bottom: 1px solid rgba(255, 244, 223, 0.14);
    }}
    nav a:hover {{ color: #ffd28a; }}
    main {{ padding: 2.2rem clamp(1rem, 4vw, 4rem); }}
    header {{
      max-width: 72rem;
      margin-bottom: 1.5rem;
      padding: 1.5rem 1.7rem;
      background: rgba(255, 250, 241, 0.78);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    header h1 {{
      margin: 0;
      font-size: clamp(1.8rem, 3vw, 3.2rem);
      line-height: 1.1;
      letter-spacing: -0.04em;
    }}
    .generated {{ color: var(--muted); margin-top: 0.6rem; }}
    section {{
      max-width: 72rem;
      margin: 1.2rem 0;
      padding: 1.4rem 1.6rem;
      background: var(--panel);
      border: 1px solid var(--line);
      box-shadow: var(--shadow);
    }}
    h2 {{
      margin: 0 0 1rem;
      font-size: 1.35rem;
      letter-spacing: -0.02em;
    }}
    h3 {{ margin: 1rem 0 0.5rem; }}
    .summary-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(11rem, 1fr));
      gap: 0.9rem;
    }}
    .card {{
      min-height: 6rem;
      padding: 1rem;
      background: #fffdf8;
      border: 1px solid var(--line);
    }}
    .card span:first-child {{
      display: block;
      color: var(--muted);
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      margin-bottom: 0.7rem;
    }}
    .card strong {{ font-size: 1.5rem; }}
    .badge {{
      display: inline-block;
      padding: 0.22rem 0.55rem;
      border-radius: 999px;
      color: white;
      font-family: "Courier New", monospace;
      font-size: 0.84rem;
      font-weight: 700;
      letter-spacing: 0.02em;
    }}
    .badge.good {{ background: var(--good); }}
    .badge.warn {{ background: var(--warn); }}
    .badge.bad {{ background: var(--bad); }}
    .badge.info {{ background: var(--info); }}
    .badge.muted {{ background: var(--muted); }}
    .table-wrap {{ overflow-x: auto; }}
    table {{
      width: 100%;
      border-collapse: collapse;
      background: #fffdf8;
      border: 1px solid var(--line);
    }}
    th, td {{
      padding: 0.65rem 0.75rem;
      border-bottom: 1px solid var(--line);
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #2d241c;
      color: #fff4df;
      font-size: 0.78rem;
      letter-spacing: 0.08em;
      text-transform: uppercase;
    }}
    code {{
      padding: 0.08rem 0.3rem;
      border-radius: 0.25rem;
      background: #efe3d0;
      font-family: "Courier New", monospace;
      font-size: 0.9em;
    }}
    .meta-list {{
      display: grid;
      grid-template-columns: max-content minmax(0, 1fr);
      gap: 0.55rem 1rem;
    }}
    .meta-list dt {{
      color: var(--muted);
      font-weight: 700;
    }}
    .meta-list dd {{ margin: 0; }}
    .warning-list li::marker {{ color: var(--warn); }}
    blockquote {{
      margin: 1rem 0 0;
      padding: 0.8rem 1rem;
      border-left: 0.35rem solid var(--warn);
      background: #fff4d6;
    }}
    .checkline {{
      display: block;
      margin: 0.6rem 0;
      padding: 0.85rem;
      background: #fffdf8;
      border: 1px solid var(--line);
    }}
    .empty {{ color: var(--muted); font-style: italic; }}
    @media (max-width: 820px) {{
      .layout {{ display: block; }}
      aside {{
        position: relative;
        height: auto;
      }}
      nav {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(8rem, 1fr));
        gap: 0 1rem;
      }}
    }}
  </style>
</head>
<body>
  <div class="layout">
    <aside>
      <h1>Patch Review</h1>
      <p>{escape(cfg.release)} · {escape(date_str)}</p>
      <nav>{nav}</nav>
    </aside>
    <main>
      <header>
        <h1>{escape(title)}</h1>
        <div class="generated">Generated: {escape(generated)}</div>
      </header>
      {''.join(sections)}
    </main>
  </div>
</body>
</html>
"""


def _html_output_path(markdown_path: Path) -> Path:
    return markdown_path.with_suffix(".html")


def main():
    parser = argparse.ArgumentParser(description="Generate patch review report")
    parser.add_argument("--date", default=today_str(), help="Staging date (default: today)")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    parser.add_argument(
        "--output",
        help="Markdown output file path (HTML uses the same path with .html suffix)",
    )
    args = parser.parse_args()

    cfg = Config.load(args.repo)
    staging = cfg.staging_path / args.date

    if not staging.is_dir():
        print(f"❌ No staged patches for {args.date}")
        sys.exit(1)

    report = generate_report(staging, cfg)
    html_report = generate_html_report(staging, cfg)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = staging / "REVIEW_REPORT.md"
    html_out_path = _html_output_path(out_path)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    html_out_path.write_text(html_report)
    print(f"🌐 HTML report saved to {html_out_path} (open this for review)")
    print(f"📄 Markdown report saved to {out_path} (edit the LGTM checkbox here to approve)")
    print(f"\n{report}")


if __name__ == "__main__":
    main()
