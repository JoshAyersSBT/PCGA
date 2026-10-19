"""v0.19.8: prove store auth modal escape/cancel/home and first-use preparation UX."""
from pathlib import Path
from html.parser import HTMLParser
import re, subprocess, unittest

ROOT = Path(__file__).resolve().parents[1]
HTML = (ROOT/'components/pcga-status-server.py').read_text().split("INDEX_HTML = r'''",1)[1].split("\n'''",1)[0]

class ParseIDs(HTMLParser):
    def __init__(self): super().__init__();self.ids=[]
    def handle_starttag(self,tag,attrs):
        self.ids += [v for (k,v) in attrs if k=='id']

class StoreLoginModalTests(unittest.TestCase):
    def test_controls_and_dialog_structure(self):
        ids=ParseIDs();ids.feed(HTML)
        self.assertEqual(len(ids.ids),len(set(ids.ids)))
        self.assertIn('role="dialog" aria-modal="true" aria-labelledby="store-auth-title"',HTML)
        for control in ('data-store-auth-close','data-store-auth-home','data-store-auth-submit','store-auth-progress','store-auth-error'):
            self.assertIn(control,HTML)
        self.assertIn('max-height:min(82dvh,780px)',HTML)
        self.assertIn('body[data-device-layout="mobile"] #store-auth-modal .store-auth-panel',HTML)
        self.assertIn("e.key==='BrowserBack'",HTML)
        self.assertIn("e.key==='Backspace'&&!pcgaTextEditingTarget(e.target)",HTML)

    def test_real_javascript_cancel_during_backend_preparation(self):
        js=HTML.rsplit('<script>',1)[1].split('</script>',1)[0]
        part=js[js.index("let storeAuthProvider='';"):js.index('async function fetchStoreJobs()')]
        part2=js[js.index('async function storeAccountConnect(provider){'):js.index('async function storeAccountLogout(provider)')]
        fixture=r'''
        const vm=require('node:vm');
        const assert=require('node:assert/strict');
        class Elem {constructor(){this.style={};this.dataset={};this.hidden=false;this.textContent='';this.value='';this.disabled=false;this.isConnected=true;this.active=false;this.classes=new Set();this.classList={add:(n)=>this.classes.add(n),remove:(n)=>this.classes.delete(n),contains:(n)=>this.classes.has(n)}}focus(){doc.activeElement=this;}removeAttribute(n){if(n==='href')this.href='';}querySelector(sel){return doc.querySelector(sel);}}
        const elements=new Map();const get=id=>{if(!elements.has(id))elements.set(id,new Elem());return elements.get(id);};
        const selectors={'[data-store-auth-submit]':get('submit'),'[data-store-auth-close]':get('back'),'[data-store-account-connect]':get('connect')};
        const doc={activeElement:get('connect'),getElementById:get,querySelector:s=>selectors[s]||get(s),querySelectorAll:()=>[]};
        let prepared=false,progressCalls=0,startCalls=0,showStatusCalls=0,closeSettingsCalls=0,loadCalls=0;
        const context=vm.createContext({document:doc,console,AbortController,DOMException,Date,setTimeout,clearTimeout,Promise,
          loadControlCenter:async()=>{loadCalls++;},closeSettings:()=>{closeSettingsCalls++;},showStatus:()=>{showStatusCalls++;},
          fetch:async(url,options)=>{
            if(options?.signal?.aborted)throw new DOMException('Aborted','AbortError');
            if(url==='/api/control/store/backends'){progressCalls++;return {ok:true,json:async()=>({ok:true,prepared})};}
            const body=JSON.parse(options.body);
            if(body.action==='store-backends-prepare')return {ok:true,json:async()=>({ok:true})};
            if(body.action==='store-account-login-start'){startCalls++;return {ok:true,json:async()=>({ok:true,provider_label:'Epic',login_url:'https://example.test/'})};}
            return {ok:true,json:async()=>({ok:true,detail:'connected'})};
          }
        });
        vm.runInContext(SOURCE1+'\n'+SOURCE2,context);
        (async()=>{
            // No backends: dialog appears immediately, then cancellation aborts polling.
            const pending=vm.runInContext("storeAccountConnect('epic')",context);
            assert.equal(get('store-auth-modal').classList.contains('show'),true);
            assert.equal(get('store-auth-fields').hidden,true);
            vm.runInContext('closeStoreAuth()',context);
            await pending;
            assert.equal(get('store-auth-modal').classList.contains('show'),false);
            assert.equal(startCalls,0);
            assert.equal(showStatusCalls,0);
            // A fresh connect on a ready backend exposes only provider URL + auth code.
            prepared=true;
            await vm.runInContext("storeAccountConnect('epic')",context);
            assert.equal(get('store-auth-modal').classList.contains('show'),true);
            assert.equal(get('store-auth-fields').hidden,false);
            assert.equal(get('submit').hidden,false);
            assert.equal(get('store-auth-link').href,'https://example.test/');
            assert.equal(startCalls,1);
            vm.runInContext('closeStoreAuth(true)',context);
            assert.equal(closeSettingsCalls,1);
            assert.equal(get('store-auth-modal').classList.contains('show'),false);
            assert.equal(get('store-auth-code').value,'');
            console.log('Store auth modal async cancellation, reentry and home escape: PASS');
        })().catch(e=>{console.error(e);process.exitCode=1;});
        '''
        fixture=fixture.replace('SOURCE1',repr(part)).replace('SOURCE2',repr(part2))
        proc=subprocess.run(['node','-e',fixture],capture_output=True,text=True,timeout=15)
        self.assertEqual(proc.returncode,0,proc.stdout+'\n'+proc.stderr)
        self.assertIn('PASS',proc.stdout)

if __name__=='__main__':unittest.main()
