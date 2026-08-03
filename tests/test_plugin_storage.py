"""Plugin storage-split logic (plugins._migrate_legacy_plugin_dirs,
_plugin_was_configured, _plugin_on_disk, OFFICIAL_PLUGINS) -- pure
filesystem and dict logic, no Flask app, DB, or network involved."""
import config
import plugins


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


class TestOfficialPluginsRegistry:
    def test_every_entry_has_required_fields(self):
        for entry in plugins.OFFICIAL_PLUGINS:
            assert entry.get('id')
            assert entry.get('name')
            assert entry.get('source')

    def test_ids_are_unique(self):
        ids = [e['id'] for e in plugins.OFFICIAL_PLUGINS]
        assert len(ids) == len(set(ids))

    def test_sources_are_owner_slash_repo(self):
        for entry in plugins.OFFICIAL_PLUGINS:
            assert entry['source'].count('/') == 1
            owner, repo = entry['source'].split('/')
            assert owner and repo
