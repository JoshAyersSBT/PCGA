"""v0.19.8: independent store backend readiness and Connect UI regression."""
from pathlib import Path
import importlib.machinery
import types
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

def load_component(name):
    module=types.ModuleType(name.replace('-','_'))
    module.__file__=str(ROOT/'components'/name)
    exec(compile((ROOT/'components'/name).read_text(),module.__file__,'exec'),module.__dict__)
    return module


class StoreLoginReadinessTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.control=load_component('pcga-control')

    def test_lightweight_status_does_not_mutate(self):
        with patch.object(self.control,'store_provider_status',return_value={'ok':True,'prepared':False}) as status,patch.object(self.control,'_read_json_file',return_value={'state':'downloading','detail':'Preparing','updated_at':10}) as read:
            result=self.control.store_backends_readiness()
        self.assertFalse(result['prepared'])
        self.assertEqual(result['bootstrap']['state'],'downloading')
        status.assert_called_once_with(False)
        read.assert_called_once()

    def test_status_bounds_error_details(self):
        with patch.object(self.control,'store_provider_status',return_value={'ok':True,'prepared':False}),patch.object(self.control,'_read_json_file',return_value={'state':'error','detail':'x'*2000,'updated_at':12}):
            result=self.control.store_backends_readiness()
        self.assertEqual(len(result['bootstrap']['detail']),600)

    def test_login_is_not_disabled_solely_for_missing_backends(self):
        ui=(ROOT/'components/pcga-status-server.py').read_text()
        self.assertIn('connect.disabled=!!row.connected||storeLoginBusy',ui)
        self.assertIn("await storeBackendsReadyForLogin(provider,controller.signal)",ui)
        self.assertIn("store-backends-prepare",ui)
        self.assertIn('path == "/store/backends"',(ROOT/'components/pcga-control').read_text())

if __name__=='__main__':unittest.main()
