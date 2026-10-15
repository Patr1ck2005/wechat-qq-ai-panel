"""Exercise inlined UI against a synthetic DOM; no browser or GUI automation."""
from pathlib import Path
import re
import shutil
import subprocess
import unittest


class UiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node is needed only for offline UI checks")
    def test_stale_results_cannot_reappear_after_revocation_and_content_is_text(self):
        html = (Path(__file__).parents[1] / "wq_panel/ui.html").read_text(encoding="utf-8")
        script = re.search(r"<script>([\s\S]*)</script>", html).group(1)
        harness = r'''
const vm=require('vm'), assert=require('assert');
class Element {
 constructor(){this.value='brief';this.textContent='';this.disabled=false;this.children=[];this.classList={add(){},remove(){},toggle(){return false}};}
 append(...items){this.children.push(...items)}
 replaceChildren(...items){this.children=items}
 setAttribute(){}
 addEventListener(){}
 set innerHTML(value){throw new Error('unsafe HTML sink')}
}
const nodes=new Map();
const document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element());return nodes.get(id)},querySelectorAll(){return []},createElement(){return new Element()},createTextNode(text){return {textContent:text}}};
const pending=[];
const context={document,window:{addEventListener(){},pywebview:{api:{result(){return new Promise(resolve=>pending.push(resolve))}}}},setTimeout(){return 1},clearTimeout(){},setInterval(){},Date,Map,Set,console,confirm(){return false}};
vm.createContext(context);
vm.runInContext(SOURCE,context);
function payload(text){return {ok:true,data:{result:{text,messageCount:1,created:1800100000,sources:[]}}}}
(async()=>{
 const old=context.loadResult();
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
 firstResolve(payload('OLD'));await first;
 assert.equal(document.getElementById('result-text').textContent,'LATEST');
 // Markup is rendered literally, without any DOM interpretation.
 const malicious='<img src=x onerror="dangerous()"><script>dangerous()</script>';
 const third=context.loadResult();pending.shift()(payload(malicious));await third;
 assert.equal(document.getElementById('result-text').textContent,malicious);
 vm.runInContext('policySaving=true',context);
 await context.loadResult();assert.equal(pending.length,0);
})().catch(error=>{console.error(error);process.exitCode=1});
'''
        import json
        source = "const SOURCE=" + json.dumps(script) + ";\n" + harness
        result = subprocess.run([shutil.which("node"), "-"], input=source, text=True, encoding="utf-8",
                                capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
