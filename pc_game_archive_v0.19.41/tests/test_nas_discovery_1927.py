"""NAS discovery is read-only, subnet-bounded, and only acts on a deliberate scan."""
from __future__ import annotations
import importlib.machinery
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

PATH=Path(__file__).resolve().parents[1]/'components/pcga-nas-discover'
loader=importlib.machinery.SourceFileLoader('pcga_nas_discovery_1927',str(PATH))
spec=importlib.util.spec_from_loader(loader.name, loader)
mod=importlib.util.module_from_spec(spec)
loader.exec_module(mod)

class NASDiscoveryTests(unittest.TestCase):
    def setUp(self):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        patch=mock.patch.object(mod,'STATE',Path(temp.name)/'state.json');patch.start();self.addCleanup(patch.stop)
        self.ifaces=[{'ifname':'enp3s0','operstate':'UP','addr_info':[{'family':'inet','local':'192.168.4.26','prefixlen':20}]},
                     {'ifname':'docker0','operstate':'UP','addr_info':[{'family':'inet','local':'172.17.0.1','prefixlen':16}]}]
    def test_primary_lan_and_max_24(self):
        result=mod.lan_networks([{'dst':'default','dev':'enp3s0'}],self.ifaces)
        self.assertEqual(len(result),1)
        self.assertEqual(result[0]['cidr'],'192.168.4.0/24')
        self.assertEqual(len(result[0]['addresses']),253)
        self.assertNotIn('192.168.4.26',result[0]['addresses'])
        self.assertNotIn('172.17.0.1',result[0]['addresses'])
    def test_narrow_lan_and_no_public_or_overlay(self):
        cases=self.ifaces+[{'ifname':'eth9','operstate':'UP','addr_info':[{'family':'inet','local':'8.8.8.8','prefixlen':24}]},
                           {'ifname':'tailscale0','operstate':'UP','addr_info':[{'family':'inet','local':'100.100.10.1','prefixlen':24}]}]
        r=mod.lan_networks([{'dst':'default','dev':'eth9'}],cases)
        self.assertEqual(r[0]['cidr'],'192.168.4.0/24')
    def test_no_eligible_network_fails_closed(self):
        self.assertEqual(mod.lan_networks([], [{'ifname':'docker0','addr_info':[{'family':'inet','local':'172.17.0.1','prefixlen':16}]}]),[])
    def test_idle_status_no_network_access(self):
        self.assertEqual(mod.status()['state'],'idle')
        with mock.patch.object(mod,'socket') as sock:
            mod.status()
            sock.create_connection.assert_not_called()
    def test_finds_smb_and_nfs_without_mutating_remote(self):
        network={'interface':'enp3s0','cidr':'192.168.4.0/30','addresses':['192.168.4.1','192.168.4.2']}
        with mock.patch.object(mod,'discover_targets',return_value=[network]),\
             mock.patch.object(mod,'check_host',side_effect=lambda ip:(ip,['smb','nfs'] if ip.endswith('.1') else [])),\
             mock.patch.object(mod,'smb_shares',return_value=(['Media'],'')) as smb,\
             mock.patch.object(mod,'nfs_exports',return_value=(['/exports/backups'],'')) as nfs:
            outcome=mod.scan()
        self.assertEqual(outcome['state'],'complete')
        self.assertEqual(len(outcome['devices']),2)
        self.assertFalse(any(dev['verified_access'] for dev in outcome['devices']))
        self.assertEqual(outcome['devices'][0]['shares'],['Media'])
        self.assertEqual(outcome['devices'][1]['shares'],['/exports/backups'])
        smb.assert_called_once_with('192.168.4.1');nfs.assert_called_once_with('192.168.4.1')
        self.assertEqual(mod.status()['state'],'complete')
    def test_no_routes_cannot_scan_broadly(self):
        with mock.patch.object(mod,'discover_targets',return_value=[]),mock.patch.object(mod,'check_host') as check:
            result=mod.scan()
        self.assertEqual(result['state'],'failed')
        check.assert_not_called()
    def test_timeout_state(self):
        mod.write_state({'state':'running','started_at':1,'devices':[],'networks':[]})
        self.assertEqual(mod.status()['state'],'failed')
    def test_no_anonymous_shares_not_misrepresented(self):
        with mock.patch.object(mod.shutil,'which',return_value=None):
            shares,why=mod.smb_shares('192.168.4.1')
        self.assertEqual(shares,[])
        self.assertIn('manually',why)
    def test_source_integration(self):
        root=PATH.parents[1]
        control=(root/'components/pcga-control').read_text()
        portal=(root/'components/pcga-status-server.py').read_text()
        upgrade=next(root.glob('upgrade_to_v0.19.*.sh')).read_text()
        self.assertIn('"nas-discover-start"',control)
        self.assertIn('"nas-discover-status"',control)
        self.assertIn('cc-nas-discovery-results',portal)
        self.assertIn('useNasDiscovered(',portal)
        self.assertIn('install -m 0755 "$COMP/pcga-nas-discover"',upgrade)

if __name__=='__main__': unittest.main()
