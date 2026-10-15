"""Exercise inlined UI against a synthetic DOM; no browser or GUI automation."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest
import json


HARNESS = r'''
const vm=require('vm'), assert=require('assert');
class Element {
 constructor(tag='div'){this.tagName=tag.toUpperCase();this.value='';this.textContent='';this.className='';this.disabled=false;this.children=[];this.attributes={};const classes=new Set();this.classList={add(...values){values.forEach(v=>classes.add(v))},remove(...values){values.forEach(v=>classes.delete(v))},contains(value){return classes.has(value)},toggle(value,force){const yes=force===undefined?!classes.has(value):force;yes?classes.add(value):classes.delete(value);return yes}};}
 append(...items){this.children.push(...items)}
 replaceChildren(...items){this.children=items}
 get firstChild(){return this.children[0]}
 setAttribute(key,value){this.attributes[key]=String(value)}
 getAttribute(key){return this.attributes[key]??null}
 removeAttribute(key){delete this.attributes[key]}
 addEventListener(){}
 set innerHTML(value){throw new Error('unsafe HTML sink')}
}
const nodes=new Map();
const document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)},querySelectorAll(){return []},createElement(tag){return new Element(tag)},createTextNode(text){return {textContent:text}}};
const pending=[];
const listeners={};
const context={document,window:{addEventListener(name,callback){listeners[name]=callback},pywebview:{api:{result(){return new Promise(resolve=>pending.push(resolve))}}}},setTimeout(){return 1},clearTimeout(){},setInterval(){},Date,Map,Set,console,confirm(){return false}};
vm.createContext(context);
vm.runInContext(SOURCE,context);
document.getElementById('preset').value='brief';
const el=id=>document.getElementById(id);
const evaluate=source=>vm.runInContext(source,context);
const tick=()=>Promise.resolve();
function payload(text){return {ok:true,data:{result:{text,messageCount:1,created:1800100000,sources:[]}}}}
const idle={busy:false,progress:'准备就绪',error:null,taskId:null,resultPreset:null};
const busy={...idle,busy:true,progress:'正在读取',taskId:'synthetic-task'};
'''


@unittest.skipUnless(shutil.which("node"), "Node is needed only for offline UI checks")
class UiTests(unittest.TestCase):
    def run_js(self, body):
        html = (Path(__file__).parents[1] / "wq_panel/ui.html").read_text(encoding="utf-8")
        script = re.search(r"<script>([\s\S]*)</script>", html).group(1)
        source = "const SOURCE=" + json.dumps(script) + ";\n" + HARNESS + "\n(async()=>{\n" + body + r'''
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        result = subprocess.run([shutil.which("node"), "-"], input=source, text=True, encoding="utf-8",
                                capture_output=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_stale_results_cannot_reappear_after_revocation_and_content_is_text(self):
        self.run_js(r'''
 const old=context.loadResult();
 assert.equal(el('result-card').getAttribute('aria-busy'),'true');
 context.clearResult();
 pending.shift()(payload('FORBIDDEN-OLD-CONTENT'));
 await old;
 assert.equal(document.getElementById('result-text').textContent,'');
 assert.equal(document.getElementById('copy').disabled,true);
 // An earlier preset response must not replace the latest selection.
 document.getElementById('preset').value='brief';const first=context.loadResult();
 document.getElementById('preset').value='daily';const second=context.loadResult();
 const firstResolve=pending.shift(),secondResolve=pending.shift();
 secondResolve(payload('LATEST'));await second;
 assert.equal(el('result-card').getAttribute('aria-busy'),'true','earlier request still owns loading state');
 firstResolve(payload('OLD'));await first;
 assert.equal(el('result-card').getAttribute('aria-busy'),'false');
 assert.equal(document.getElementById('result-text').textContent,'LATEST');
 // Markup is rendered literally, without any DOM interpretation.
 const malicious='<img src=x onerror="dangerous()"><script>dangerous()</script>';
 const third=context.loadResult();pending.shift()(payload(malicious));await third;
 assert.equal(document.getElementById('result-text').textContent,malicious);
 vm.runInContext('policySaving=true',context);
 await context.loadResult();assert.equal(pending.length,0);
''')

    def test_group_private_device_and_unknown_are_partitioned_by_metadata_and_account(self):
        self.run_js(r'''
evaluate(`
settings={watched:[]};
catalog={accounts:[{platform:'qq',account:'a'},{platform:'qq',account:'b'},{platform:'wechat',account:'w'}],conversations:[
 {platform:'qq',account:'a',conversation_id:'1',ref:'qq-group',title:'普通朋友',kind:'group'},
 {platform:'qq',account:'a',conversation_id:'2',ref:'qq-private',title:'某某群聊',kind:'private'},
 {platform:'qq',account:'a',conversation_id:'3',ref:'qq-device',title:'我的手机',kind:'device'},
 {platform:'qq',account:'a',conversation_id:'4',ref:'qq-other',title:'家庭群',kind:'new-unrecognized-kind'},
 {platform:'qq',account:'b',conversation_id:'2',ref:'qq-second-account',title:'某某群聊',kind:'private'},
 {platform:'wechat',account:'w',conversation_id:'plain-id',ref:'wx-group',title:'普通朋友',kind:'group'}
]};
policies=new Map(catalog.accounts.map(a=>[key(a),'deny']));
allowed=catalog.conversations;
custom=new Set(['qq-group','qq-private']);
`);
context.renderConversations();
let headings=el('conversation-list').children.filter(n=>n.className==='conversation-section');
assert.equal(headings.length,6);
assert(headings.some(n=>n.textContent.startsWith('QQ 群聊 · 账号 a')));
assert(headings.some(n=>n.textContent.startsWith('QQ 私聊 · 账号 a')));
assert(headings.some(n=>n.textContent.startsWith('QQ 私聊 · 账号 b')));
const rows=el('conversation-list').children.filter(n=>n.getAttribute('data-ref'));
assert.equal(rows.find(n=>n.getAttribute('data-ref')==='qq-group').getAttribute('data-kind'),'group');
assert.equal(rows.find(n=>n.getAttribute('data-ref')==='qq-private').getAttribute('data-kind'),'private');
assert.equal(rows.find(n=>n.getAttribute('data-ref')==='qq-device').getAttribute('data-kind'),'device');
assert.equal(rows.find(n=>n.getAttribute('data-ref')==='qq-other').getAttribute('data-kind'),'other');
el('filter-kind').value='private';el('filter-account').value='qq\u001fb';context.renderConversations();
const filtered=el('conversation-list').children.filter(n=>n.getAttribute('data-ref'));
assert.equal(filtered.length,1);assert.equal(filtered[0].getAttribute('data-ref'),'qq-second-account');
el('scope').value='custom';context.renderCustom();
assert(el('custom-picks').children.some(n=>n.className==='custom-section'&&n.textContent.startsWith('QQ 群聊')));
el('custom-kind').value='private';context.renderCustom();context.updateScopeInfo();
assert(!el('custom-picks').children.some(n=>n.getAttribute('data-ref')==='qq-group'));
assert.deepEqual(Array.from(context.chosenRefs()),['qq-group','qq-private']);
assert(el('scope-info').textContent.includes('QQ群聊 1'));
assert(el('scope-info').textContent.includes('QQ私聊 1'));
assert(el('scope-info').textContent.includes('已选会话仍保留'));
''')

    def test_busy_deduplicates_and_restores_after_success_or_failure_without_undoing_task_state(self):
        self.run_js(r'''
let resolve,calls=0;
const first=context.withBusy('synthetic-save',{buttons:['save-settings'],regions:['tab-settings']},()=>{calls++;return new Promise(r=>resolve=r)});
const duplicate=context.withBusy('synthetic-save',{buttons:['save-settings']},()=>{calls++;});
assert.strictEqual(first,duplicate);
assert.equal(el('save-settings').disabled,true);
assert.equal(el('tab-settings').getAttribute('aria-busy'),'true');
await tick();assert.equal(calls,1);
context.applyTaskStatus(busy);
resolve('saved');await first;
assert.equal(el('save-settings').disabled,true,'task reason must survive operation finally');
assert.equal(el('save-settings').getAttribute('aria-busy'),'false');
context.applyTaskStatus(idle);assert.equal(el('save-settings').disabled,false);
await assert.rejects(context.withBusy('synthetic-failure',{buttons:['discover-dsh'],regions:['dsh-fields']},()=>{throw new Error('synthetic')}));
assert.equal(el('discover-dsh').disabled,false);
assert.equal(el('dsh-fields').getAttribute('aria-busy'),'false');
assert.equal(el('dsh-fields').getAttribute('inert'),null);
''')

    def test_real_discovery_copy_and_export_handlers_show_busy_and_recover(self):
        self.run_js(r'''
const api=context.window.pywebview.api;
let resolve,calls=0;
api.discover_dsh=()=>{calls++;return new Promise(r=>resolve=r)};
const first=el('discover-dsh').onclick(),second=el('discover-dsh').onclick();
assert.equal(el('discover-dsh').disabled,true);await tick();assert.equal(calls,1);
resolve({ok:false,error:{code:'SYNTHETIC',message:'合成发现失败'}});await Promise.all([first,second]);
assert.equal(el('discover-dsh').disabled,false);
assert.equal(el('discover-dsh').getAttribute('aria-busy'),'false');
context.setDisabled('copy','result',false);
api.copy_result=()=>new Promise(r=>resolve=r);
const copy=el('copy').onclick();await tick();
assert.equal(el('copy').getAttribute('aria-busy'),'true');
context.clearResult();resolve({ok:true,data:{copied:true}});await copy;
assert.equal(el('copy').disabled,true,'revocation must survive copy finally');
context.setDisabled('export','result',false);
api.export_result=()=>new Promise(r=>resolve=r);
const exporting=el('export').onclick();await tick();assert.equal(el('export').disabled,true);
resolve({ok:false,error:{code:'SYNTHETIC',message:'合成导出失败'}});await exporting;
assert.equal(el('export').disabled,false);assert.equal(el('export').getAttribute('aria-busy'),'false');
''')

    def test_start_and_cancel_remain_busy_until_actual_task_completion(self):
        self.run_js(r'''
let resolveStart;
context.window.pywebview.api.start=()=>new Promise(r=>resolveStart=r);
context.window.pywebview.api.status=async()=>({ok:true,data:busy});
const starting=context.start('fetch');await tick();
context.applyTaskStatus(idle);
assert.equal(el('fetch').disabled,true,'start RPC still pending');
resolveStart({ok:true,data:busy});await starting;
assert.equal(el('fetch').disabled,true,'task still running after RPC finally');
assert.equal(el('summarize').disabled,true);
assert.equal(el('task-status').getAttribute('aria-busy'),'true');
context.window.pywebview.api.stop=async()=>({ok:true,data:{requested:true}});
await el('stop').onclick();
assert.equal(el('stop').disabled,true);
assert.equal(el('stop').getAttribute('aria-busy'),'true');
context.applyTaskStatus(idle);
assert.equal(el('stop').disabled,false);assert.equal(el('fetch').disabled,false);
assert.equal(el('task-status').getAttribute('aria-busy'),'false');
''')

    def test_quiet_permission_refresh_does_not_flash_result_loading(self):
        self.run_js(r'''
const check=context.loadResult({quiet:true});
assert.notEqual(el('result-card').getAttribute('aria-busy'),'true');
pending.shift()({ok:true,data:{result:null,hidden:true}});await check;
assert.equal(el('copy').disabled,true);
assert.equal(el('result-text').textContent,'');
''')

    def test_bootstrap_catalog_options_and_settings_show_real_loading_and_recover(self):
        self.run_js(r'''
const api=context.window.pywebview.api;
let resolveBootstrap,resolveCatalog,resolveOptions,resolveSettings;
const settings={watched:[],selectedPreset:'brief',presets:[{id:'brief',name:'速览',prompt:'合成整理',daily:false}],model:{backend:'dsh',dsh:{executable:'',home:'',provider:'synthetic',model:'test'},api:{base_url:'',model:'',key_env:'',credential_name:''}}};
api.bootstrap=()=>new Promise(r=>resolveBootstrap=r);
api.conversations=async()=>({ok:true,data:{conversations:[]}});
api.result=async()=>({ok:true,data:{result:null}});
api.status=async()=>({ok:true,data:idle});
const boot=listeners.pywebviewready();
assert.equal(el('app-main').getAttribute('aria-busy'),'true');
assert.equal(el('fetch').disabled,true);await tick();
resolveBootstrap({ok:true,data:{settings,storageWarning:false}});await boot;
assert.equal(el('app-main').getAttribute('aria-busy'),'false');
assert.equal(el('app-main').getAttribute('inert'),null);
assert(el('initial-loading').classList.contains('hidden'));
assert.equal(el('fetch').disabled,false);
api.catalog=()=>new Promise(r=>resolveCatalog=r);
const catalog=context.loadCatalog();await tick();
assert.equal(el('reload-catalog').disabled,true);
assert.equal(el('conversation-list').getAttribute('aria-busy'),'true');
resolveCatalog({ok:true,data:{accounts:[{platform:'qq',account:'synthetic'}],conversations:[],policy:null,watched:[]}});await catalog;
assert.equal(el('reload-catalog').disabled,false);
assert.equal(el('conversation-list').getAttribute('aria-busy'),'false');
assert.equal(el('save-policy').disabled,true,'onboarding must still choose a mode');
api.conversations=()=>new Promise(r=>resolveOptions=r);
const options=context.loadAllowed();await tick();
assert.equal(el('scope').disabled,true);
resolveOptions({ok:false,error:{code:'POLICY_REQUIRED',message:'合成未授权'}});await options;
assert.equal(el('scope').disabled,false);
assert.equal(el('custom-picks').getAttribute('aria-busy'),'false');
api.save_settings=()=>new Promise(r=>resolveSettings=r);
const saving=el('save-settings').onclick();await tick();
assert.equal(el('save-settings').disabled,true);
resolveSettings({ok:false,error:{code:'SYNTHETIC',message:'合成保存失败'}});await saving;
assert.equal(el('save-settings').disabled,false);
assert.equal(el('tab-settings').getAttribute('aria-busy'),'false');
''')

    def test_storage_preview_and_cleanup_have_busy_feedback_and_failure_restores_buttons(self):
        self.run_js(r'''
const api=context.window.pywebview.api;
let resolvePreview,resolveClean;
api.storage=()=>new Promise(r=>resolvePreview=r);
const preview=context.storage();await tick();
assert.equal(el('refresh-storage').disabled,true);
assert.equal(el('cache-list').getAttribute('aria-busy'),'true');
resolvePreview({ok:true,data:{categories:[{id:'dsh',label:'DSH测试记录',bytes:100,files:1,skipped:false,warning:false}],note:'合成',accessAvailable:true}});await preview;
assert.equal(el('refresh-storage').disabled,false);
assert.equal(el('cache-list').getAttribute('aria-busy'),'false');
const row=el('cache-list').children[0],button=row.children[2];
context.confirm=()=>true;
api.clean=()=>new Promise(r=>resolveClean=r);
const cleaning=button.onclick();await tick();
assert.equal(button.disabled,true);assert.equal(row.getAttribute('aria-busy'),'true');
resolveClean({ok:false,error:{code:'SYNTHETIC',message:'合成清理失败'}});await cleaning;
assert.equal(button.disabled,false);assert.equal(row.getAttribute('aria-busy'),'false');
const failed=context.storage();await tick();
resolvePreview({ok:false,error:{code:'SYNTHETIC',message:'合成统计失败'}});await assert.rejects(failed);
assert.equal(el('refresh-storage').disabled,false);
assert.equal(el('cache-list').getAttribute('aria-busy'),'false');
''')

    def test_successful_policy_save_normalizes_watched_scope_to_authorized_list(self):
        self.run_js(r'''
evaluate(`
settings={watched:['revoked'],presets:[{id:'draft',prompt:'未保存的提示词'}]};
catalog={accounts:[{platform:'qq',account:'a'}],conversations:[
 {platform:'qq',account:'a',conversation_id:'group-id',ref:'revoked',title:'合成群',kind:'group'},
 {platform:'qq',account:'a',conversation_id:'private-id',ref:'kept',title:'合成私聊',kind:'private'}
]};
policies=new Map([[key(catalog.accounts[0]),'allow']]);
selected=new Set([key(catalog.accounts[0])+'\u001fprivate-id']);
watched=new Set(['revoked']);
`);
el('scope').value='watched';
const api=context.window.pywebview.api;
api.save_policy=async()=>({ok:true,data:{policy:{revision:'new'}}});
api.bootstrap=async()=>({ok:true,data:{settings:{watched:[],presets:[]}}});
api.conversations=async()=>({ok:true,data:{conversations:[{platform:'qq',account:'a',conversation_id:'private-id',ref:'kept',title:'合成私聊',kind:'private'}]}});
api.result=async()=>({ok:true,data:{result:null}});
await el('save-policy').onclick();
assert.deepEqual(Array.from(evaluate('settings.watched')),[]);
assert.deepEqual(Array.from(evaluate('watched')),[]);
assert.equal(evaluate('settings.presets[0].prompt'),'未保存的提示词');
assert(el('scope-info').textContent.includes('本次范围 0 个会话'));
assert.equal(el('save-policy').getAttribute('aria-busy'),'false');
''')

    def test_directory_refresh_preserves_saved_watched_when_a_source_is_unavailable(self):
        self.run_js(r'''
evaluate("settings={watched:['offline-synthetic']};watched=new Set(settings.watched)");
context.window.pywebview.api.conversations=async()=>({ok:true,data:{conversations:[]}});
await context.loadAllowed();
assert.deepEqual(Array.from(evaluate('settings.watched')),['offline-synthetic']);
assert.deepEqual(Array.from(evaluate('watched')),['offline-synthetic']);
''')

    def test_initialization_failure_stops_loading_and_restores_controls(self):
        self.run_js(r'''
context.window.pywebview.api.bootstrap=async()=>({ok:false,error:{code:'SYNTHETIC',message:'合成初始化失败'}});
await listeners.pywebviewready();
assert.equal(el('app-main').getAttribute('aria-busy'),'false');
assert.equal(el('app-main').getAttribute('inert'),null);
assert.equal(el('fetch').disabled,false);
assert(el('initial-loading').classList.contains('error'));
assert(!el('initial-loading').classList.contains('hidden'));
assert(el('initial-loading-text').textContent.includes('初始化未完成'));
''')


if __name__ == "__main__":
    unittest.main()
