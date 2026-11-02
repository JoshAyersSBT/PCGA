"""A collected systemd unit is not evidence that an update completed."""
import ast
import copy
from pathlib import Path
import re
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

BASE = Path(__file__).resolve().parents[1]
SOURCE = (BASE / 'components/pcga-control').read_text(encoding='utf-8')
NODE = next(node for node in ast.parse(SOURCE).body
            if isinstance(node, ast.FunctionDef) and node.name == 'patch_status')
CODE = compile(ast.Module(body=[NODE], type_ignores=[]), 'pcga-control:patch_status', 'exec')
JOB = '20261023-192429-4735c327'


class PatchStatus1938(unittest.TestCase):
    def status(self, *, state='running', exit_text=None, properties='', log='', journal=''):
        metadata = {'id': JOB, 'state': state, 'unit': 'pcga-patch-' + JOB,
                    'exit_file': '/patch.exit', 'log': '/patch.log'}
        class File:
            def __init__(self, path): self.path = path
            def __truediv__(self, part): return File(str(self.path) + '/' + part)
            def is_file(self): return self.path == '/patch.exit' and exit_text is not None
            def read_text(self, **kwargs):
                if self.path == '/patch.exit' and exit_text is not None: return exit_text
                if self.path == '/patch.log': return log
                raise FileNotFoundError(self.path)
        runner = Mock(side_effect=lambda args, **kw: SimpleNamespace(
            returncode=0, stderr='', stdout=journal if args[0] == 'journalctl' else properties))
        namespace = {'re': re, 'Path': File, 'PATCH_ROOT': File('/patches'),
                     'load_json': lambda path: copy.deepcopy(metadata), 'atomic_json': Mock(),
                     'run': runner, '_redact_log_text': lambda text: text.replace('SECRET', '[REDACTED]')}
        exec(CODE, namespace)
        return namespace['patch_status'](JOB), runner

    def test_start_failure_cannot_turn_into_complete_after_systemd_collects_unit(self):
        result, _ = self.status(state='failed-to-start', properties='ActiveState=inactive\nResult=success\nExecMainStatus=0\n')
        self.assertEqual(result['state'], 'failed')
        self.assertIsNone(result['exit_code'])

    def test_missing_completion_record_is_failure_even_with_systemd_zero(self):
        result, _ = self.status(properties='LoadState=not-found\nActiveState=inactive\nResult=success\nExecMainStatus=0\n')
        self.assertEqual(result['state'], 'failed')
        self.assertIn('completion record', result['detail'])

    def test_running_update_is_allowed_to_wait_for_its_completion_file(self):
        result, _ = self.status(properties='LoadState=loaded\nActiveState=active\nSubState=running\n')
        self.assertEqual(result['state'], 'running')

    def test_durable_zero_exit_is_success_after_unit_disappears(self):
        result, runner = self.status(exit_text='0\n', log='Upgrade checks passed')
        self.assertEqual(result['state'], 'complete')
        self.assertEqual(result['exit_code'], 0)
        runner.assert_not_called()

    def test_runner_failure_preserves_exit_code_and_reads_redacted_journal(self):
        result, _ = self.status(exit_text='20\n', journal='Start failed: SECRET')
        self.assertEqual(result['state'], 'failed')
        self.assertEqual(result['exit_code'], 20)
        self.assertEqual(result['log_tail'], 'Start failed: [REDACTED]')

    def test_corrupt_exit_record_does_not_report_success(self):
        result, _ = self.status(exit_text='not an exit code')
        self.assertEqual(result['state'], 'failed')


if __name__ == '__main__':
    unittest.main()
