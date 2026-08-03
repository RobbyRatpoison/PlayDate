"""Plugin storage-split logic (plugins._migrate_legacy_plugin_dirs,
_plugin_was_configured, _plugin_on_disk, OFFICIAL_PLUGINS, BETA_PLUGINS,
_current_platform_key) -- pure filesystem and dict logic, no Flask app, DB,
or network involved."""
import sys

import pytest

import config
import plugins

_VALID_STATUSES = {'working', 'untested', 'broken'}
_VALID_PLATFORM_KEYS = {'windows', 'linux', 'mac'}


def _make_plugin_dir(base, plugin_id, extra_files=None):
    d = base / plugin_id
    d.mkdir()
    (d / 'plugin.json').write_text('{"id": "%s"}' % plugin_id)
    for name, content in (extra_files or {}).items():
        (d / name).write_text(content)
    return d


class TestMigrateLegacyPluginDirs:
    def test_moves_plugin_dir_with_manifest(self, tmp_path):
        bundled = tmp_path / 'bundled'; bundled.mkdir()
        user = tmp_path / 'user'; user.mkdir()
        _make_plugin_dir(bundled, 'ea_app')

        plugins._migrate_legacy_plugin_dirs(bundled, user)

        assert not (bundled / 'ea_app').exists()
        assert (user / 'ea_app' / 'plugin.json').exists()

    def test_skips_directories_without_a_manifest(self, tmp_path):
        bundled = tmp_path / 'bundled'; bundled.mkdir()
        user = tmp_path / 'user'; user.mkdir()
        (bundled / '__pycache__').mkdir()

        plugins._migrate_legacy_plugin_dirs(bundled, user)

        assert (bundled / '__pycache__').exists()
        assert not (user / '__pycache__').exists()

    def test_leaves_top_level_files_alone(self, tmp_path):
        # plugins/__init__.py itself sits directly in the bundled dir --
        # migration must only ever touch subdirectories.
        bundled = tmp_path / 'bundled'; bundled.mkdir()
        user = tmp_path / 'user'; user.mkdir()
        (bundled / '__init__.py').write_text('# real package file')

        plugins._migrate_legacy_plugin_dirs(bundled, user)

        assert (bundled / '__init__.py').exists()

    def test_does_not_overwrite_an_existing_destination(self, tmp_path):
        bundled = tmp_path / 'bundled'; bundled.mkdir()
        user = tmp_path / 'user'; user.mkdir()
        _make_plugin_dir(bundled, 'gog', {'marker.txt': 'old'})
        _make_plugin_dir(user, 'gog', {'marker.txt': 'new'})

        plugins._migrate_legacy_plugin_dirs(bundled, user)

        # Left in place with a warning, not clobbered and not deleted.
        assert (bundled / 'gog').exists()
        assert (user / 'gog' / 'marker.txt').read_text() == 'new'

    def test_noop_when_bundled_and_user_dir_are_the_same_path(self, tmp_path):
        # Source checkouts: BASE_DIR is the project root, so the writable
        # dir and the bundled dir resolve to the exact same physical
        # directory. Must not try to move a plugin dir into itself.
        same = tmp_path / 'plugins'; same.mkdir()
        _make_plugin_dir(same, 'itch_io')

        plugins._migrate_legacy_plugin_dirs(same, same)

        assert (same / 'itch_io' / 'plugin.json').exists()

    def test_missing_bundled_dir_does_not_raise(self, tmp_path):
        user = tmp_path / 'user'; user.mkdir()
        plugins._migrate_legacy_plugin_dirs(tmp_path / 'does_not_exist', user)


class TestPluginWasConfigured:
    def test_true_when_auth_token_saved(self, monkeypatch):
        monkeypatch.setattr(config, 'load_config', lambda: {'gog': {'access_token': 'x'}})
        assert plugins._plugin_was_configured('gog') is True

    def test_true_when_launcher_config_saved(self, monkeypatch):
        monkeypatch.setattr(config, 'load_config',
                             lambda: {'launchers': {'ea_app': {'wine_bin': '/usr/bin/wine'}}})
        assert plugins._plugin_was_configured('ea_app') is True

    def test_false_when_neither_present(self, monkeypatch):
        monkeypatch.setattr(config, 'load_config', lambda: {'some_other_plugin': {'x': 1}})
        assert plugins._plugin_was_configured('ea_app') is False

    def test_false_when_config_missing_entirely(self, monkeypatch):
        monkeypatch.setattr(config, 'load_config', lambda: None)
        assert plugins._plugin_was_configured('ea_app') is False

    def test_empty_saved_value_does_not_count_as_configured(self, monkeypatch):
        # e.g. a key left over from a partially-completed disconnect
        monkeypatch.setattr(config, 'load_config', lambda: {'ea_app': {}})
        assert plugins._plugin_was_configured('ea_app') is False

    def test_cleared_after_uninstall_shape(self, monkeypatch):
        # Mirrors what on_uninstall()/the uninstall route actually leave
        # behind: both keys popped entirely, not just emptied.
        monkeypatch.setattr(config, 'load_config', lambda: {'launchers': {}})
        assert plugins._plugin_was_configured('ea_app') is False


class TestPluginOnDisk:
    def test_true_when_present_in_writable_dir(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path))
        writable = tmp_path / 'plugins'; writable.mkdir()
        _make_plugin_dir(writable, 'zzz_test_writable_only')

        assert plugins._plugin_on_disk('zzz_test_writable_only') is True

    def test_false_when_absent_everywhere(self, tmp_path, monkeypatch):
        monkeypatch.setattr(config, 'BASE_DIR', str(tmp_path))
        assert plugins._plugin_on_disk('zzz_test_definitely_not_a_real_plugin') is False


@pytest.mark.parametrize("registry_name", ["OFFICIAL_PLUGINS", "BETA_PLUGINS"])
class TestPluginRegistries:
    def test_every_entry_has_required_fields(self, registry_name):
        for entry in getattr(plugins, registry_name):
            assert entry.get('id')
            assert entry.get('name')
            assert entry.get('source')

    def test_ids_are_unique(self, registry_name):
        ids = [e['id'] for e in getattr(plugins, registry_name)]
        assert len(ids) == len(set(ids))

    def test_sources_are_owner_slash_repo(self, registry_name):
        for entry in getattr(plugins, registry_name):
            assert entry['source'].count('/') == 1
            owner, repo = entry['source'].split('/')
            assert owner and repo

    def test_platform_status_covers_all_three_platforms_with_valid_values(self, registry_name):
        for entry in getattr(plugins, registry_name):
            status = entry.get('platform_status')
            assert status, f"{entry['id']} has no platform_status"
            assert set(status.keys()) == _VALID_PLATFORM_KEYS
            for value in status.values():
                assert value in _VALID_STATUSES


class TestPluginRegistriesDontOverlap:
    def test_no_id_appears_in_both_registries(self):
        official_ids = {e['id'] for e in plugins.OFFICIAL_PLUGINS}
        beta_ids = {e['id'] for e in plugins.BETA_PLUGINS}
        assert not (official_ids & beta_ids)


class TestCurrentPlatformKey:
    def test_windows(self, monkeypatch):
        monkeypatch.setattr(sys, 'platform', 'win32')
        assert plugins._current_platform_key() == 'windows'

    def test_mac(self, monkeypatch):
        monkeypatch.setattr(sys, 'platform', 'darwin')
        assert plugins._current_platform_key() == 'mac'

    def test_linux(self, monkeypatch):
        monkeypatch.setattr(sys, 'platform', 'linux')
        assert plugins._current_platform_key() == 'linux'

    def test_unknown_platform_falls_back_to_linux(self, monkeypatch):
        # e.g. one of the BSDs -- better to assume the more Linux-like
        # behavior than to crash on an unrecognized sys.platform value.
        monkeypatch.setattr(sys, 'platform', 'freebsd13')
        assert plugins._current_platform_key() == 'linux'
