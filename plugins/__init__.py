import importlib
import json
import logging
import os

log = logging.getLogger(__name__)

_plugins: dict = {}
_fragment_map: dict = {}
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
                for slot, tpl in p.fragments().items():
                    _fragment_map.setdefault(slot, []).append(tpl)
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
