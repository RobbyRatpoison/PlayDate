# Plugin System — Implementation Plan

## Goals

- Non-Steam library integrations (GOG, Epic, etc.) become optional plugins
- Core app stays lean; users install only what they need
- GOG integration serves as the reference implementation

## Database Changes

### Composite key / internal ID
Replace the current negative-integer appid hack with a proper identity model:
- `appid` becomes an internal auto-increment INTEGER (primary key, stable)
- Add `platform` column: `'steam'`, `'gog'`, `'epic'`, etc. (what launcher runs the game)
- Add `source` column: which plugin added the row (e.g. `'steam'`, `'gog'`, `'playnite'`) — usually matches `platform` but not always
- Add `native_id` column: TEXT, the platform's own identifier (Steam appid, GOG product ID, etc.)
- Unique constraint on `(platform, native_id)`

On uninstall, core does: `DELETE FROM games WHERE source = 'plugin_name'`

### No plugin-specific columns
Plugins read/write only the standard `games` columns. No platform-specific columns are added to `games`. Plugins manage their own tables (e.g. OAuth tokens, order history) freely, keyed to the internal `appid`.

Achievements stay in existing achievement columns — no separate table needed.

## Plugin Discovery

Directory convention: drop a folder into `plugins/` and the app picks it up on startup. Future: UI to streamline install/enable.

Plugin folder structure:
```
plugins/
  gog/
    plugin.json       # manifest
    __init__.py       # entry point
    routes.py         # Flask blueprint (optional)
    templates/        # Jinja2 templates (optional)
    static/           # CSS/JS/assets (optional)
```

Plugins are auto-discovered on startup. May add explicit enable/disable toggle in `config.json` later.

## Plugin Manifest (`plugin.json`)

```json
{
  "id": "gog",
  "name": "GOG",
  "version": "1.0.0",
  "platform": "gog",
  "author": ""
}
```

## Plugin Interface

Each plugin's `__init__.py` exports a class or object implementing:

- `register(app)` — receives the Flask app; registers blueprint, DB migrations, etc.
- `sync()` — pulls library from the platform and upserts into `games`
- `on_uninstall()` — cleanup hook (drop plugin-owned tables, etc.); core handles `DELETE FROM games WHERE source = id`

## Navbar Extension

Plugins can register additional navbar pages via their Flask blueprint. Pages use full `base.html` inheritance, getting the navbar, theme system, gamepad nav, and modal infrastructure for free. Plugins can override any block they don't need.

Nav ordering: core pages always first, plugin pages appended in consistent order.

## Frontend

- Plugin pages inherit `base.html`
- Plugins can inject CSS/JS via template blocks
- Plugin static assets served under `/plugins/<id>/static/`

## Migration Path

1. Schema migration: add `native_id`, `source`, convert `appid` to internal integer
2. Update all routes (`SignedIntConverter` → plain int, no negative handling needed)
3. Update all internal references from appid-as-platform-id to internal appid
4. Extract GOG integration into `plugins/gog/` as reference implementation
5. Extract Steam integration into `plugins/steam/` (built-in but same structure)
6. Plugin loader in `main.py` / `app.py`

## Open Questions

- Whether plugins ever get distributed as installable packages (PyPI / zip download) — for now, manual folder drop is sufficient
- UI for plugin management (list installed, enable/disable, uninstall)
