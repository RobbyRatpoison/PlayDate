"""Pick 6: 'what should I play next' page and scoring engine. See CLAUDE.md's
Pick 6 Scoring section for the six signals (tag similarity, review score,
staleness, completion bias, playtime, release recency) and the fallback to
top-50-most-played when there are no beaten games."""
import logging
import random

from flask import Blueprint, jsonify, render_template, request

from database import get_db

log = logging.getLogger(__name__)

pick_bp = Blueprint('pick', __name__)

COMPLETION_STATUSES = ['Never Played', 'Unfinished', 'Beaten', 'Completed', "Won't Play"]


def _build_pick_where(state, use_filtered):
    """WHERE clause (active filter + hidden platforms + hide_duplicates) shared
    by pick_game and pick_status_counts, before any completion_status condition
    is applied."""
    from library import build_tree_sql, _strip_sql_wrapper, is_safe_sql

    params = []
    where = '1=1'

    if use_filtered:
        from config import resolve_active_filter_tree
        filter_tree = resolve_active_filter_tree(state)
        if filter_tree:
            custom_sql = _strip_sql_wrapper(filter_tree.get('custom_sql', ''))
            if custom_sql:
                where = custom_sql if is_safe_sql(custom_sql) else '1=0'
            else:
                tree_sql = build_tree_sql(filter_tree, params)
                if tree_sql and tree_sql != '1=1':
                    where = tree_sql

    hidden_platforms = state.get('hidden_platforms') or []
    if hidden_platforms:
        plat_conds = []
        if 'steam' in hidden_platforms:
            plat_conds.append("platform != 'steam'")
        non_steam_hidden = [p for p in hidden_platforms if p != 'steam']
        if non_steam_hidden:
            ph = ','.join('?' * len(non_steam_hidden))
            plat_conds.append(f"platform NOT IN ({ph})")
            params = list(params) + non_steam_hidden
        if plat_conds:
            where = f"({where}) AND ({' AND '.join(plat_conds)})"

    if state.get('hide_duplicates', True):
        dup_cond = "(duplicate_of IS NULL OR duplicate_of = '')"
        where = dup_cond if where == '1=1' else f"({where}) AND {dup_cond}"

    return where, params


@pick_bp.route('/pick')
def pick():
    from config import load_state, resolve_active_filter_tree, BUILTIN_FILTERS
    state = load_state()
    raw_ft = state.get('filter_tree')
    ft = resolve_active_filter_tree(state)
    state['filter_tree'] = ft  # modal sees expanded tree (mirrors library.py)
    has_filters = bool(ft and (ft.get('items') or ft.get('custom_sql')))
    filter_name = None
    if isinstance(raw_ft, dict):
        if 'saved_filter' in raw_ft:
            filter_name = raw_ft['saved_filter']
        elif raw_ft.get('custom_sql'):
            cs = raw_ft['custom_sql']
            for bf in BUILTIN_FILTERS.values():
                if bf.get('where') == cs:
                    filter_name = bf['label']
                    break
    return render_template('pick.html', state=state, has_filters=has_filters, filter_name=filter_name)

@pick_bp.route('/api/pick-game', methods=['POST'])
def pick_game():
    from config import load_state

    data         = request.json or {}
    mode         = data.get('mode', 'random')
    use_filtered = data.get('use_filtered', False)
    statuses     = data.get('statuses', None)  # None means all statuses
    w_tags      = float(data.get('w_tags',      65))
    w_review    = float(data.get('w_review',    35))
    w_staleness = float(data.get('w_staleness',  0))
    w_recency   = float(data.get('w_recency',    0))
    w_hltb      = float(data.get('w_hltb',       0))

    def _parse_bound(key):
        v = data.get(key)
        return float(v) if v is not None else None

    b_review    = _parse_bound('b_review')
    b_staleness = _parse_bound('b_staleness')
    b_recency   = _parse_bound('b_recency')
    b_hltb      = _parse_bound('b_hltb')

    state  = load_state()
    db     = get_db()
    where, params = _build_pick_where(state, use_filtered)

    if statuses is not None:
        placeholders = ','.join('?' * len(statuses))
        where = f"({where}) AND completion_status IN ({placeholders})"
        params = list(params) + list(statuses)

    # Smart mode auto-bounds: apply a minimum review floor automatically.
    if mode == 'smart' and b_review is None:
        b_review = 70.0

    try:
        rows = db.execute(f"SELECT * FROM games WHERE {where}", params).fetchall()
    except Exception as e:
        db.close()
        return jsonify({"status": "error", "message": f"Filter error: {e}"}), 400

    games = [dict(r) for r in rows]

    if not games:
        db.close()
        return jsonify({"status": "error", "message": "No games matched the current filters."})

    NUM_PICKS = 6
    picks = []
    any_relaxed = False
    bounded_pool_size = len(games)

    if mode in ('smart', 'weighted'):
        profile_rows = db.execute(
            "SELECT tags, playtime_forever FROM games "
            "WHERE completion_status IN ('Beaten', 'Completed') "
            "AND tags IS NOT NULL AND tags != ''"
        ).fetchall()

        using_fallback = False
        if not profile_rows:
            using_fallback = True
            profile_rows = db.execute(
                "SELECT tags, playtime_forever FROM games "
                "WHERE tags IS NOT NULL AND tags != '' "
                "ORDER BY playtime_forever DESC LIMIT 50"
            ).fetchall()

        db.close()

        tag_weights: dict[str, float] = {}
        for row in profile_rows:
            weight = max(float(row['playtime_forever'] or 0), 1.0)
            for tag in [t.strip() for t in (row['tags'] or '').split(',') if t.strip()]:
                tag_weights[tag] = tag_weights.get(tag, 0.0) + weight

        profile_norm = sum(v * v for v in tag_weights.values()) ** 0.5 or 1.0

        def tag_similarity(g):
            candidate_tags = [t.strip() for t in (g.get('tags') or '').split(',') if t.strip()]
            if not candidate_tags:
                return 0.0, []
            dot    = sum(tag_weights.get(t, 0.0) for t in candidate_tags)
            c_norm = len(candidate_tags) ** 0.5
            sim    = dot / (profile_norm * c_norm) if (profile_norm * c_norm) else 0.0
            matched = sorted([t for t in candidate_tags if t in tag_weights],
                             key=lambda t: tag_weights[t], reverse=True)
            return sim, matched

        def review_score(g):
            wp = g.get('weighted_percentage')
            rp = g.get('review_percentage')
            if wp is not None and wp != '': return float(wp) / 100.0
            if rp is not None and rp != '': return float(rp) / 100.0
            return None

        def staleness_score(g):
            from datetime import datetime, timezone
            now = datetime.now(timezone.utc).timestamp()
            lp = g.get('last_played')
            if lp:
                try:
                    return min((now - float(lp)) / 86400, 730) / 730.0
                except Exception:
                    return 0.5
            return 1.0

        def hltb_length_score(g):
            # Returns [0,1] where 1 = longest, or None if no data.
            # sqrt curve concentrates probability at the extremes so moderate
            # lengths don't crowd out clearly short/long games.
            import math
            times = [v for v in [g.get('hltb_main'), g.get('hltb_extras'), g.get('hltb_completionist')] if v]
            if not times:
                return None  # handled as low (not neutral) by sig() via unknown_val
            if w_hltb >= 0:
                # Prefer long: max time, floor at 10hrs, scale over 100hrs above floor.
                # 10hr → 0, 35hr → 0.5, 110hr+ → 1.0
                val = max(times)
                return math.sqrt(max(0.0, min(float(val) - 600.0, 6000.0) / 6000.0)
)
            else:
                # Prefer short: min time, cap at 10hrs.
                # 0hr → 0, 2.5hr → 0.5, 10hr+ → 1.0
                val = min(times)
                return math.sqrt(min(float(val), 600.0) / 600.0)

        def recency_score(g):
            rd = g.get('release_date')
            if not rd:
                return 0.5
            try:
                from datetime import datetime, timezone
                year = datetime.fromtimestamp(float(rd), tz=timezone.utc).year
                age_years = max(datetime.now().year - year, 0)
                return 1.0 - min(age_years, 10) / 10.0
            except Exception:
                return 0.5

        def score_game(g, relax_factor=0.0):
            sim, matched = tag_similarity(g)
            rev  = review_score(g)
            stal = staleness_score(g)
            rec  = recency_score(g)
            hltb = hltb_length_score(g)

            if relax_factor < 1.0:
                w_rev_dir = w_review if mode == 'weighted' else 35.0
                if b_review is not None:
                    if rev is None:
                        return None
                    rev_pct = rev * 100
                    if w_rev_dir >= 0:
                        if rev_pct < b_review * (1 - relax_factor):
                            return None
                    else:
                        if rev_pct > b_review + (100 - b_review) * relax_factor:
                            return None
                if b_staleness is not None:
                    from datetime import datetime, timezone as _tzb
                    _now = datetime.now(_tzb.utc).timestamp()
                    _lp  = g.get('last_played')
                    _days = (_now - float(_lp)) / 86400 if _lp else 999999.0
                    if w_staleness >= 0:
                        if _days < b_staleness * (1 - relax_factor):
                            return None
                    else:
                        if _days > b_staleness * (1 + 9 * relax_factor):
                            return None
                if b_recency is not None:
                    _rd = g.get('release_date')
                    if not _rd:
                        return None
                    try:
                        from datetime import datetime, timezone as _tzc
                        _yr = datetime.fromtimestamp(float(_rd), tz=_tzc.utc).year
                        if w_recency >= 0:
                            if _yr < b_recency - relax_factor * (b_recency - 1970):
                                return None
                        else:
                            _cur_yr = datetime.now(_tzc.utc).year
                            if _yr > b_recency + relax_factor * (_cur_yr - b_recency):
                                return None
                    except Exception:
                        return None
                if b_hltb is not None:
                    _times = [v for v in [g.get('hltb_main'), g.get('hltb_extras'), g.get('hltb_completionist')] if v]
                    if not _times:
                        return None
                    if w_hltb >= 0:
                        if max(_times) / 60 < b_hltb * (1 - relax_factor):
                            return None
                    else:
                        if min(_times) / 60 > b_hltb * (1 + 9 * relax_factor):
                            return None

            if mode == 'weighted':
                total_w = (abs(w_tags) + abs(w_review) + abs(w_staleness) + abs(w_recency) + abs(w_hltb)) or 1.0
                def sig(w_raw, score, unknown_val=0.5):
                    # Apply signal: direction flips score if negative.
                    # unknown_val controls contribution when score is None (missing data).
                    if w_raw == 0:
                        return 0.0
                    s = unknown_val if score is None else score
                    norm = abs(w_raw) / total_w
                    return norm * s if w_raw > 0 else norm * (1.0 - s)
                final = (sig(w_tags, sim) + sig(w_review, rev, unknown_val=0.1) + sig(w_staleness, stal)
                         + sig(w_recency, rec, unknown_val=0.1) + sig(w_hltb, hltb, unknown_val=0.1))
            else:
                final = 0.65 * sim + 0.35 * (rev if rev is not None else 0.1)

            return final, sim, matched

        has_bounds = any(b is not None for b in [b_review, b_staleness, b_recency, b_hltb])
        if has_bounds:
            bounded_pool_size = sum(1 for g in games if score_game(g) is not None)
        remaining = list(games)
        for _ in range(min(NUM_PICKS, len(remaining))):
            scored = []
            for g in remaining:
                result = score_game(g)
                if result is not None:
                    scored.append((result, g))
            this_relaxed = False
            if not scored and has_bounds:
                for step in range(1, 21):
                    f = step * 0.05
                    scored = []
                    for g in remaining:
                        result = score_game(g, relax_factor=f)
                        if result is not None:
                            scored.append((result, g))
                    if scored:
                        this_relaxed = True
                        any_relaxed = True
                        break
            if not scored:
                break
            total  = sum(s[0] for s, _ in scored)

            if total == 0:
                game = random.choice([g for _, g in scored])
                final, sim, matched = 0.0, 0.0, []
            else:
                r          = random.random() * total
                cumulative = 0.0
                game       = scored[-1][1]
                final, sim, matched = scored[-1][0]
                for (f, s, m), g in scored:
                    cumulative += f
                    if r <= cumulative:
                        game, _, _, matched = g, f, s, m
                        break

            rev = review_score(game)
            cs  = game.get('completion_status', '')
            profile_desc = "your most-played games" if using_fallback else "games you've beaten"

            # Determine factor order: weighted mode uses slider values; smart uses fixed weights.
            if mode == 'weighted':
                factor_order = sorted([
                    ('tags', w_tags), ('review', w_review), ('staleness', w_staleness),
                    ('recency', w_recency), ('hltb', w_hltb),
                ], key=lambda x: abs(x[1]), reverse=True)
            else:
                factor_order = [('tags', 65.0), ('review', 35.0)]

            from datetime import datetime, timezone as _tz
            phrases = []
            for _key, _w in factor_order:
                if _w == 0 or len(phrases) >= 3:
                    continue
                _p = None
                if _key == 'tags':
                    if _w > 0 and matched:
                        _p = f"matches {profile_desc} on {', '.join(matched[:3])}"
                elif _key == 'review':
                    if rev is not None:
                        _pct = int(rev * 100)
                        _p = f"well reviewed ({_pct}%)" if _w > 0 else f"low-reviewed ({_pct}%)"
                elif _key == 'staleness':
                    _lp = game.get('last_played')
                    if _lp:
                        _days = (datetime.now(_tz.utc).timestamp() - float(_lp)) / 86400
                        if _w > 0:
                            if _days >= 365:
                                _p = f"last played {_days / 365:.0f}yr ago"
                            elif _days >= 30:
                                _p = f"last played {int(_days / 30)}mo ago"
                            else:
                                _p = f"last played {int(_days)}d ago"
                    elif _w > 0:
                        _p = "never played"
                elif _key == 'recency':
                    _rd = game.get('release_date')
                    if _rd:
                        try:
                            _year = datetime.fromtimestamp(float(_rd), tz=_tz.utc).year
                            _p = f"{_year} release"
                        except Exception:
                            pass
                elif _key == 'hltb':
                    _times = [v for v in [game.get('hltb_main'), game.get('hltb_extras'),
                                          game.get('hltb_completionist')] if v]
                    if _times:
                        _hrs = round((max(_times) if _w > 0 else min(_times)) / 60)
                        _p = f"~{_hrs}h to beat"
                if _p:
                    phrases.append(_p)

            if phrases:
                reason = '; '.join(phrases).capitalize() + '.'
            elif rev is not None:
                reason = f"Solid reviews ({int(rev * 100)}%)."
            else:
                reason = "Picked based on your library."

            if cs == 'Unfinished':
                reason += " You've started this one before."

            picks.append({"game": game, "reason": reason, "bounds_relaxed": this_relaxed})
            remaining = [g for g in remaining if g['appid'] != game['appid']]

    else:
        db.close()
        for g in random.sample(games, min(NUM_PICKS, len(games))):
            picks.append({"game": g, "reason": None})

    from library import _compute_outline_colors
    _outlines_cfg = state.get('card_outlines', {})
    pick_games = [p['game'] for p in picks]
    outline_map = _compute_outline_colors(pick_games, state) if _outlines_cfg.get('enabled', {}).get('pick6', True) else {}
    for p in picks:
        p['outline_color'] = outline_map.get(str(p['game']['appid']))

    return jsonify({
        "status":                "success",
        "picks":                 picks,
        "pool_size":             len(games),
        "bounded_pool_size":     bounded_pool_size,
        "bounds_relaxed":        any_relaxed,
    })


@pick_bp.route('/api/pick-status-counts', methods=['POST'])
def pick_status_counts():
    """Per-status game counts for greying out completion-status toggles: once for
    the whole library (a status nobody ever set, e.g. most users never mark
    anything 'Beaten' since nothing does it automatically) and, when the active
    filter is in play, once more under that filter (a status the filter excludes
    entirely, e.g. it already restricts to Never Played/Unfinished)."""
    from config import load_state

    data = request.json or {}
    use_filtered = data.get('use_filtered', False)
    state = load_state()
    db = get_db()

    def _counts(where, params):
        rows = db.execute(
            f"SELECT completion_status, COUNT(*) c FROM games WHERE ({where}) GROUP BY completion_status",
            params
        ).fetchall()
        counts = {s: 0 for s in COMPLETION_STATUSES}
        for r in rows:
            if r['completion_status'] in counts:
                counts[r['completion_status']] = r['c']
        return counts

    try:
        library_where, library_params = _build_pick_where(state, use_filtered=False)
        library_counts = _counts(library_where, library_params)

        filtered_counts = None
        if use_filtered:
            filtered_where, filtered_params = _build_pick_where(state, use_filtered=True)
            filtered_counts = _counts(filtered_where, filtered_params)
    except Exception as e:
        db.close()
        return jsonify({"status": "error", "message": f"Filter error: {e}"}), 400

    db.close()
    return jsonify({
        "status": "success",
        "library_counts": library_counts,
        "filtered_counts": filtered_counts,
    })
