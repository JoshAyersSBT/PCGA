"""Real app settings and loss of Wolf's nonpersistent comment markers."""
import ast
from collections import Counter
import contextlib
import copy
import json
from pathlib import Path
import re
import sys
import tempfile
import shutil
import uuid
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'components'))
import pcga_wolf_config as config

SID = 'fa3059a2-0635-44aa-b381-15629dfc51f9'
FIXTURE = json.loads((ROOT / 'tests/fixtures/wolf-apps-1939.json').read_text())


@contextlib.contextmanager
def test_directory():
    base = Path(tempfile.gettempdir()).resolve()
    folder = base / ('pcga-test-' + uuid.uuid4().hex)
    folder.mkdir(mode=0o755)
    try:
        yield str(folder)
    finally:
        assert folder.resolve().parent == base
        shutil.rmtree(folder)


def value(item):
    if isinstance(item, dict):
        return '{' + ', '.join(json.dumps(k) + '=' + value(v) for k, v in item.items()) + '}'
    if isinstance(item, list):
        return '[' + ', '.join(value(v) for v in item) + ']'
    return json.dumps(item, ensure_ascii=False)


def block(apps):
    return '\n'.join('[[profiles.apps]]\n' + '\n'.join(k + '=' + value(v) for k, v in app.items()) for app in apps) + '\n'


def document(apps, *, other=True):
    source = 'config_version=4\n[[profiles]]\nid="moonlight-profile-id"\n' + block(apps)
    if other:
        source += '\n[[profiles]]\nid="user"\n' + block([{'title': 'User launcher', 'runner': {'type': 'process', 'run_cmd': 'echo preserved'}}])
    return source + '\n[gstreamer]\nsecret_setting="preserved"\n'


def function(name):
    source = (ROOT / 'components/pcga-game-orchestrator').read_text()
    node = next(n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == name)
    return compile(ast.Module(body=[node], type_ignores=[]), name, 'exec')


class WolfCatalog1939(unittest.TestCase):
    def setUp(self):
        self.apps = copy.deepcopy(FIXTURE['jedi'])
        self.heroic = copy.deepcopy(FIXTURE['heroic'])

    def test_actual_serialized_game_entries_need_no_comments_or_reload(self):
        original = document(self.apps + [self.heroic])
        desired = '# BEGIN PCGA MANAGED APP ' + SID + '\n' + block(self.apps)
        self.assertEqual(config.reconcile_apps(original, desired, SID), original)

    def test_json_whitespace_and_key_order_are_not_changes(self):
        changed = copy.deepcopy(self.apps)
        for app in changed:
            app['runner']['base_create_json'] = json.dumps(json.loads(app['runner']['base_create_json']), indent=4, sort_keys=True)
        self.assertTrue(config.apps_match(document(changed), block(self.apps), SID))

    def test_34_observed_heroic_duplicates_become_one_and_games_survive(self):
        source = document([self.heroic] * 34 + self.apps)
        result = config.reconcile_apps(source, block([self.heroic]), 'heroic')
        parsed = config.tomllib.loads(result)
        apps = config.profile(parsed)['apps']
        self.assertEqual(sum(config.owns(a, 'heroic') for a in apps), 1)
        self.assertEqual([a for a in apps if config.owns(a, SID)], self.apps)
        self.assertEqual(parsed['profiles'][1], config.tomllib.loads(source)['profiles'][1])
        self.assertEqual(parsed['gstreamer'], {'secret_setting': 'preserved'})
        self.assertEqual(config.reconcile_apps(result, block([self.heroic]), 'heroic'), result)

    def test_real_image_change_is_applied_once(self):
        desired = copy.deepcopy(self.apps)
        desired[0]['runner']['image'] = 'pcga/new-runtime'
        original = document(self.apps + [self.heroic])
        changed = config.reconcile_apps(original, block(desired), SID)
        self.assertNotEqual(changed, original)
        self.assertTrue(config.apps_match(changed, block(desired), SID))
        self.assertEqual(config.reconcile_apps(changed, block(desired), SID), changed)

    def test_runner_environment_difference_is_not_hidden(self):
        desired = copy.deepcopy(self.apps)
        desired[0]['runner']['env'].append('PCGA_NEW_SETTING=1')
        self.assertFalse(config.apps_match(document(self.apps), block(desired), SID))

    def test_foreign_app_with_same_title_is_preserved(self):
        custom = copy.deepcopy(self.apps[0])
        custom['runner']['env'] = ['CUSTOM_APP=1']
        result = config.reconcile_apps(document([custom]), block(self.apps), SID)
        self.assertIn(custom, config.profile(config.tomllib.loads(result))['apps'])

    def test_other_profile_apps_are_never_deduplicated(self):
        text = document(self.apps) + '\n[[profiles]]\nid="custom"\n' + block([self.heroic] * 2)
        result = config.reconcile_apps(text, block([self.heroic]), 'heroic')
        self.assertEqual(len(config.tomllib.loads(result)['profiles'][-1]['apps']), 2)

    def test_global_tables_after_last_profile_are_preserved(self):
        text = document(self.apps, other=False)
        result = config.reconcile_apps(text, block([self.heroic]), 'heroic')
        self.assertEqual(config.tomllib.loads(result)['gstreamer'], {'secret_setting': 'preserved'})

    def test_remove_owned_app_without_removing_adjacent_custom_settings(self):
        text = document([self.heroic] + self.apps)
        result = config.reconcile_apps(text, '', 'heroic')
        self.assertTrue(config.apps_match(result, block(self.apps), SID))
        self.assertFalse(any(config.owns(a, 'heroic') for a in config.profile(config.tomllib.loads(result))['apps']))

    def test_wrong_owner_is_rejected(self):
        with self.assertRaisesRegex(ValueError, 'do not belong'):
            config.reconcile_apps(document([]), block([self.heroic]), SID)

    def test_ambiguous_header_inside_multiline_string_fails_closed(self):
        text = document(self.apps).replace('id="moonlight-profile-id"', 'id="moonlight-profile-id"\nnote="""\n[[profiles.apps]]\n"""')
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            config.reconcile_apps(text, block([self.heroic]), 'heroic')

    def sync(self, *, quarantined=False, image_changed=False):
        with test_directory() as folder:
            path = Path(folder) / 'wolf.toml'
            path.write_text(document(self.apps))
            desired = copy.deepcopy(self.apps)
            if image_changed:
                desired[0]['runner']['image'] = 'new-image'
            state = {'status': 'ready', 'runtime_image': 'image', 'stream_state': 'failed' if quarantined else 'ready'}
            if quarantined:
                state.update(wolf_registration_quarantined_v01869=True, wolf_registration_quarantine_reason='managed-app-block-dropped-after-two-reloads')
            def update(sid, **kwargs):
                state.update(kwargs)
                return dict(state)
            namespace = dict(Path=Path, WOLF_CONFIG=path, state_update=update,
                             managed_app_block=lambda *a: block(desired),
                             wolf_internal_app_title=lambda *a: 'PCGA Game',
                             wolf_launch_variant_apps=lambda *a: [], _wolf_pending_load=lambda: set(),
                             _WOLF_CHANGED_SET_IDS=set(), _WOLF_CONFIG_DIRTY=False,
                             _wolf_request_reload=Mock(), re=re, os=__import__('os'), shutil=__import__('shutil'))
            exec(function('wolf_sync'), namespace)
            original = path.read_bytes()
            with patch.object(config, 'stack_lock', contextlib.nullcontext):
                result = namespace['wolf_sync'](SID, {'title': 'Jedi'}, state)
            return result, namespace['_wolf_request_reload'], original == path.read_bytes()

    def test_game_sync_does_not_write_or_queue_when_only_comments_are_missing(self):
        result, reload, same = self.sync()
        self.assertEqual(result['stream_state'], 'ready')
        self.assertTrue(same)
        reload.assert_not_called()

    def test_false_marker_quarantine_recovers_without_a_restart(self):
        result, reload, same = self.sync(quarantined=True)
        self.assertEqual(result['stream_state'], 'ready')
        self.assertFalse(result['wolf_registration_quarantined_v01869'])
        self.assertTrue(same)
        reload.assert_not_called()

    def test_different_quarantined_app_is_not_automatically_retried(self):
        result, reload, same = self.sync(quarantined=True, image_changed=True)
        self.assertEqual(result['stream_state'], 'failed')
        self.assertTrue(same)
        reload.assert_not_called()

    def test_real_game_change_queues_a_reload(self):
        result, reload, same = self.sync(image_changed=True)
        self.assertEqual(result['stream_state'], 'pending-restart')
        self.assertFalse(same)
        reload.assert_called_once_with(SID)

    def test_post_restart_serialization_does_not_trigger_a_second_restart(self):
        with test_directory() as folder:
            path = Path(folder) / 'wolf.toml'; path.write_text(document(self.apps))
            state = {'status': 'ready', 'runtime_image': 'image'}
            runner = Mock(side_effect=lambda args, **kw: SimpleNamespace(returncode=0, stdout='true' if args[:2] == ['docker', 'inspect'] else ''))
            namespace = dict(WOLF_CONFIG=path, _WOLF_CONFIG_DIRTY=True, _WOLF_CHANGED_SET_IDS={SID},
                             _wolf_pending_load=lambda: {SID}, _wolf_pending_save=Mock(),
                             _wolf_runtime_session_active=lambda: (False, ''), state_path=lambda sid: path,
                             state_update=Mock(), load_json=lambda p: state, SETS=Path(folder),
                             managed_app_block=lambda *a: block(self.apps), subprocess=SimpleNamespace(run=runner, DEVNULL=-3),
                             time=SimpleNamespace(sleep=lambda *a: None), log=Mock(), wolf_sync=Mock())
            exec(function('_wolf_reconcile_batched_restart'), namespace)
            with patch.object(config, 'stack_lock', contextlib.nullcontext):
                self.assertTrue(namespace['_wolf_reconcile_batched_restart']())
            self.assertEqual(sum(c.args[0][:2] == ['docker', 'restart'] for c in runner.call_args_list), 1)
            namespace['wolf_sync'].assert_not_called()

    def test_unreadable_session_state_blocks_restart(self):
        namespace = {'subprocess': SimpleNamespace(run=Mock(side_effect=TimeoutError('busy')))}
        exec(function('_wolf_runtime_session_active'), namespace)
        active, reason = namespace['_wolf_runtime_session_active']()
        self.assertTrue(active)
        self.assertIn('could not verify', reason)

    def heroic_sync(self, *, ready=True, defer=False):
        with test_directory() as folder:
            path = Path(folder) / 'wolf.toml'; path.write_text(document([self.heroic] * 34 + self.apps))
            queue = set()
            def applied():
                queue.clear()
                return True
            orchestrator = SimpleNamespace(_wolf_request_reload=Mock(side_effect=queue.add),
                _wolf_pending_load=lambda: set(queue), _wolf_reconcile_batched_restart=Mock(side_effect=applied))
            source = (ROOT / 'components/pcga-heroic-sync').read_text()
            nodes = [n for n in ast.parse(source).body if isinstance(n, ast.FunctionDef) and n.name == 'reconcile_wolf']
            namespace = dict(WOLF_CONFIG=path, run=Mock(return_value=SimpleNamespace(returncode=0 if ready else 1)),
                IMAGE='heroic', LAUNCHER_TITLE='PCGA Heroic Library', LAUNCHER_SID='heroic-library-manager',
                app_block=lambda *a: block([self.heroic]), BEGIN='# BEGIN PCGA HEROIC MANAGED APPS',
                END='# END PCGA HEROIC MANAGED APPS', STATE=Path(folder), shutil=shutil, os=__import__('os'))
            exec(compile(ast.Module(body=nodes, type_ignores=[]), 'heroic-sync', 'exec'), namespace)
            original = path.read_bytes()
            with patch.object(config, 'stack_lock', contextlib.nullcontext), patch.object(config, 'load_orchestrator', return_value=orchestrator):
                first = namespace['reconcile_wolf']([], Path(folder), defer_reload=defer)
                second = namespace['reconcile_wolf']([], Path(folder), defer_reload=defer)
            return first, second, orchestrator, original == path.read_bytes()

    def test_heroic_cleanup_shares_one_restart_then_is_idle(self):
        first, second, orchestrator, same = self.heroic_sync()
        self.assertTrue(first['changed'])
        self.assertTrue(first['restarted'])
        self.assertFalse(second['changed'])
        self.assertFalse(second['restarted'])
        self.assertFalse(same)
        orchestrator._wolf_reconcile_batched_restart.assert_called_once()

    def test_heroic_installer_can_batch_its_cleanup_with_games(self):
        first, second, orchestrator, same = self.heroic_sync(defer=True)
        self.assertTrue(first['pending'])
        self.assertFalse(first['restarted'])
        self.assertFalse(second['changed'])
        orchestrator._wolf_reconcile_batched_restart.assert_not_called()

    def test_unavailable_heroic_image_cannot_delete_apps(self):
        first, second, orchestrator, same = self.heroic_sync(ready=False)
        self.assertFalse(first['changed'])
        self.assertTrue(same)
        orchestrator._wolf_request_reload.assert_not_called()


if __name__ == '__main__':
    unittest.main()
