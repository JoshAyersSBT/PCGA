"""v0.19.9 native Downloads UX and provider-queue progress contract."""
from pathlib import Path
import importlib.machinery
import importlib.util
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
COMP = ROOT / 'components'
source = (COMP/'pcga-status-server.py').read_text()
HTML = source.split("INDEX_HTML = r'''",1)[1].split("\n'''",1)[0]

loader=importlib.machinery.SourceFileLoader('pcga_store_jobs_download_center',str(COMP/'pcga-store-jobs'))
spec=importlib.util.spec_from_loader(loader.name,loader)
worker=importlib.util.module_from_spec(spec)
sys.modules[spec.name]=worker
loader.exec_module(worker)

class DownloadCenterTests(unittest.TestCase):
    def test_read_only_queue_position_and_eta(self):
        with tempfile.TemporaryDirectory() as t:
            state=Path(t)/'state'; logs=Path(t)/'logs'
            with mock.patch.object(worker,'STATE_ROOT',state),mock.patch.object(worker,'DB_PATH',state/'jobs.sqlite3'),mock.patch.object(worker,'LOG_ROOT',logs):
                worker.init_db()
                a=worker.enqueue('epic','install','epic-one','First Epic')['job']['id']
                b=worker.enqueue('gog','install','gog-one','First GOG')['job']['id']
                c=worker.enqueue('epic','install','epic-two','Second Epic')['job']['id']
                db=worker.connect()
                db.execute("UPDATE jobs SET state='running',bytes_done=200,bytes_total=1000,speed_bps=100,progress=20 WHERE id=?",(a,))
                db.close()
                result=worker.list_jobs(limit=2)
                self.assertEqual(len(result['jobs']),2)
                by_id={j['id']:j for j in result['jobs']}
                self.assertEqual(by_id[c]['queue_position'],1)
                self.assertEqual(by_id[b]['queue_position'],1)
                self.assertEqual(result['counts']['running'],1)
                full={j['id']:j for j in worker.list_jobs(limit=100)['jobs']}
                self.assertEqual(full[a]['eta_seconds'],8)
                self.assertIsNone(full[a]['queue_position'])
                self.assertIsNone(full[b]['eta_seconds'])
                self.assertEqual(full[c]['provider'],'epic')
                self.assertFalse(any('log_path' in j for j in full.values()))

    def test_download_markup_and_reentrant_navigation(self):
        for text in ('data-store-job-filter="active"','data-store-job-filter="completed"',
                     'data-store-job-filter="attention"','id="store-jobs-search"',
                     'data-store-jobs-library','data-store-job-open','queue_position',
                     'aria-valuenow','store-job-progress.indeterminate','data-store-game-controls'):
            self.assertIn(text,HTML)
        self.assertIn("'store-install-modal','store-jobs-modal'",HTML)
        self.assertIn('focus({preventScroll:true})',HTML)
        self.assertIn('if(storeJobsRenderedHtml!==html)',HTML)
        self.assertIn('storeJobsRequestBusy',HTML)
        self.assertIn('Amazon game installation is not available yet',HTML)
        self.assertIn('Download and organize in PCGA',HTML)

    def test_real_javascript_filters_and_missing_progress(self):
        js=HTML.rsplit('<script>',1)[1].split('</script>',1)[0]
        part=js[js.index("let storeJobsView='all';"):js.index('async function storeAccountConnect(provider){')]
        fixture=r"""
        const vm=require('node:vm');const assert=require('node:assert/strict');
        class Element {constructor(){this.innerHTML='';this.textContent='';this.scrollTop=0;this.dataset={};this.attributes={};this.classList={toggle:()=>{}};}querySelectorAll(){return [];}setAttribute(k,v){this.attributes[k]=v;}}
        const list=new Element(),summary=new Element(),sub=new Element();
        const nodes={'store-jobs-list':list,'store-jobs-summary':summary,'store-jobs-sub':sub};
        const document={activeElement:null,getElementById:id=>nodes[id],querySelectorAll:sel=>sel==='[data-store-job-filter]'?[]:[]};
        const context=vm.createContext({document,console,Math,Number,String,Set,Date,setTimeout,clearTimeout,
          humanBytes:n=>n+' B',esc:s=>String(s).replaceAll('<','&lt;'),storeInstallJobs:[],storeLibraryItems:[]});
        vm.runInContext(SOURCE,context);
        const data={jobs:[
          {id:'one',provider:'epic',title:'Massive & Epic',state:'running',progress:null,bytes_done:null,bytes_total:null,log_tail:''},
          {id:'two',provider:'gog',title:'Example',state:'queued',progress:null,queue_position:2,log_tail:''},
          {id:'three',provider:'gog',title:'Baldur',state:'failed',message:'offline',log_tail:''}
        ],counts:{running:1,queued:1,failed:1}};
        vm.runInContext('renderStoreJobs',context)(data);
        assert.match(list.innerHTML,/Install…/);assert.doesNotMatch(list.innerHTML,/0% downloading/);
        assert.match(list.innerHTML,/#2 in GOG queue/);
        vm.runInContext("storeJobsView='active'",context);
        vm.runInContext('renderStoreJobs',context)(data);
        assert.doesNotMatch(list.innerHTML,/Baldur/);
        vm.runInContext("storeJobsView='attention';storeJobsSearch='bald'",context);
        vm.runInContext('renderStoreJobs',context)(data);
        assert.match(list.innerHTML,/Baldur/);assert.doesNotMatch(list.innerHTML,/Example/);
        console.log('Download filters, queue ordering and unknown progress: PASS');
        """
        fixture=fixture.replace('SOURCE',repr(part))
        p=subprocess.run(['node','-e',fixture],capture_output=True,text=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stdout+'\n'+p.stderr)
        self.assertIn('PASS',p.stdout)

    def test_actual_browser_js_parses(self):
        js=HTML.rsplit('<script>',1)[1].split('</script>',1)[0]
        p=subprocess.run(['node','--check','-'],input=js,text=True,capture_output=True,timeout=15)
        self.assertEqual(p.returncode,0,p.stderr)

if __name__=='__main__': unittest.main()
