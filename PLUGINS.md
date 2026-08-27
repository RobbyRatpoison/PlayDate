# Writing a PlayDate Plugin

Plugins add non-Steam library sources (GOG, Epic, EA App, etc.) to PlayDate. Nothing ships as source in the main PlayDate repo, including PlayDate's own first-party integrations — GOG, EA App, Epic Games, Humble Bundle, IndieGala, itch.io, and Ubisoft Connect are just plugins too, published as their own GitHub repos (`plugins.OFFICIAL_PLUGINS`) and installed the same way as any third-party plugin. Each plugin lives in its own subdirectory under a writable, update-safe directory and is auto-discovered at startup.

**Where plugins actually live:** `plugins._user_plugins_dir()`, which resolves to `BASE_DIR/plugins/` — the same base directory that already holds `config.json`/`games.db`. For a Flatpak install that's the app's isolated data directory, not the read-only `/app` mount; for a frozen build it's the folder next to the executable; for a source checkout it's this project's own `plugins/` folder (since `BASE_DIR` *is* the project root there, so it's literally the same physical directory you're looking at in this repo). PlayDate also still scans the bundled `plugins/` folder next to `plugins/__init__.py` for anything left over from the old single-directory layout, and migrates it into the writable directory automatically on startup — this only matters for a plugin manually dropped into that legacy location; a normal install never puts anything there.

## Installing a plugin

Users can install plugins four ways:

1. **Plugins modal → Plugin Catalog** (hamburger menu → Plugins) — one-click install for PlayDate's own first-party plugins (`plugins.OFFICIAL_PLUGINS`) and unfinished/experimental ones (`plugins.BETA_PLUGINS`), listed automatically whenever one isn't currently installed (`GET /api/plugins/catalog`). Grouped into expandable Working / Untested / Broken sections based on each entry's `platform_status` for whatever OS PlayDate is actually running on right now — not a full cross-platform matrix, just "is this worth trying on my system."
2. **Plugins modal → Install from Zip** — select a `.zip` file; the server validates it, extracts it to the writable plugins directory (see above), and prompts for restart.
3. **Plugins modal → Install from GitHub** — paste a GitHub repo URL (`github.com/owner/repo` or `owner/repo`); PlayDate fetches the latest release zip and installs it the same way.
4. **Manual drop** — copy the plugin folder directly into the writable plugins directory and restart.

The zip can be either flat (`plugin.json` at root) or wrapped in a single top-level folder (`myplugin/plugin.json`). The plugin `id` in `plugin.json` must be alphanumeric + underscores and determines the destination folder name.

Every install method requires a restart to actually take effect — Flask refuses to register a new Blueprint once the app has served its first request, so a freshly-installed plugin's code sits on disk, loaded but inactive, until the next launch.

If a plugin is hosted on GitHub and its `plugin.json` includes a `source` field, PlayDate will check for updates when the Plugins modal is opened and show a one-click update button when a newer release is available.

Uninstalling a plugin deletes its directory outright (`shutil.rmtree`) and clears its saved credentials/launcher config — this is what makes it stick across a PlayDate update now, since there's no bundled copy anywhere for an update to silently reintroduce.

## Directory layout

```
plugins/
  myplugin/
    __init__.py    # plugin class + singleton
    plugin.json    # manifest
    routes.py      # Flask Blueprint
    templates/     # optional UI fragments (see below)
    static/        # optional static assets (CSS, JS, images)
    watcher.py     # optional filesystem watcher
```

## plugin.json

```json
{
  "id":       "myplugin",
  "name":     "My Platform",
  "version":  "1.0.0",
  "platform": "myplugin",
  "author":   "",
  "source":   "github:owner/myplugin-repo"
}
```

The `id` and `platform` values must be unique across all plugins and must match the string you store in the `platform` column of the `games` table.

### `launcher` field (optional)

If your plugin needs a separate launcher application (e.g. Epic Games Store, EA App) to run games, declare it:

```json
"launcher": {
  "required": true,
  "name": "Epic Games Store",
  "exe_name": "EpicGamesLauncher.exe"
}
```

Set `"required": false` (or omit the field entirely) if your plugin can launch games without a separate launcher process. Core reads this field to drive launcher configuration UI -- no code changes are needed in the plugin itself beyond declaring it.

### `launcher.installer` field (optional) -- automated Wine-based launcher install

If your launcher can be installed unattended under Wine, declare an `installer` block and core will drive the whole install through `runners/launcher_installer.py` from a "Configure Launcher" button -- no plugin code needed:

```json
"launcher": {
  "required": true,
  "name": "My Launcher",
  "exe_name": "MyLauncher.exe",
  "installer": {
    "url": "https://example.com/MyLauncherInstaller.exe",
    "type": "exe",
    "winearch": "win64",
    "win_version": "win10",
    "winetricks": ["d3dcompiler_43", "corefonts"],
    "post_install_files": [
      {"path": "AppData\\Local\\My Launcher\\settings.yaml", "content": "overlay:\n  enabled: false"}
    ],
    "post_install_dlls": ["files/lib/wine/x86_64-windows/some.dll"],
    "install_path": "Program Files (x86)\\My Launcher",
    "env": {"SOME_VAR": "1"}
  }
}
```

Fields (all but `url` optional):
- `url` -- installer download URL.
- `type` -- `"msi"` (default), `"exe"` (run interactively -- the user completes the setup window), or `"extract"` (bypass the installer entirely and 7z-extract its payload directly into the prefix at `install_path`; for installers that refuse to run at all without admin rights under Wine).
- `winearch` -- `"win64"` (default) or `"win32"`.
- `win_version` -- if set, writes `HKCU\Software\Wine\Version` to this value (e.g. `"win10"`) right after prefix creation.
- `winetricks` -- list of verbs installed (in order) before the installer runs. Proton wine automatically falls back to system `wine` for this step (winetricks and Proton's own wine binary don't mix).
- `post_install_files` -- list of `{"path": ..., "content": ...}` written into the Wine user profile directory (`path` relative to it, backslashes accepted) after winetricks but *before* the installer runs -- for pre-seeding a config file the installer or first-run would otherwise create with different defaults (e.g. disabling an overlay before it ever gets a chance to inject itself).
- `post_install_dlls` -- list of paths (relative to the detected Proton build's root, e.g. `files/lib/wine/x86_64-windows/xyz.dll`) copied into the prefix's `system32` after the installer completes.
- `install_path` -- required for `type: "extract"` (destination under `drive_c`, backslashes accepted); unused for `msi`/`exe`.
- `env` -- extra environment variables merged in for every step (prefix creation, winetricks, install).

`exe_name` (used to verify the install actually succeeded) is read from `launcher.exe_name` if not also set directly on `installer`.

Progress is tracked through phases (`creating_prefix` -> `downloading` -> `installing` -> `verifying` -> `done`), pollable via `GET /api/launcher-install/<platform_id>/status` -- no plugin-side polling code needed, the built-in Configure Launcher UI handles it.

The optional `source` field enables update checking. Set it to `github:owner/repo` pointing to the GitHub repository where releases are published. PlayDate compares the installed `version` against the latest release tag (stripping a leading `v`) and surfaces an update link in the Plugins modal when a newer version is available. Updates download and overwrite the plugin folder in-place; a restart is required to load the new code.

### `min_core_version` field (optional)

If your plugin relies on a lifecycle method, field, or behavior introduced in a specific PlayDate release, declare the minimum core version it needs:

```json
"min_core_version": "1.7.0"
```

At startup, `load_all()` compares this against the running PlayDate version. If the installed core is older, the plugin is **not imported or registered** — it fails safely instead of crashing on a missing method/field or throwing at import time. It still shows up in the Plugins modal with a "needs PlayDate X.Y.Z" message (fetched from `GET /api/plugins/incompatible`) and can still be uninstalled from there; only `register()` and everything after it in `load_all()` is skipped. Omit the field if your plugin has no minimum version requirement.

This is also enforced earlier, at install/update time: installing a zip, a GitHub URL, or clicking Update in the Plugins modal all funnel through the same install path, which rejects the install outright with a user-facing error if your declared `min_core_version` exceeds the user's current PlayDate version — it won't silently install and then fail to load on next restart. If you're bumping `min_core_version` alongside new PlayDate release requirements, be aware that a plugin update released the same day as the PlayDate version it requires is deliberately not blocked by the "install updates then update core" bundled flow (it compares against the *target* core version being installed, not the currently-running one).

If a newer release of an already-installed plugin raises `min_core_version` past the user's current PlayDate, the Plugins modal shows it as "vX.Y.Z · needs PlayDate A.B.C" (not a clickable standalone update), but still offers it through the combined **Update PlayDate & Plugins** button on the update prompt, which installs it against the newer core.

## __init__.py — the plugin class

`plugins/__init__.py` calls `mod.plugin` on your package, so `__init__.py` must expose a `plugin` singleton.

```python
import logging

log = logging.getLogger(__name__)


class MyPlugin:
    id       = 'myplugin'
    name     = 'My Platform'   # fallback display label
    label    = 'My Platform'   # display label used in platform_labels(); defaults to name if absent
    platform = 'myplugin'

    def register(self, app):
        """Called once at startup. Register your Blueprint here."""
        from .routes import bp
        app.register_blueprint(bp)

    def on_startup(self):
        """Called after the Flask server and pywebview window are ready."""
        # start background threads, filesystem watchers, etc.
        pass

    def on_shutdown(self):
        """Called when the window closes. Stop any threads/watchers."""
        pass

    def sync(self):
        """Optional. Called when the user triggers a library sync."""
        pass

    # Optional class attribute. If your platform has an external orders/activation page
    # that the Tampermonkey date-import script should open, declare it here.
    # Core collects these from all plugins whose games are in a bulk date-import selection
    # and returns them as date_import_urls: [{url, label}] to the frontend.
    # date_import_url = 'https://example.com/account/orders'

    def launch_game(self, appid):
        """
        Optional. Called by core when the user clicks Play on a game with this platform.
        appid is the integer PlayDate appid (negative for non-Steam games).
        Must return a dict that will be JSON-serialised and sent to the frontend.
        Common shapes:
          {"status": "success", "last_played": <unix_ts>}
          {"status": "installing", "message": "Installing…",
           "install_poller": "_startMyInstallPoller"}   # JS fn name registered by your fragment
          {"status": "error", "message": "…"}
        Do NOT use platform-named flags like gog_install — use install_poller instead.
        Core calls window[install_poller](appid) if that function exists.
        If not implemented, core returns HTTP 501 for non-Steam platforms.
        """
        pass

    def on_game_launched(self, appid, platform):
        """
        Optional. Best-effort notification fired after ANY game launch is
        dispatched (not just this plugin's own platform — check `platform`
        if you only care about specific ones). Exceptions are caught and
        logged by core, never surfaced to the user, so this is safe for
        things like Discord rich presence or a launch-history log.
        """
        pass

    def on_library_updated(self):
        """
        Optional. Best-effort notification fired after populate/scrape-new-games
        finishes. Exceptions are caught and logged by core.
        """
        pass

    def rescrape(self, appid):
        """
        Optional. Called by bulk_rescrape_games() for games on this platform.
        Should fetch fresh metadata (name, genres, tags, achievements, etc.) and
        return a dict ready to pass to update_game_data(**meta), or None on failure.
        Include meta_fetched and cheevos_fetched date strings (YYYY-MM-DD) as needed.
        If not implemented, the game is skipped during bulk rescrape.
        """
        pass

    def fetch_description(self, appid, platform_id):
        """
        Optional. Called by GET /api/game-description/<appid> for non-Steam games.
        Return a plain-text description string, or None if unavailable.
        Core falls back to the Steam store API when this is not implemented.
        """
        pass

    def resync_installed(self):
        """
        Optional. Re-check installed-flag/install_path for every game on this
        platform (whatever your own on_startup()/install-watcher sync function
        already does — just call it here too). Called after a backup restore,
        and by bulk_rescrape_games() for every non-Steam platform it touched,
        once metadata that rescrape() just fetched could newly make install
        detection succeed for a game your own filesystem watcher never fired
        on (it wasn't a filesystem event, so the watcher wouldn't catch it).
        """
        pass

    def on_launcher_installed(self, prefix, wine_bin):
        """
        Optional. Called by the generic launcher installer
        (runners/launcher_installer.py) right after your launcher's installer
        finishes, before the install is reported done. Use it to fix up the
        freshly-installed launcher inside `prefix` — e.g. apply a vendor
        self-update the installer staged but can't run under Wine, which would
        otherwise loop the launcher on first start. `wine_bin` is the binary
        the install used (may be None). Only fires for plugins with a
        `launcher.installer` block in plugin.json.
        """
        pass

    def extra_info(self, appid, platform, platform_id):
        """
        Optional. Called by GET /api/game-extra-info/<appid>, for EVERY loaded
        game (any platform, not just this plugin's own — a price-tracker or
        alternate review-score plugin can annotate Steam games too). Return a
        list of {'label': str, 'value': str, 'url': str|None} dicts, or None.
        Shown in the library list view's detail pane, below the description.
        Called on every game-detail view, so avoid slow blocking calls where
        possible (e.g. cache upstream results yourself).
        """
        pass

    def launcher_status(self):
        """
        Optional. Implement this if plugin.json declares launcher.required: true.
        Called at startup and on demand (POST /api/plugins/launcher-status/<platform>).
        Must return a dict: {"available": bool, "detail": str}
        Example checks: is Wine installed? is the launcher .exe present in the configured prefix?
        The result is cached and exposed via GET /api/plugins/launcher-status.
        """
        pass

    def on_uninstall(self):
        """Optional. Clean up credentials/tokens when the plugin is removed."""
        pass

    def js_api(self):
        """Optional. Expose platform capabilities to core JS via window._PLUGIN_API."""
        return {
            'uninstall_url':     '/api/myplugin/uninstall/{appid}',  # POST; {appid} replaced at runtime
            'uninstall_confirm': 'Uninstall this game?\n\nThis will delete the game files from disk.',
            'scrape_url':        '/api/myplugin/scrape-single/{appid}',
            'scrape_method':     'POST',   # or 'GET'
            'store_url':         'https://example.com/game/{slug}',  # {slug} = platform_slug column
            'store_label':       'View on My Platform Store ↗',
            'appid_label':       'My Platform ID:',
            'sync_label':        'Sync My Platform Data',
            # Optional: extra entries in the game right-click menu, for games on
            # this platform. Static and declarative -- no server round trip when
            # the menu opens, same {appid}/{slug} templating as store_url above.
            'context_menu_items': [
                {
                    'label':       'Check Price History',
                    'action_type': 'open_url',           # 'open_url' | 'call'
                    'url_template': 'https://example.com/price/{appid}',
                    'visible_if':  'has_slug',            # optional: 'installed' | 'has_slug' | 'non_steam'
                },
                # {'label': 'Do Something', 'action_type': 'call', 'js_fn': 'myPluginCtxAction'},
            ],
        }

    def manage_ui(self):
        """
        Optional. Declare the plugin's Manage modal using built-in building blocks.
        Core renders the modal; a Manage button appears automatically on the plugin card.
        The modal ID follows the convention: {plugin_id}-manage-modal.

        Section fields:
          title (str)         — label shown above the section
          auth  (dict)        — optional; shows connected vs disconnected state
            endpoint (str)      — GET endpoint returning {connected, username}
            disconnected (list) — blocks shown when not connected
            connected    (list) — blocks shown when connected
          items (list)        — blocks shown unconditionally (use instead of auth)

        Block types:
          {type: 'text',           content: str}
          {type: 'connected_label'}               -- "Connected as {username}"
          {type: 'info_endpoint',  endpoint: str} -- GET returns {text, color}
          {type: 'button',  label: str, variant: 'muted'?, action: <action>}
          {type: 'buttons', items: [{label, variant?, action}]}
          {type: 'status_output',  key: str}      -- id: {plugin_id}-manage-status-{key}

        Action types:
          {type: 'call',       fn: str}                           -- call named JS function
          {type: 'open_url',   url: str}                          -- open in system browser
          {type: 'post',       endpoint: str, on_success: str?}   -- on_success: 'refresh_auth'
          {type: 'oauth_paste', title, url_endpoint, callback_endpoint,
                                instructions, input_placeholder, open_label, submit_label}

        Status output elements use the id pattern: {plugin_id}-manage-status-{key}.
        Plugin JS (tools_scripts fragment) can reference these by that id.
        """
        return {
            'sections': [
                {
                    'title': 'Account',
                    'auth': {
                        'endpoint': '/api/myplugin/status',
                        'disconnected': [
                            {'type': 'text', 'content': 'Connect your account to import your library.'},
                            {'type': 'button', 'label': 'Connect', 'action': {
                                'type': 'oauth_paste',
                                'title': 'Connect My Platform',
                                'url_endpoint': '/api/myplugin/auth-url',
                                'callback_endpoint': '/api/myplugin/callback',
                                'instructions': ['Open the login URL.', 'Log in.', 'Paste the redirect URL below.'],
                                'input_placeholder': 'https://...',
                                'open_label': 'Open Login',
                                'submit_label': 'Connect',
                            }},
                        ],
                        'connected': [
                            {'type': 'connected_label'},
                            {'type': 'buttons', 'items': [
                                {'label': 'Sync Library', 'action': {'type': 'call', 'fn': 'myPluginSync'}},
                                {'label': 'Disconnect', 'variant': 'muted', 'action': {'type': 'post', 'endpoint': '/api/myplugin/disconnect', 'on_success': 'refresh_auth'}},
                            ]},
                            {'type': 'status_output', 'key': 'main'},
                        ],
                    },
                },
            ],
        }

    def home_widgets(self):
        """
        Optional. Return [{'id': str, 'label': str}, ...] describing Home page
        shelf presets this plugin provides. Each id needs a matching
        'home_widget_<id>' entry in fragments() below, pointing at a template
        that renders the widget -- including its own <script> that fetches
        whatever data it needs from a route this plugin registers itself.
        Core passes no data in; the widget is fully self-sufficient.
        The id shows up as a selectable preset in the Home page shelf editor.
        """
        return [{'id': 'myplugin_stats', 'label': 'My Platform Stats'}]

    def fragments(self):
        """Optional. Map injection slot names to template filenames."""
        return {
            'base_head_styles':  'myplugin_base_head_styles.html',
            'base_nav_items':    'myplugin_base_nav_items.html',
            'base_body_scripts': 'myplugin_base_scripts.html',
            'tools_scripts':     'myplugin_tools_scripts.html',
            'home_widget_myplugin_stats': 'myplugin_stats_widget.html',
        }


plugin = MyPlugin()
```

All lifecycle methods except `register` are optional — omit the ones you don't need.

## routes.py — Flask Blueprint

Use a Blueprint with a `/api/<plugin-id>` prefix. Add `template_folder='templates'` so Jinja2 can find your fragment templates. If you have static assets (CSS, JS, images), add `static_folder='static'` and `static_url_path='/plugins/<id>/static'` — files will be served at that URL path.

```python
from flask import Blueprint, jsonify, request
from database import get_db, update_game_data

bp = Blueprint('myplugin', __name__, url_prefix='/api/myplugin',
               template_folder='templates',
               static_folder='static',
               static_url_path='/plugins/myplugin/static')


@bp.route('/status')
def status():
    return jsonify({'connected': False})


@bp.route('/sync', methods=['POST'])
def sync():
    from .myplugin import sync_library
    result = sync_library()
    if 'error' in result:
        return jsonify({'status': 'error', 'message': result['error']}), 400
    return jsonify({'status': 'success', **result})
```

## UI fragments

Plugins inject UI into core pages via named slots. Each slot is a small HTML or JS file in `plugins/myplugin/templates/`. The loader collects all registered fragments at startup; if no plugin registers a slot, nothing is rendered there.

### Available slots

| Slot | Rendered inside | Use for |
|------|----------------|---------|
| `base_head_styles` | `<style>` block in `<head>` | CSS for elements your nav fragment adds |
| `base_nav_items` | Hamburger menu, after the populate button | Persistent status buttons (e.g. install progress) |
| `base_body_scripts` | `<script>` block at end of `<body>` | JS that must exist on every page |
| `tools_scripts` | `<script>` block in `modal_tools.html` | JS for the manage modal (sync handlers, etc.) |
| `home_widget_<id>` | Home page, in place of the shelf matching `shelf.preset == '<id>'` | A Home page shelf widget, declared via `home_widgets()` |

### Naming convention

Prefix template filenames with your plugin id to avoid collisions across plugins:

```
plugins/myplugin/templates/
  myplugin_base_head_styles.html
  myplugin_base_nav_items.html
  myplugin_base_scripts.html
  myplugin_tools_scripts.html
```

### Example: adding a nav button

`myplugin_base_nav_items.html`:
```html
<button id="myplugin-status-btn" class="hamburger-item" style="display:none;">MY PLATFORM: SYNCING...</button>
```

`myplugin_base_head_styles.html`:
```css
#myplugin-status-btn { color: var(--accent); font-weight: bold; }
```

`myplugin_base_scripts.html`:
```js
// JS that controls #myplugin-status-btn on every page
```

### Calling plugin functions from core JS

Core templates use `typeof` guards for any soft calls into plugin JS, so missing plugins don't cause errors:

```js
if (typeof _myPluginRefresh === 'function') _myPluginRefresh();
```

Define complex sync handlers (e.g. `myPluginSync`) in your `tools_scripts` fragment and reference them by name in `manage_ui()` button actions using `{type: 'call', fn: 'myPluginSync'}`. Status output elements follow the id pattern `{plugin_id}-manage-status-{key}` so your JS can update them directly.

## Database integration

### Appid allocation

Non-Steam games use **negative integer appids** to avoid collisions with Steam. Allocate the next available one inside a single DB connection:

```python
def _next_negative_appid(db):
    row = db.execute('SELECT MIN(appid) FROM games WHERE appid < 0').fetchone()
    return (row[0] - 1) if row[0] is not None else -1
```

### Inserting a game

```python
db.execute(
    """INSERT OR IGNORE INTO games
       (appid, name, platform, platform_id, platform_slug, date_added,
        completion_status, installed,
        art_fetched, meta_fetched, cheevos_fetched,
        protondb_fetched, hltb_fetched)
       VALUES (?, ?, ?, ?, ?, ?,
               'Never Played', 0,
               '0', '0', '0', '0', '0')""",
    (next_appid, name, 'myplugin', platform_native_id, slug, date_added_unix_ts),
)
```

Key columns:

| Column | Notes |
|--------|-------|
| `appid` | Negative integer, allocated via `_next_negative_appid` |
| `platform` | String matching your `plugin.json` `platform` field |
| `platform_id` | The service's own identifier for the game (used for launch/sync) |
| `platform_slug` | URL slug for building store links (optional) |
| `date_added` | Unix timestamp (INTEGER) |
| `completion_status` | Start with `'Never Played'` |
| `installed` | `0` or `1` |
| `art_fetched` / `meta_fetched` / `cheevos_fetched` | `'0'` until fetched; use `'YYYY-MM-DD'` once done |

### Skipping blacklisted games

Before inserting, check `platform_id` for games the user previously removed:

```python
blacklisted = {
    row[0]
    for row in db.execute(
        "SELECT platform_id FROM blacklist WHERE platform_id IS NOT NULL"
    ).fetchall()
}

if str(platform_native_id) in blacklisted:
    continue
```

### Updating game data

```python
from database import update_game_data
update_game_data(appid, installed=1, install_path='/games/MyGame')
```

`update_game_data` accepts any column name as a keyword argument.

## Optional: install watcher

If your platform installs games to a known directory, watch it with `watchdog` and sync install status on change. Use `runners.watcher.PluginInstallWatcher` — it encapsulates the Observer lifecycle and only requires a name and a sync callback:

```python
from runners.watcher import PluginInstallWatcher

def sync_install_status():
    # reset installed=0 for your platform, then set installed=1 for found games
    ...

_watcher = PluginInstallWatcher('myplugin', sync_install_status)

def start_watcher(watch_path):
    _watcher.start(watch_path)   # no-op if already running

def stop_watcher():
    _watcher.stop()
```

If `watch_path` doesn't exist yet when `start()` is called (e.g. a fresh prefix with nothing installed), it retries every 30s until the path appears, then attaches for good — you don't need to handle that case yourself or re-call `start()` later.

The sync callback pattern:

1. Reset all `installed` flags for your platform to `0`.
2. Walk the install directory and set `installed = 1` for found games.

## Shared runners

Reusable helpers in `runners/` that plugins should use rather than rolling their own:

### `runners/oauth2.py` — Generic OAuth2

For plugins that authenticate via OAuth2 authorization code + refresh token flow.

```python
from runners.oauth2 import exchange_authorization_code, get_valid_session

# Exchange code for tokens (returns raw token dict; raises ValueError on failure)
token_data = exchange_authorization_code(
    token_url, client_id, client_secret, code,
    redirect_uri=None,     # include if the provider requires it
    use_basic_auth=False,  # True for providers that use HTTP Basic auth (e.g. Epic)
)

# Get a requests.Session with a valid Bearer token (auto-refreshes; returns None if disconnected)
session = get_valid_session(
    'my_platform',         # key in config.json where tokens are stored
    token_url, client_id, client_secret,
    extra_headers=None,    # e.g. {'User-Agent': '...'}
    use_basic_auth=False,
)
```

Token storage convention: `config.json["my_platform"]` must contain `access_token`, `refresh_token`, `expires_at`. Any other keys (username, account_id, etc.) are preserved on refresh.

### `runners/watcher.py` — `PluginInstallWatcher`

See the install watcher section above.

### `runners/wine.py` — Wine helpers

```python
from runners.wine import find_wine_binary, list_prefixes, create_prefix, run_in_prefix, launch_protocol_url

# Open a Windows protocol URL (e.g. com.epicgames.launcher://...) inside a prefix
launch_protocol_url(prefix_path, url, wine_bin=None)
```

`launch_protocol_url()` and `run_in_prefix()` already handle Proton/umu-run routing, an already-running-session for the same prefix, and native-Wayland preference internally — plugins don't need to special-case any of that themselves. By default, when a session is already live they deliver into it with a plain `wine start`/`wine` call and never kill it. Pass `restart_session_if_running=True` only if your launcher is confirmed *not* to accept a deep link while running (Ubisoft Connect is the only one so far) — that ends the live session and cold-starts a fresh one.

If your plugin needs to know whether a real game (not just an idle launcher client) is currently running under its prefix before doing something disruptive (e.g. before ending/restarting a Wine session), use `runners.wine.list_prefix_processes(prefix_path)` — it returns `[(pid, argv0), ...]` for every process tied to that prefix, correctly matching both the bare prefix path and its Proton `<prefix>/pfx` subdirectory. Match `argv0` against your own game-install-path convention rather than an exclusion list of known launcher process names — an exclusion list breaks the moment an unrelated process (e.g. a container helper) also carries the prefix's `WINEPREFIX` env var.

## Checking for a plugin in templates

`has_plugin(id)` is available in every Jinja2 template for cases where fragment slots aren't enough:

```jinja2
{% if has_plugin('myplugin') %}
  <!-- platform-specific UI -->
{% endif %}
```

## Checklist for a new plugin

- [ ] `plugins/myplugin/` directory with `__init__.py`, `plugin.json`, `routes.py`
- [ ] Unique `id` and `platform` string in `plugin.json` and plugin class
- [ ] `source` set to `github:owner/repo` in `plugin.json` if the plugin is hosted on GitHub
- [ ] `label` set on plugin class (display name used in `window._PLAT_LABELS`)
- [ ] `template_folder='templates'` on the Blueprint if using fragments
- [ ] `static_folder='static'` + `static_url_path='/plugins/<id>/static'` if serving static assets
- [ ] `js_api()` implemented if the plugin needs uninstall, scrape, or store-link support in core UI
- [ ] `manage_ui()` implemented if the plugin needs auth/sync controls (avoids writing modal HTML)
- [ ] Negative appids allocated with `_next_negative_appid`
- [ ] `platform` column set to your plugin id on every inserted row
- [ ] `platform_id` stored for each game (needed for sync deduplication and blacklist)
- [ ] `register(app)` registers the Blueprint
- [ ] `on_startup` / `on_shutdown` manage any background threads
- [ ] `on_uninstall()` clears credentials/tokens
- [ ] `launch_game(appid)` implemented so the Play button works (returns a status dict); use `install_poller` key (not platform-named flags) when installation is triggered
- [ ] `rescrape(appid)` implemented if the platform has a metadata API (enables bulk rescrape)
- [ ] `fetch_description(appid, platform_id)` implemented if the platform has a description API
- [ ] `extra_info(appid, platform, platform_id)` implemented if the plugin has supplemental info to show in the library detail pane (any platform, not just your own)
- [ ] `context_menu_items` added to `js_api()` if the plugin adds right-click menu actions for its games
- [ ] `on_game_launched(appid, platform)` / `on_library_updated()` implemented if the plugin needs to react to launches or library refreshes
- [ ] `home_widgets()` + a matching `home_widget_<id>` fragment implemented if the plugin adds a Home page shelf widget
- [ ] `date_import_url` declared if the platform has an orders page the Tampermonkey script should open
- [ ] `launcher_status()` implemented if `plugin.json` sets `launcher.required: true`
- [ ] Blacklist check before inserting games
- [ ] Fragment template filenames prefixed with plugin id to avoid collisions
