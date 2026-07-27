#!/usr/bin/env python3
"""Dev tool: scan PAGYWOSG event(s) and report which categories aren't
automated yet.

Categories are fetched fresh from pagywosg.xyz — there's no static list to
keep in sync. Each one is run through the same pagywosg.classify_category()
the app uses, keyed off its 'reason' field:

  automated      — a regex branch recognized it (tag/date/title/HLTB pattern,
                   the gifter/icaio/santa special cases, etc.)
  not automated  — nothing recognized it. It might still work this month via
                   SteamGifts' own mod-verified entries (shown as a detail),
                   but that's luck, not a pattern — these are the ones to
                   either write a regex for or mark as permanently manual.

Usage:
    python tools/pagywosg_category_scan.py                  # current event
    python tools/pagywosg_category_scan.py --next            # upcoming event
    python tools/pagywosg_category_scan.py --event 80        # one specific event
    python tools/pagywosg_category_scan.py --events 70-86    # a range, deduped
    python tools/pagywosg_category_scan.py --events 70-86 --triage
                                                              # walk through
                                                              # undecided
                                                              # not-automated
                                                              # categories;
                                                              # for each, mark
                                                              # non-automatable,
                                                              # always-personal,
                                                              # or leave open

Decisions ("this will never be automated") persist in
pagywosg_scan_decisions.json next to your other local state files, keyed by
category base name. Anything not marked there keeps showing up every scan
until it's either marked or a pattern is added for it.

Categories marked "always-personal" during --triage go into
pagywosg_personal_defaults.json instead — unlike the decisions file, that one
is tracked in git and ships with the app, so every user's install pre-checks
that category as personal (still per-user toggle-able) for the event(s) it
was reviewed against.
"""
import argparse
import json
import os
import re
import sys
import time
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pagywosg
from config import BASE_DIR

DECISIONS_PATH = os.path.join(BASE_DIR, 'pagywosg_scan_decisions.json')
PERSONAL_DEFAULTS_PATH = os.path.join(BASE_DIR, pagywosg.PERSONAL_DEFAULTS_PATH)

_SUFFIX_RE = re.compile(r'\s*\((win|backlog)\)\s*$', re.IGNORECASE)

# reasons that mean "nothing recognized this" — see classify_category()'s docstring.
_UNAUTOMATED_REASONS = {'verified_fallback', 'unhandled'}


def _current_event_id():
    # Same anchor as app.py's pagywosg_auto(): event 83 = April 2026.
    today = date.today()
    return 83 + (today.year - 2026) * 12 + (today.month - 4)


def _load_decisions():
    try:
        with open(DECISIONS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_decisions(decisions):
    with open(DECISIONS_PATH, 'w', encoding='utf-8') as f:
        json.dump(decisions, f, indent=2, sort_keys=True)


def _load_personal_defaults_full():
    try:
        with open(PERSONAL_DEFAULTS_PATH, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}


def _save_personal_defaults_full(data):
    with open(PERSONAL_DEFAULTS_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, sort_keys=True)


def classify_event(event_id):
    """Fetch + classify one event. Returns list of per-category result dicts."""
    event = pagywosg.fetch_event(event_id)
    categories = event.get('gameCategories', [])
    entries = event.get('entries', [])

    base_to_cats = {}
    for cat in categories:
        base = _SUFFIX_RE.sub('', cat['name']).strip()
        base_to_cats.setdefault(base, []).append(cat)

    all_pool_bases = set()
    for base, cats in base_to_cats.items():
        names_lc = [c['name'].lower() for c in cats]
        if any('(win)' in n for n in names_lc) and any('(backlog)' in n for n in names_lc):
            all_pool_bases.add(base)

    verified_by_cat = {}
    for entry in entries:
        if entry.get('verified'):
            cid = str(entry['category']['id'])
            verified_by_cat.setdefault(cid, {})[entry['game']['id']] = entry['game']['name']

    icaio_ga, icaio_wl, santa = pagywosg.load_supplements()

    results = []
    for base, cats in base_to_cats.items():
        pool = 'all' if base in all_pool_bases else 'wins'
        base_appids = {}
        for cat in cats:
            base_appids.update(verified_by_cat.get(str(cat['id']), {}))

        classified = pagywosg.classify_category(base, base_appids, icaio_ga, icaio_wl, santa)
        # Only 'game title with X, Y' ever returns >1 item, and all items
        # share the same reason/type in that case — the first is representative.
        first = classified[0]
        automated = first['reason'] not in _UNAUTOMATED_REASONS
        n_verified = len(first['appids']) if first['type'] == 'appids' else 0

        if first['type'] == 'tag':
            detail = f"tag \"{first['tag']}\""
        elif first['type'] == 'cond':
            detail = f"op={first['op']}"
        elif first['type'] == 'appids':
            detail = f"{n_verified} verified appid(s)" + (' (auto)' if first.get('auto') else '')
        else:
            detail = 'skipped'

        results.append({
            'base': base, 'pool': pool, 'event_id': event_id,
            'automated': automated, 'reason': first['reason'],
            'n_verified': n_verified, 'detail': detail,
        })
    return event, results


def _parse_event_range(spec):
    if '-' in spec:
        a, b = spec.split('-', 1)
        a, b = int(a), int(b)
        if a > b:
            a, b = b, a
        return list(range(a, b + 1))
    return [int(spec)]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--next', action='store_true', help='scan the upcoming event')
    parser.add_argument('--event', type=int, metavar='N', help='scan exactly event N')
    parser.add_argument('--events', metavar='A-B', help='scan a range of event ids, e.g. 70-86')
    parser.add_argument('--all', action='store_true',
                         help='also print automated categories (default: only not-automated ones, plus a count)')
    parser.add_argument('--triage', action='store_true',
                         help='interactively mark not-automated categories as non-automatable')
    args = parser.parse_args()

    if args.events:
        event_ids = _parse_event_range(args.events)
    elif args.event is not None:
        event_ids = [args.event]
    elif args.next:
        event_ids = [_current_event_id() + 1]
    else:
        event_ids = [_current_event_id()]

    all_results = []
    event_names = {}
    for i, eid in enumerate(event_ids):
        try:
            event, results = classify_event(eid)
        except Exception as e:
            print(f"  event {eid}: could not fetch — {e}", file=sys.stderr)
            continue
        event_names[eid] = event.get('name', '')
        all_results.extend(results)
        if len(event_ids) > 1:
            print(f"  event {eid} ({event_names[eid]}): {len(results)} categories", file=sys.stderr)
            time.sleep(0.2)

    if not all_results:
        print("No categories fetched.", file=sys.stderr)
        sys.exit(1)

    decisions = _load_decisions()

    automated = [r for r in all_results if r['automated']]
    unautomated = [r for r in all_results if not r['automated']]

    # Dedupe not-automated categories by base name across a multi-event scan,
    # keeping the most recent event's detail and merging the event id list.
    by_base = {}
    for r in sorted(unautomated, key=lambda r: r['event_id']):
        entry = by_base.setdefault(r['base'], {**r, 'events': []})
        entry['events'].append(r['event_id'])
        entry['pool'], entry['detail'], entry['n_verified'], entry['reason'] = (
            r['pool'], r['detail'], r['n_verified'], r['reason'])
    unautomated_deduped = sorted(by_base.values(), key=lambda r: -max(r['events']))

    print(f"\n{len(event_ids)} event(s) scanned, {len(all_results)} category-instances, "
          f"{len(automated)} automated, {len(unautomated_deduped)} distinct not-automated categories.\n")

    decided = [r for r in unautomated_deduped if decisions.get(r['base']) == 'non_automatable']
    undecided = [r for r in unautomated_deduped if decisions.get(r['base']) != 'non_automatable']

    if undecided:
        print(f"NOT AUTOMATED — undecided ({len(undecided)}):")
        for r in undecided:
            ev = r['events'][0] if len(r['events']) == 1 else f"{min(r['events'])}-{max(r['events'])}"
            print(f"  - {r['base']}  [{r['pool']} pool, event {ev}]  — {r['detail']}")
        print()
    else:
        print("No undecided not-automated categories.\n")

    if decided:
        suffix = ":" if args.all else " (use --all to list)"
        print(f"NOT AUTOMATED — marked non-automatable ({len(decided)}){suffix}")
        if args.all:
            for r in decided:
                print(f"  - {r['base']}")
        print()

    if args.all:
        print(f"AUTOMATED ({len(automated)}):")
        for r in automated:
            print(f"  - {r['base']}  [{r['pool']} pool, event {r['event_id']}]  → reason={r['reason']}, {r['detail']}")
        print()

    if args.triage:
        _run_triage(undecided, decisions)


def _run_triage(undecided, decisions):
    if not undecided:
        print("Nothing to triage.")
        return
    print(f"--- Triage: {len(undecided)} undecided categories ---")
    print("For each: [n] mark non-automatable  [p] mark always-personal  [s] skip / decide later  [q] quit triage\n")
    changed = False
    personal_changed = False
    personal_defaults = _load_personal_defaults_full()
    for i, r in enumerate(undecided):
        ev = r['events'][0] if len(r['events']) == 1 else f"{min(r['events'])}-{max(r['events'])}"
        print(f"[{i+1}/{len(undecided)}] \"{r['base']}\"  ({r['pool']} pool, event {ev}, {r['detail']})")
        try:
            choice = input("  > ").strip().lower()
        except EOFError:
            break
        if choice == 'q':
            break
        if choice == 'n':
            decisions[r['base']] = 'non_automatable'
            changed = True
            print("  marked non-automatable.")
        elif choice == 'p':
            # A personal category is inherently not something a regex could
            # automate either, so this also records non_automatable locally.
            decisions[r['base']] = 'non_automatable'
            changed = True
            for eid in r['events']:
                bucket = personal_defaults.setdefault(str(eid), [])
                if r['base'] not in bucket:
                    bucket.append(r['base'])
            personal_changed = True
            print(f"  marked always-personal for event(s) {', '.join(str(e) for e in r['events'])}.")
        # 's' or anything else: leave undecided, move on
    if changed:
        _save_decisions(decisions)
        print("\nDecisions saved.")
    if personal_changed:
        _save_personal_defaults_full(personal_defaults)
        print(f"{PERSONAL_DEFAULTS_PATH} changed — this file is tracked in git, "
              "remember to commit it so other installs pick it up.")


if __name__ == '__main__':
    main()
