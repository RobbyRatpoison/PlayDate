import importlib
import json
import logging
import os
import re

log = logging.getLogger(__name__)

_plugins: dict = {}
_fragment_map: dict = {}
_fragment_abs: dict = {}   # slot -> list of absolute file paths (for JS slots)
_plugin_paths: dict = {}
_plugin_manifests: dict = {}


def load_all(app):
    """Discover and register all plugins found in this directory."""
    plugins_dir = os.path.dirname(os.path.abspath(__file__))
    if not os.path.isdir(plugins_dir):
        return
    for entry in sorted(os.listdir(plugins_dir)):
        plugin_path    = os.path.join(plugins_dir, entry)
        manifest_path  = os.path.join(plugin_path, 'plugin.json')
        if not os.path.isdir(plugin_path) or not os.path.exists(manifest_path):
            continue
        try:
            with open(manifest_path) as f:
                manifest = json.load(f)
            mod    = importlib.import_module(f'plugins.{entry}')
            p      = mod.plugin
            p.register(app)
            _plugins[p.id]          = p
            _plugin_paths[p.id]     = plugin_path
            _plugin_manifests[p.id] = manifest
            if hasattr(p, 'fragments'):
                tpl_dir = os.path.join(plugin_path, 'templates')
                for slot, tpl in p.fragments().items():
                    _fragment_map.setdefault(slot, []).append(tpl)
                    abs_path = os.path.join(tpl_dir, tpl)
                    _fragment_abs.setdefault(slot, []).append(abs_path)
            log.info(f"Loaded plugin: {manifest.get('name', entry)} v{manifest.get('version', '?')}")
        except Exception as e:
            log.error(f"Plugin load failed: {entry} — {e}", exc_info=True)


def get(plugin_id: str):
    return _plugins.get(plugin_id)


def loaded() -> dict:
    return dict(_plugins)


def has(plugin_id: str) -> bool:
    return plugin_id in _plugins


def fragments(slot: str) -> list:
    return _fragment_map.get(slot, [])


def fragment_js(slot: str) -> str:
    """Return combined JS content for a slot, stripping any <script> wrappers.

    Plugins that mistakenly wrap their tools_scripts content in <script> tags
    still work; a warning is logged so the author can fix it.
    """
    parts = []
    for path in _fragment_abs.get(slot, []):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
            if re.search(r'<script[\s>]', content, re.IGNORECASE):
                plugin_name = os.path.basename(os.path.dirname(os.path.dirname(path)))
                log.warning(
                    f"Plugin '{plugin_name}': {os.path.basename(path)} contains <script> tags "
                    f"but is included inside an existing script block — tags stripped automatically. "
                    f"Remove <script>/<\/script> from the template to silence this warning."
                )
                content = re.sub(r'</?script[^>]*>', '', content, flags=re.IGNORECASE)
            parts.append(content)
        except Exception as e:
            log.error(f"fragment_js: could not read {path}: {e}")
    return '\n'.join(parts)


# Platforms without a plugin yet; overridden if a plugin claims the same key.
_CORE_PLATFORM_LABELS = {
    'steam':       'Steam',
    'epic_games':  'Epic Games',
    'ea_app':      'EA App',
    'ubisoft':     'Ubisoft',
}


def plugin_path(plugin_id: str) -> str | None:
    return _plugin_paths.get(plugin_id)


def plugin_manifest(plugin_id: str) -> dict:
    return _plugin_manifests.get(plugin_id, {})


def plugin_js_api() -> dict:
    """Return JS API descriptors for all plugins that provide them."""
    return {p.platform: p.js_api() for p in _plugins.values() if hasattr(p, 'js_api')}


def platform_labels() -> dict:
    """Return display labels for all known platforms (core + plugins)."""
    labels = dict(_CORE_PLATFORM_LABELS)
    for p in _plugins.values():
        labels[p.platform] = getattr(p, 'label', p.name)
    return labels


def get_platform_priority() -> list:
    """Return the full duplicate-detection priority list.

    Merges the user's saved order with the hardcoded default, then appends
    any registered plugin platforms not already present. This ensures:
    - User's custom ordering is respected
    - Newly installed plugins are included at lowest priority automatically
    """
    from database import PLATFORM_PRIORITY_DEFAULT
    try:
        from config import load_state
        saved = load_state().get('platform_priority') or []
    except Exception:
        saved = []
    base   = saved + [p for p in PLATFORM_PRIORITY_DEFAULT if p not in saved]
    result = list(base)
    for p in _plugins.values():
        if p.platform not in result:
            result.append(p.platform)
    return result
