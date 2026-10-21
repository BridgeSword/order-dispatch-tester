// Order Dispatch Tester UI. All user-visible strings come from /api/i18n (order_tester/i18n/<lang>.json).
// ---------------- i18n ----------------
let I18N={},LANG='zh';
function t(k,v){let s=I18N[k];if(s==null)s=k;if(v)s=s.replace(/\{(\w+)\}/g,(m,n)=>v[n]!=null?v[n]:m);return s}
function applyI18n(){document.documentElement.lang=LANG=='en'?'en':'zh';document.title=t('app.title');
 document.querySelectorAll('[data-i18n]').forEach(e=>e.textContent=t(e.dataset.i18n));
 document.querySelectorAll('[data-i18n-ph]').forEach(e=>e.placeholder=t(e.dataset.i18nPh));
 document.querySelectorAll('[data-i18n-title]').forEach(e=>e.title=t(e.dataset.i18nTitle));$('langsel').value=LANG}
async function loadI18n(){let want=null;try{want=localStorage.getItem('odtLang')}catch(e){}
 let r=await (await fetch('/api/i18n'+(want?'?lang='+want:''))).json();I18N=r.t;LANG=r.lang;applyI18n()}
async function setLang(l){try{localStorage.setItem('odtLang',l)}catch(e){}await post('/api/config',{lang:l});location.reload()}
const stName=s=>s==DRAFT?t('state.draft'):s=='其它'?t('state.other'):s;
// ---------------- state / settings ----------------
let allSt=[],stMap={},stations=[],pools={start:[],end:[]},view={s:1,ox:0,oy:0},sel=new Set();
const $=id=>document.getElementById(id);
async function post(u,b){return (await fetch(u,{method:'POST',body:JSON.stringify(b)})).json()}
const NOSAVE=new Set(['q','tf','paste','hidedone','smapf','f_veh','f_grp','f_st','f_id','f_stuck','newpool','tpl_raw','tpl_json','tpl_imp','tpl_title','langsel','swa','swb','tpl_sel']);let loaded=false,saveT=null;
function poolNames(){let n=Object.keys(pools);for(const r of (cur&&cur.pools)||[])if(!n.includes(r))n.push(r);return n}
function collect(){let f={};document.querySelectorAll('input[id],select[id],textarea[id]').forEach(e=>{if(NOSAVE.has(e.id)||e.closest('#steps'))return;f[e.id]=e.type=='checkbox'?e.checked:e.value});
 let pm=document.querySelector('input[name=pm]:checked');
 return {base:$('base').value,pollSec:+$('poll').value,fields:f,pm:pm?pm.value:'start',pools,starts:pools.start||[],ends:pools.end||[],activeTemplate:cur?cur.name:'default',strategy:$('strategy').value}}
let pmSaved='start';
function applySettings(st){if(!st||typeof st!='object')return;let f=st.fields||{};
 if(st.base&&f.base==null)f.base=st.base;if(st.pollSec&&f.poll==null)f.poll=st.pollSec;
 if(f.grp)fillGroups(null,f.grp);
 for(const[k,v]of Object.entries(f)){let e=$(k);if(!e||NOSAVE.has(k))continue;if(e.type=='checkbox')e.checked=!!v;else if(v!=null)e.value=v}
 if(st.pools&&typeof st.pools=='object')pools=JSON.parse(JSON.stringify(st.pools));else pools={start:Array.isArray(st.starts)?st.starts:[],end:Array.isArray(st.ends)?st.ends:[]};
 if(st.strategy)$('strategy').value=st.strategy;pmSaved=st.pm=='S'?'start':st.pm=='E'?'end':(st.pm||'start')}
function saveNow(){if(!loaded)return;let st=collect();try{localStorage.setItem('odtSettings',JSON.stringify(st))}catch(e){}
 return post('/api/config',{base:st.base,pollSec:st.pollSec,settings:st}).catch(()=>{})}
function saveLater(){if(!loaded)return;clearTimeout(saveT);saveT=setTimeout(saveNow,600)}
async function initSettings(){let st=null,fromLocal=false;try{st=await (await fetch('/api/settings')).json()}catch(e){}
 if(!st||!Object.keys(st).length){try{st=JSON.parse(localStorage.getItem('odtSettings')||'null');fromLocal=!!st}catch(e){}}
 applySettings(st);await loadTemplates(st&&st.activeTemplate);loaded=true;renderPool();renderSt();showTab($('tab').value||'cfg');loadGeom(false);
 if(poolNames().some(r=>(pools[r]||[]).length))ensureScene().then(ok=>{if(ok){$('info').textContent=t('msg.loadedScene',{n:allSt.length});renderPool();renderSt();prevLater()}});
 document.querySelectorAll('input,select,textarea').forEach(e=>{if(e.id&&NOSAVE.has(e.id))return;if(e.closest('#steps'))return;e.addEventListener('input',saveLater);e.addEventListener('change',saveLater)});
 ['grp','veh','pri','label'].forEach(i=>{$(i).addEventListener('input',prevLater);$(i).addEventListener('change',prevLater)});
 $('info').textContent=st&&Object.keys(st).length?(fromLocal?t('msg.fromLocal'):t('msg.loaded')):'';if(fromLocal)saveNow()}
function saveCfg(){if(!loaded)return post('/api/config',{base:$('base').value,pollSec:+$('poll').value});let st=collect();try{localStorage.setItem('odtSettings',JSON.stringify(st))}catch(e){}
 return post('/api/config',{base:st.base,pollSec:st.pollSec,settings:st})}
async function loadSt(){saveCfg();$('info').textContent=t('msg.loading');let r=await (await fetch('/api/stations')).json();
 if(!r.ok){$('info').textContent=r.err;return}setScene(r.stations);stations=r.stations;$('info').textContent=t('msg.nStations',{n:stations.length});fitAll();renderSt();renderPool();prevLater()}
function setScene(list){allSt=list||[];stMap={};for(const s of allSt)stMap[s.name]=s}
let sceneP=null;
async function ensureScene(){if(allSt.length)return true;if(sceneP)return sceneP;$('info').textContent=t('msg.sceneLoading');
 sceneP=(async()=>{try{let r=await (await fetch('/api/stations')).json();if(!r.ok){$('info').innerHTML=`<b style=color:red>${t('msg.sceneFail')}: ${esc(r.err)}</b> <button onclick="ensureScene().then(()=>{renderSt();renderPool()})">${t('btn.retry')}</button>`;return false}
  setScene(r.stations);if(stations.some(s=>s.missing||s.x==null))stations=stations.map(s=>stMap[s.name]?{...stMap[s.name]}:{...s,missing:true});return true}
  catch(e){$('info').innerHTML=`<b style=color:red>${t('msg.sceneFail')}: ${esc(e)}</b>`;return false}finally{sceneP=null}})();return sceneP}
async function usePaste(){let names=[...new Set($('paste').value.split(/[\s,，;；]+/).filter(x=>x))];await ensureScene();
 stations=names.map(n=>stMap[n]?{...stMap[n]}:{name:n,type:n.replace(/\d.*/,''),x:null,y:null,pre:'',missing:true});
 let miss=stations.filter(s=>s.missing).map(s=>s.name);$('info').innerHTML=t('msg.pasted',{n:names.length})+(allSt.length?'':' '+t('msg.noSceneCoords'))+(miss.length&&allSt.length?` <b style=color:red>${t('msg.notInScene')}: ${esc(miss.join(', '))}</b>`:'');renderSt();renderPool();fitAll()}
function preOv(){let m={};$('pre_ov').value.split(/\n/).forEach(l=>{let a=l.split(/[=:，,\s]+/).filter(x=>x);if(a.length>=2)m[a[0]]=a[1]});return m}
function preOf(n){let o=preOv();if(o[n])return o[n];let s=stMap[n]||stations.find(x=>x.name==n);return s&&s.pre||''}
function pmRole(){let r=document.querySelector('input[name=pm]:checked');return r?r.value:pmSaved}
function pick(n,role){role=role||pmRole();let a=pools[role]||(pools[role]=[]);let i=a.indexOf(n);i>=0?a.splice(i,1):a.push(n);renderPool();renderSt();prevLater()}
// incremental table rows (keeps scroll / selection / open JSON boxes)
function syncRows(tb,items){let ex=new Map();for(const tr of [...tb.rows])if(tr.dataset.k)ex.set(tr.dataset.k,tr);
 let want=new Set(items.map(i=>i.k));for(const[k,tr]of ex)if(!want.has(k))tr.remove();let prev=null;
 for(const it of items){let tr=ex.get(it.k);if(!tr){tr=document.createElement('tr');tr.dataset.k=it.k;tr._c=[]}
  if(tr._cls!==(it.cls||'')){tr.className=it.cls||'';tr._cls=it.cls||''}if(tr._st!==(it.st||'')){tr.setAttribute('style',it.st||'');tr._st=it.st||''}
  while(tr.cells.length>it.c.length){tr.deleteCell(-1);tr._c.length=tr.cells.length}
  it.c.forEach((c,i)=>{let h=typeof c=='string'?c:c.h,sp=typeof c=='string'?1:(c.span||1),td=tr.cells[i]||tr.insertCell(-1);if(td.colSpan!==sp)td.colSpan=sp;if(c&&c.title!=null&&td.title!==c.title)td.title=c.title;if(tr._c[i]!==h){td.innerHTML=h;tr._c[i]=h}});
  let next=prev?prev.nextSibling:tb.firstChild;if(next!==tr)tb.insertBefore(tr,next);prev=tr}}
function mkTable(host,hdr){let tb=document.createElement('table');tb.innerHTML='<thead><tr>'+hdr.map(h=>'<th>'+h+'</th>').join('')+'</tr></thead><tbody></tbody>';host.appendChild(tb);return tb}
// pool colours: start=green, end=red, other pools from the palette
const PAL=['#1a9a1a','#d01010','#1060d0','#c07000','#008b8b','#a0309a','#606000'];
function pcol(r){if(r=='start')return PAL[0];if(r=='end')return PAL[1];let i=poolNames().filter(x=>x!='start'&&x!='end').indexOf(r);return PAL[2+((i<0?0:i)%(PAL.length-2))]}
function plab(r){return r=='start'?t('pool.start'):r=='end'?t('pool.end'):r}
let stTable=null,stSig='';
function renderSt(){let q=$('q').value.toLowerCase(),tf=$('tf').value.toLowerCase(),ov=preOv(),pn=poolNames(),sig=pn.join('|');
 if(stSig!==sig){$('st').innerHTML='';stTable=null;stSig=sig}
 if(!stTable)stTable=mkTable($('st'),[t('st.name'),t('st.type'),t('st.xy'),t('st.pre'),t('st.pick')]);
 syncRows(stTable.tBodies[0],stations.filter(s=>s.name.toLowerCase().includes(q)&&(s.type+s.name).toLowerCase().includes(tf)).slice(0,500).map(s=>{let miss=s.missing&&allSt.length,pp=ov[s.name]||s.pre||'',tt=(s.preCands||[]).join(' ')+' '+(s.preSrc||'')+(ov[s.name]?' ('+t('pre.manual')+')':''),inAny=pn.some(r=>(pools[r]||[]).includes(s.name));
  return {k:s.name,st:miss?'background:#fdd':'',c:[esc(s.name)+(miss?` <b style=color:red>${t('msg.notInScene')}</b>`:''),esc(s.type),s.x!=null?s.x.toFixed(2)+','+s.y.toFixed(2):'',
  {h:inAny?'<b>'+esc(pp)+'</b>':esc(pp),title:tt},
  pn.map(r=>`<button onclick="pick('${s.name}','${r}')" style="${(pools[r]||[]).includes(s.name)?'font-weight:bold;color:'+pcol(r):''}">${esc(plab(r))}</button>`).join('')]}}));draw()}
let hlSt=new Set();
function chips(a,r){let ov=preOv(),c=pcol(r);return a.map(n=>{let pp=ov[n]||(stMap[n]||stations.find(x=>x.name==n)||{}).pre||'';
 let tt=t('pre.of')+': '+(pp||(allSt.length?t('pre.none'):t('pre.loading')))+(ov[n]?' ('+t('pre.manual')+')':'');
 return `<span class="chip${hlSt.has(n)?' hl':''}" style="color:${c};border-color:${c};background:${c}14" data-n="${esc(n)}" data-r="${esc(r)}" title="${esc(tt)}">${esc(n)}<i title="${t('btn.del')} ${esc(n)}">×</i></span>`}).join('')||`<span class=dim>${t('pool.empty')}</span>`}
function chipClick(e){let c=e.target.closest('.chip');if(!c)return;let n=c.dataset.n,r=c.dataset.r;
 if(e.target.tagName=='I'){let a=pools[r]||[],i=a.indexOf(n);if(i>=0)a.splice(i,1);renderPool();renderSt();saveNow();prevLater();return}
 hlSt.has(n)?hlSt.delete(n):hlSt.add(n);renderPool();draw()}
function renderPools(){let pn=poolNames(),used=(cur&&cur.pools)||[];
 $('pools').innerHTML=pn.map(r=>`<div class=poolrow><span class=pn style="color:${pcol(r)}">${esc(plab(r))}</span> <span class=dim>(${(pools[r]||[]).length})</span>${used.includes(r)?'':` <span class=dim>${t('pool.unused')}</span>`}: <span class=chips data-r="${esc(r)}">${chips(pools[r]||[],r)}</span> <button onclick="clearPool('${r}')">${t('btn.clear')}</button>${r=='start'||r=='end'?'':` <button onclick="renamePool('${r}')">${t('pool.rename')}</button> <button onclick="delPool('${r}')">${t('pool.del')}</button>`}</div>`).join('');
 document.querySelectorAll('#pools .chips').forEach(e=>e.onclick=chipClick);
 for(const s of ['swa','swb']){let e=$(s),v=e.value;e.innerHTML=pn.map(r=>`<option value="${esc(r)}">${esc(plab(r))}</option>`).join('');e.value=pn.includes(v)?v:(s=='swa'?pn[0]:pn[1]||pn[0])}
 let pm=pmRole();$('pm_box').innerHTML=pn.map(r=>`<label><input type=radio name=pm value="${esc(r)}" ${r==pm?'checked':''} onchange=saveLater()>${t('map.pickFor',{p:esc(plab(r))})}</label>`).join('');
 if(!document.querySelector('input[name=pm]:checked')&&pn.length)document.querySelector('input[name=pm]').checked=true}
function clearPool(r){pools[r]=[];renderPool();renderSt();saveNow();prevLater()}
function delPool(r){if(!confirm(t('pool.delQ',{p:r})))return;delete pools[r];renderPool();renderSt();refreshStepPools();saveNow()}
function renamePool(r){let n=prompt(t('pool.renameQ',{p:r}),r);if(n==null)return;n=n.trim();if(n==r)return;if(!/^[A-Za-z_][\w]*$/.test(n)){alert(t('pool.badName'));return}if(pools[n]){alert(t('pool.exists',{p:n}));return}
 let np={};for(const k of Object.keys(pools))np[k==r?n:k]=pools[k];pools=np;let ch=false;if(cur)for(const s of cur.steps)if(s.location&&s.location.type=='pool'&&s.location.pool==r){s.location.pool=n;ch=true}
 renderSteps();if(ch)tplChanged();renderPool();renderSt();saveNow()}
function addPool(){let n=$('newpool').value.trim();if(!/^[A-Za-z_][\w]*$/.test(n)){alert(t('pool.badName'));return}if(!pools[n])pools[n]=[];$('newpool').value='';renderPool();renderSt();refreshStepPools();saveNow()}
function stratCount(){let roles=(cur&&cur.pools)||[],sz=roles.map(r=>(pools[r]||[]).length),s=$('strategy').value;if(!sz.length)return 0;
 if(s=='cartesian'){let ns=$('noself').checked,c=0,tot=sz.reduce((a,b)=>a*b,1);if(tot>200000)return tot;const rec=(i,used)=>{if(i==roles.length){c++;return}for(const x of pools[roles[i]]||[]){if(ns&&used.includes(x))continue;rec(i+1,used.concat([x]))}};rec(0,[]);return c}
 if(s=='round_robin')return Math.max(...sz);return sz[0]}
function renderPool(){renderPools();if($('cnt_auto').value=='1')$('cnt').value=stratCount();let roles=(cur&&cur.pools)||[],s=$('strategy').value;$('noreuse_l').style.display=s=='random'?'':'none';
 $('poolline').innerHTML=t('gen.line.'+s,{pools:roles.map(r=>esc(plab(r))+'('+(pools[r]||[]).length+')').join(' × ')})+t('gen.total',{n:`<span style=color:#06c>${$('cnt').value}</span>`})+(s=='random'&&$('noreuse').checked?' · '+t('gen.noreuseShort'):'');saveLater();
 let need=needRoles();
 if(!allSt.length&&roles.some(r=>(pools[r]||[]).length)){$('pre_info').innerHTML=`<span class=dim>${t('pre.loading')}</span>`;draw();return}
 $('pre_info').innerHTML=roles.map(r=>{let a=pools[r]||[],miss=a.filter(e=>!preOf(e));
  return `<b>${t('pre.of')} · ${esc(plab(r))}</b>: `+a.map(e=>esc(e)+'→'+(esc(preOf(e))||`<b style=color:${need.has(r)?'red':'#a60'}>${t('pre.none')}</b>`)).join(' ')+
  (miss.length?(need.has(r)?`<br><b style=color:red>${t('pre.missNeeded')}: ${esc(miss.join(', '))}</b>`:`<br><span style=color:#a60>⚠ ${t('pre.missUnneeded')}: ${esc(miss.join(', '))}</span>`):'')}).join('<br>');draw()}
// pools whose stations need a pre-point (an enabled 'pre' step derives from them)
function stepRef(S,id){let s=S.find(x=>x.id==id);if(s)return s;let m=/^(?:step)?(\d+)$/.exec(id||'');return m?S[+m[1]-1]||null:null}
function needRoles(){let n=new Set();if(!cur)return n;let S=cur.steps;
 for(const s of S){if(s.enabled===false||s.location.type!='pre')continue;let r=stepRef(S,s.location.step),k=0;while(r&&r.location.type=='pre'&&k++<20)r=stepRef(S,r.location.step);if(r&&r.location.type=='pool')n.add(r.location.pool)}return n}
// ---------------- template editor ----------------
let TPL={},cur=null,tplT=null,prevT=null,dirty=false;
async function loadTemplates(active){let r=await (await fetch('/api/templates')).json();TPL=r.templates||{};$('adapterinfo').textContent=t('cfg.adapter')+': '+r.adapter;
 let names=Object.keys(TPL);active=active&&TPL[active]?active:(TPL[r.active]?r.active:names[0]);fillTplSel(active);setCur(TPL[active]||r.builtin)}
function fillTplSel(v){$('tpl_sel').innerHTML=Object.keys(TPL).sort().map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');$('tpl_sel').value=v}
function setCur(tp){cur=JSON.parse(JSON.stringify(tp));dirty=false;$('tpl_title').value=cur.title||'';renderSteps();if($('tpl_raw').checked)$('tpl_json').value=JSON.stringify(cur,null,1);tplStatus('');if(loaded)renderPool();prevLater()}
function selectTpl(n){if(!TPL[n])return;if(dirty)saveTpl();setCur(TPL[n]);saveNow()}
function tplStatus(s,cls){$('tpl_status').innerHTML=s?`<span class=${cls||'dim'}>${s}</span>`:''}
function tplChanged(){dirty=true;cur.pools=locPools();tplStatus(t('tpl.unsaved'));clearTimeout(tplT);tplT=setTimeout(saveTpl,700);renderPool();prevLater()}
function locPools(){let p=[];for(const s of cur.steps)if(s.location&&s.location.type=='pool'&&s.location.pool&&!p.includes(s.location.pool))p.push(s.location.pool);return p}
async function saveTpl(){clearTimeout(tplT);cur.pools=locPools();let r=await post('/api/template_save',{template:cur,activate:true});
 if(!r.ok){tplStatus(t('tpl.saveErr')+': '+esc(r.err),'err');return false}TPL[cur.name]=r.template;cur.pools=r.template.pools;dirty=false;tplStatus(t('tpl.saved'),'ok');renderPools();return true}
function askName(def){let n=prompt(t('tpl.namePrompt'),def||'');if(n==null)return null;n=n.trim();if(!/^[A-Za-z0-9_.\-\u4e00-\u9fff]{1,64}$/.test(n)){alert(t('tpl.badName'));return null}if(TPL[n]&&!confirm(t('tpl.overwriteQ',{n})))return null;return n}
function newStep(id,name,loc){return {id,name,enabled:true,location:loc,operation:'Wait',args:{},vsOn:false,variableShape:{head:1.539,tail:1.539}}}
async function newTpl(){let n=askName('my_template');if(!n)return;cur={name:n,title:'',version:1,pools:['start','end'],steps:[newStep('s',t('step.defPick'),{type:'pool',pool:'start'}),newStep('e',t('step.defDrop'),{type:'pool',pool:'end'})]};
 if(await saveTpl()){fillTplSel(n);setCur(TPL[n]);saveNow()}}
async function copyTpl(){let n=askName(cur.name+'_copy');if(!n)return;cur=JSON.parse(JSON.stringify(cur));cur.name=n;if(await saveTpl()){fillTplSel(n);setCur(TPL[n]);saveNow()}}
async function delTpl(){if(Object.keys(TPL).length<=1){alert(t('tpl.lastOne'));return}if(!confirm(t('tpl.delQ',{n:cur.name})))return;let r=await post('/api/template_delete',{name:cur.name});if(!r.ok){alert(r.err);return}
 delete TPL[cur.name];let n=Object.keys(TPL).sort()[0];fillTplSel(n);setCur(TPL[n]);saveNow()}
function exportTpl(){let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(cur,null,1)],{type:'application/json'}));a.download=cur.name+'.json';document.body.appendChild(a);a.click();a.remove()}
async function importTpl(){let f=$('tpl_imp').files[0];if(!f)return;let tp;try{tp=JSON.parse(await f.text())}catch(e){alert(t('tpl.badJson')+': '+e.message);return}finally{$('tpl_imp').value=''}
 await importTplObj(tp,f.name)}
async function importTplObj(tp,fname){let n=askName(tp.name||String(fname||'imported').replace(/\.json$/i,''));if(!n)return false;tp.name=n;let v=await post('/api/template_validate',{template:tp});if(!v.ok){alert(t('tpl.invalid')+':\n'+v.errors.join('\n'));return false}
 cur=v.template;if(await saveTpl()){fillTplSel(n);setCur(TPL[n]);saveNow();return true}return false}
function toggleRaw(){let raw=$('tpl_raw').checked;if(raw)$('tpl_json').value=JSON.stringify(cur,null,1);else renderSteps();$('tpl_form').style.display=raw?'none':'';$('tpl_rawbox').style.display=raw?'':'none'}
function rawChanged(){let v;try{v=JSON.parse($('tpl_json').value)}catch(e){tplStatus(t('tpl.badJson')+': '+esc(e.message),'err');return}
 if(!v||typeof v!='object'||!Array.isArray(v.steps)||v.steps.some(s=>!s||typeof s!='object'||!s.location)){tplStatus(t('tpl.invalid'),'err');return}v.name=cur.name;cur=v;$('tpl_title').value=cur.title||'';tplChanged()}
const OPS=['Wait','ForkLoad','ForkUnload','ForkHeight','Script','JackLoad','JackUnload','none'];
function locCell(s,i){let L=s.location,ty=L.type,pn=poolNames(),opts=cur.steps.map((x,j)=>j==i?'':`<option value="${esc(x.id)}" ${L.step==x.id?'selected':''}>${j+1}. ${esc(x.name||x.id)}</option>`).join('');
 return `<select class=loctype onchange="setLoc(${i},'type',this.value)">${['pool','pre','fixed'].map(x=>`<option value=${x} ${ty==x?'selected':''}>${t('loc.'+x)}</option>`).join('')}</select><br>`+
 (ty=='pool'?poolSelect(L.pool,i):
  ty=='pre'?`<select class=locstep onchange="setLoc(${i},'step',this.value)"><option value="">-</option>${opts}</select>`:`<input class=locfixed size=10 value="${esc(L.station||'')}" placeholder="LM1" onchange="setLoc(${i},'station',this.value)">`)}
// pool dropdown for a 'pool' step: every existing pool (display names) + the step's own value if it is not a pool yet.
// (was <input list=datalist>: browsers filter datalist suggestions by the current value, so only 'start' was offered)
function poolSelect(v,i){let pn=poolNames();if(v&&!pn.includes(v))pn=pn.concat([v]);
 return `<select class=locpool onchange="setLoc(${i},'pool',this.value)">${pn.map(r=>`<option value="${esc(r)}" ${r==v?'selected':''}>${esc(plab(r))}${r!='start'&&r!='end'||plab(r)==r?'':' ('+r+')'}</option>`).join('')}</select>`}
// re-render the step table only when the pool list changed and no step control has focus (never clobber an open dropdown/input)
let stepPoolSig='';function refreshStepPools(){let sig=poolNames().join('|');if(sig===stepPoolSig)return;
 let a=document.activeElement;if(a&&a.closest&&a.closest('#steps')){setTimeout(refreshStepPools,500);return}if(cur)renderSteps()}
function renderSteps(){stepPoolSig=poolNames().join('|');let tb=$('steps').tBodies[0];tb.innerHTML='';cur.steps.forEach((s,i)=>{let tr=document.createElement('tr');tr.className=s.enabled===false?'off':'';tr.dataset.i=i;
 let vs=s.variableShape||{head:1.539,tail:1.539};
 tr.innerHTML=`<td><span class=hdl draggable=true title="${t('step.drag')}">☰</span><br><button class=up onclick=mvStep(${i},-1) ${i?'':'disabled'}>↑</button><button class=down onclick=mvStep(${i},1) ${i<cur.steps.length-1?'':'disabled'}>↓</button></td><td>${i+1}</td>
 <td><input type=checkbox class=sten ${s.enabled===false?'':'checked'} onchange="setF(${i},'enabled',this.checked)"></td>
 <td><input class=stid size=6 value="${esc(s.id)}" onchange="setF(${i},'id',this.value.trim())"><br><span class=dim title="${t('step.suffixTip')}">${t('step.suffix')}</span><input size=8 value="${esc(s.blockSuffix||'')}" placeholder="-${esc(s.id)}" onchange="setF(${i},'blockSuffix',this.value.trim())"></td>
 <td><input class=stname size=9 value="${esc(s.name||'')}" onchange="setF(${i},'name',this.value)"></td><td>${locCell(s,i)}</td>
 <td><input class=stop list=dl_ops size=10 value="${esc(s.operation||'none')}" onfocus="this.placeholder=this.value;this.value=''" onblur="if(!this.value)this.value=this.placeholder" onchange="if(this.value.trim())setF(${i},'operation',this.value.trim())"></td>
 <td><textarea class=stargs rows=3 onchange="setArgs(${i},this)">${esc(JSON.stringify(s.args||{}))}</textarea><span class="err argerr"></span></td>
 <td><label><input type=checkbox class=stvs ${s.vsOn?'checked':''} onchange="setVs(${i},'on',this.checked)">${t('step.vsOn')}</label><br><input type=number step=0.001 value="${vs.head}" onchange="setVs(${i},'head',this.value)"> <input type=number step=0.001 value="${vs.tail}" onchange="setVs(${i},'tail',this.value)"></td>
 <td><button class=rm onclick=rmStep(${i}) title="${t('btn.del')}">✕</button></td>`;
 tr.querySelector('.hdl').addEventListener('dragstart',e=>{e.dataTransfer.setData('text/plain',String(i));e.dataTransfer.effectAllowed='move'});
 tr.addEventListener('dragover',e=>{e.preventDefault();tr.classList.add('drag')});tr.addEventListener('dragleave',()=>tr.classList.remove('drag'));
 tr.addEventListener('drop',e=>{e.preventDefault();tr.classList.remove('drag');moveStep(parseInt(e.dataTransfer.getData('text/plain')),i)});tb.appendChild(tr)});
 if(!$('dl_ops')){let d=document.createElement('datalist');d.id='dl_ops';d.innerHTML=OPS.map(o=>`<option value="${o}">`).join('');document.body.appendChild(d)}}
function setF(i,k,v){let s=cur.steps[i];if(k=='id'){let old=s.id;if(!v||cur.steps.some((x,j)=>j!=i&&x.id==v)){alert(t('step.dupId'));renderSteps();return}cur.steps.forEach(x=>{if(x.location.type=='pre'&&x.location.step==old)x.location.step=v})}
 if(k=='blockSuffix'&&!v)delete s.blockSuffix;else s[k]=v;renderSteps();tplChanged()}
function setLoc(i,k,v){let L=cur.steps[i].location;if(k=='type'){cur.steps[i].location=v=='pool'?{type:'pool',pool:poolNames()[0]||'start'}:v=='pre'?{type:'pre',step:(cur.steps.find((x,j)=>j!=i&&x.location.type=='pool')||{}).id||''}:{type:'fixed',station:''}}else L[k]=v.trim();renderSteps();tplChanged()}
function setArgs(i,ta){let v;try{v=JSON.parse(ta.value||'{}');if(!v||typeof v!='object'||Array.isArray(v))throw new Error(t('step.argsObj'))}catch(e){ta.nextElementSibling.textContent=e.message;return}ta.nextElementSibling.textContent='';cur.steps[i].args=v;tplChanged()}
function setVs(i,k,v){let s=cur.steps[i];s.variableShape=s.variableShape||{head:1.539,tail:1.539};if(k=='on')s.vsOn=v;else{let n=parseFloat(v);if(!isFinite(n)){alert(t('vs.num'));return}s.variableShape[k]=n}tplChanged()}
function mvStep(i,d){moveStep(i,i+d)}
function moveStep(a,b){if(a==b||isNaN(a)||b<0||b>=cur.steps.length)return;let [s]=cur.steps.splice(a,1);cur.steps.splice(b,0,s);renderSteps();tplChanged()}
function rmStep(i){if(cur.steps.length<=1){alert(t('step.lastOne'));return}if(!confirm(t('step.delQ',{n:cur.steps[i].name||cur.steps[i].id})))return;let id=cur.steps[i].id;cur.steps.splice(i,1);renderSteps();tplChanged()}
function addStep(){let k=1;while(cur.steps.some(s=>s.id=='step'+k))k++;cur.steps.push(newStep('step'+k,'step'+k,{type:'pool',pool:poolNames()[0]||'start'}));renderSteps();tplChanged()}
function prevLater(){clearTimeout(prevT);prevT=setTimeout(doPreview,300)}
async function doPreview(){if(!cur)return;let r;try{r=await post('/api/preview',Object.assign(dispCfg(),{template:Object.assign({},cur,{pools:locPools()}),pools}))}catch(e){return}
 if(!r.ok){$('prev_info').innerHTML=`<span class=err>${esc(r.err)}</span>`;$('tpl_prev').textContent='';return}
 $('prev_info').textContent=t('tpl.prevInfo',{p:Object.entries(r.picks).map(([k,v])=>plab(k)+'='+v).join(', ')});$('tpl_prev').textContent=JSON.stringify(r.payload,null,1)}
// ---------------- map ----------------
const C=$('map'),X=C.getContext('2d');let geom=null,pcOff=null,pcK=1;
function showTab(tb){if(!['cfg','map','rob','ord'].includes(tb))tb='cfg';$('tab').value=tb;document.querySelectorAll('.tab').forEach(e=>e.classList.toggle('on',e.id=='tab-'+tb));
 document.querySelectorAll('#tabbar button').forEach(b=>b.classList.toggle('on',b.dataset.t==tb));saveLater();if(tb=='map'){let first=!C.dataset.sized;resizeMap();if(first)fitAll()}}
function resizeMap(){if($('tab').value!='map')return;let top=C.getBoundingClientRect().top;C.width=Math.max(300,document.documentElement.clientWidth-16);C.height=Math.max(200,window.innerHeight-top-10);C.dataset.sized=1;draw()}
window.addEventListener('resize',resizeMap);
async function loadGeom(refresh){$('geominfo').textContent=t('map.loadingGeom');let r;try{r=await (await fetch('/api/scene_geom'+(refresh?'?refresh=1':''))).json()}catch(e){$('geominfo').textContent=t('map.geomFail')+' '+e;return}
 if(!r.ok){$('geominfo').textContent=r.err||t('map.geomFail');return}setGeom(r)}
function setGeom(r){geom=r;if(r.stations&&r.stations.length){if(!allSt.length)setScene(r.stations);if(!stations.length){stations=r.stations;}
 else if(stations.some(s=>s.missing||s.x==null))stations=stations.map(s=>stMap[s.name]?{...stMap[s.name]}:{...s,missing:true});renderSt();renderPool();prevLater()}buildPC();$('geominfo').innerHTML=t('map.geomInfo',{c:r.curves.length,cs:r.curveSrc?' ('+esc(r.curveSrc)+')':'',p:r.npoints,ps:r.pointSrc?' ('+esc(r.pointSrc)+')':''})+(r.notes&&r.notes.length?` <span style=color:#a60 title="${esc(r.notes.join('\n'))}">⚠${esc(r.notes[r.notes.length-1])}</span>`:'');
 if(!stations.filter(s=>s.x!=null).length||!C.dataset.fitted)fitAll();draw()}
function buildPC(){pcOff=null;if(!geom||!geom.npoints)return;let P=geom.points,x0=1e9,y0=1e9,x1=-1e9,y1=-1e9;
 for(let i=0;i<P.length;i+=2){let x=P[i],y=P[i+1];if(x<x0)x0=x;if(x>x1)x1=x;if(y<y0)y0=y;if(y>y1)y1=y}
 pcK=Math.min(4096/((x1-x0)||1),4096/((y1-y0)||1),1/Math.max(geom.cell||0.05,0.02));let w=Math.ceil((x1-x0)*pcK)+1,h=Math.ceil((y1-y0)*pcK)+1;
 let off=document.createElement('canvas');off.width=w;off.height=h;let g=off.getContext('2d'),im=g.createImageData(w,h),d=new Uint32Array(im.data.buffer);
 for(let i=0;i<P.length;i+=2){let px=Math.floor((P[i]-x0)*pcK),py=Math.floor((y1-P[i+1])*pcK);d[py*w+px]=0xff8c8c8c}
 g.putImageData(im,0,0);pcOff={c:off,x0,y1,w,h}}
function fitAll(){let b=geom&&geom.bounds?{...geom.bounds}:null;for(const s of (allSt.length?allSt:stations)){if(s.x==null)continue;if(!b)b={minx:s.x,maxx:s.x,miny:s.y,maxy:s.y};b.minx=Math.min(b.minx,s.x);b.maxx=Math.max(b.maxx,s.x);b.miny=Math.min(b.miny,s.y);b.maxy=Math.max(b.maxy,s.y)}
 if(!b)return;view.s=Math.min((C.width-40)/((b.maxx-b.minx)||1),(C.height-40)/((b.maxy-b.miny)||1));view.ox=(C.width-(b.maxx-b.minx)*view.s)/2-b.minx*view.s;view.oy=(C.height+(b.maxy-b.miny)*view.s)/2+b.miny*view.s;
 if(C.dataset.sized)C.dataset.fitted=1;draw()}
const tx=x=>x*view.s+view.ox,ty=y=>view.oy-y*view.s;let robotsCache=[],ordersCache=[];
function draw(){X.setTransform(1,0,0,1,0,0);X.clearRect(0,0,C.width,C.height);X.font='11px sans-serif';
 if($('ly_pc').checked&&pcOff){X.imageSmoothingEnabled=false;let sc=view.s/pcK;X.drawImage(pcOff.c,tx(pcOff.x0),ty(pcOff.y1),pcOff.w*sc,pcOff.h*sc)}
 if($('ly_rt').checked&&geom){X.strokeStyle='#2a8a8a';X.lineWidth=1.2;X.beginPath();for(const c of geom.curves){let p=c.p;X.moveTo(tx(p[0][0]),ty(p[0][1]));for(let i=1;i<p.length;i++)X.lineTo(tx(p[i][0]),ty(p[i][1]))}X.stroke();
  if(view.s>12){X.fillStyle='#2a8a8a';for(const c of geom.curves){let p=c.p,m=Math.floor(p.length/2),a=p[Math.max(0,m-1)],b=p[Math.min(p.length-1,m)];let ang=Math.atan2(-(b[1]-a[1]),b[0]-a[0]),cx=tx((a[0]+b[0])/2),cy=ty((a[1]+b[1])/2);
   X.beginPath();X.moveTo(cx+6*Math.cos(ang),cy+6*Math.sin(ang));X.lineTo(cx+6*Math.cos(ang+2.5),cy+6*Math.sin(ang+2.5));X.lineTo(cx+6*Math.cos(ang-2.5),cy+6*Math.sin(ang-2.5));X.fill()}}}
 if($('ly_st').checked)drawStations();
 if($('ly_rb').checked)for(const r of robotsCache){if(r.x==null)continue;let stk=r.idle>+$('still').value&&r.orderActive;X.fillStyle=stk?'red':r.orderActive?'#f80':'#fc0';X.strokeStyle='#000';
  X.fillRect(tx(r.x)-7,ty(r.y)-7,14,14);X.strokeRect(tx(r.x)-7,ty(r.y)-7,14,14);X.fillStyle='#000';X.font='bold 12px sans-serif';X.fillText(r.name+(r.orderActive?' ['+r.order+' '+(r.orderState||'')+']':'')+(stk?' ⚠':''),tx(r.x)+9,ty(r.y)+12);X.font='11px sans-serif'}}
// stations: each pool its colour; station in 2+ pools = split + purple ring; pre-points lighter + dashed line to the station
const RING='#8a2be2';
function stPos(n){let s=stMap[n]||(allSt.length?allSt:stations).find(x=>x.name==n);return s&&s.x!=null?s:null}
function lbl(s,x,y,c){X.save();X.font='bold 12px sans-serif';X.lineWidth=3;X.strokeStyle='rgba(255,255,255,.9)';X.strokeText(s,x,y);X.fillStyle=c;X.fillText(s,x,y);X.restore()}
function dot(x,y,r,c1,c2,ring){X.save();if(c2&&c2!==c1){X.fillStyle=c1;X.beginPath();X.arc(x,y,r,Math.PI/2,Math.PI*1.5);X.fill();X.fillStyle=c2;X.beginPath();X.arc(x,y,r,-Math.PI/2,Math.PI/2);X.fill()}
 else{X.fillStyle=c1;X.beginPath();X.arc(x,y,r,0,7);X.fill()}X.lineWidth=ring?2.5:1.5;X.strokeStyle=ring||'#fff';X.beginPath();X.arc(x,y,r,0,7);X.stroke();X.restore()}
const light=c=>c+'70';
function drawStations(){let pn=poolNames(),inP={},pre={};
 for(const r of pn)for(const n of pools[r]||[]){(inP[n]=inP[n]||[]).push(r);let p=preOf(n);if(p){pre[p]=pre[p]||{};(pre[p][r]=pre[p][r]||[]).push(n)}}
 for(const s of (allSt.length?allSt:stations)){if(s.x==null||inP[s.name]||pre[s.name])continue;
  X.fillStyle=(s.type.includes('Action')||s.name.startsWith('AP'))?'#06c':'#999';X.beginPath();X.arc(tx(s.x),ty(s.y),3,0,7);X.fill();if(view.s>15){X.fillStyle='#333';X.fillText(s.name,tx(s.x)+4,ty(s.y)-4)}}
 X.save();X.setLineDash([4,3]);X.lineWidth=1.2;
 for(const p in pre){let a=stPos(p);if(!a)continue;for(const r in pre[p])for(const n of pre[p][r]){let b=stPos(n);if(!b)continue;X.strokeStyle=pcol(r);X.globalAlpha=.7;X.beginPath();X.moveTo(tx(a.x),ty(a.y));X.lineTo(tx(b.x),ty(b.y));X.stroke()}}
 X.restore();
 for(const p in pre){if(inP[p])continue;let a=stPos(p);if(!a)continue;let rs=Object.keys(pre[p]),multi=rs.length>1;
  dot(tx(a.x),ty(a.y),4.5,light(pcol(rs[0])),multi?light(pcol(rs[1])):null,multi?RING:pcol(rs[0]));lbl(p,tx(a.x)+6,ty(a.y)+13,multi?RING:pcol(rs[0]))}
 for(const n in inP){let a=stPos(n);if(!a)continue;let rs=inP[n],b=rs.length>1,x=tx(a.x),y=ty(a.y);
  dot(x,y,7,pcol(rs[0]),b?pcol(rs[1]):null,b?RING:null);lbl(n,x+9,y-6,b?RING:pcol(rs[0]))}
 for(const n of hlSt){let a=stPos(n);if(!a)continue;X.save();X.strokeStyle='#f80';X.lineWidth=3;X.beginPath();X.arc(tx(a.x),ty(a.y),12,0,7);X.stroke();X.restore()}
 drawLegend(pn)}
function drawLegend(pn){let items=pn.map(r=>['dot',pcol(r),null,null,`${plab(r)} (${(pools[r]||[]).length})`]).concat([['dot',PAL[0],PAL[1],RING,t('lg.multi')]],
 pn.map(r=>['pre',light(pcol(r)),null,pcol(r),t('lg.preOf',{p:plab(r)})]),[['dot','#06c',null,null,t('lg.otherAP')],['dot','#999',null,null,t('lg.other')]]);
 let x0=10,y0=C.height-items.length*17-14;X.save();X.setTransform(1,0,0,1,0,0);X.fillStyle='rgba(255,255,255,.88)';X.strokeStyle='#bbb';X.fillRect(x0,y0,200,items.length*17+8);X.strokeRect(x0,y0,200,items.length*17+8);
 X.font='12px sans-serif';items.forEach((it,i)=>{let y=y0+13+i*17,cx=x0+12;if(it[0]=='pre'){X.save();X.setLineDash([4,3]);X.strokeStyle=it[3];X.beginPath();X.moveTo(cx+5,y);X.lineTo(cx+16,y);X.stroke();X.restore();dot(cx,y,4.5,it[1],null,it[3])}
  else if(it[1]=='#06c'||it[1]=='#999'){X.fillStyle=it[1];X.beginPath();X.arc(cx,y,3,0,7);X.fill()}else dot(cx,y,6,it[1],it[2],it[3]);X.fillStyle='#222';X.fillText(it[4],x0+30,y+4)});X.restore()}
let drag=null;C.onmousedown=e=>drag={x:e.offsetX,y:e.offsetY,m:0};C.onmousemove=e=>{if(!drag)return;let dx=e.offsetX-drag.x,dy=e.offsetY-drag.y;if(Math.abs(dx)+Math.abs(dy)>2)drag.m=1;view.ox+=dx;view.oy+=dy;drag.x=e.offsetX;drag.y=e.offsetY;draw()};
C.onmouseup=e=>{if(drag&&!drag.m&&$('ly_st').checked){let best=null,bd=144;for(const s of (allSt.length?allSt:stations)){if(s.x==null)continue;let d=(tx(s.x)-e.offsetX)**2+(ty(s.y)-e.offsetY)**2;if(d<bd){bd=d;best=s}}if(best)pick(best.name)}drag=null};
C.onmouseleave=()=>drag=null;
C.onwheel=e=>{e.preventDefault();let f=e.deltaY<0?1.2:1/1.2;view.ox=e.offsetX-(e.offsetX-view.ox)*f;view.oy=e.offsetY-(e.offsetY-view.oy)*f;view.s*=f;draw()};
async function uploadSmap(){let f=$('smapf').files[0];if(!f)return;$('geominfo').textContent=t('map.uploading',{f:f.name,mb:(f.size/1e6).toFixed(1)});
 let r=await (await fetch('/api/smap_upload?name='+encodeURIComponent(f.name),{method:'POST',body:f})).json();if(!r.ok){alert(r.err);$('geominfo').textContent=r.err;return}C.dataset.fitted='';setGeom(r)}
async function useSmapPath(){$('geominfo').textContent=t('map.parsing');let r=await post('/api/smap_path',{path:$('smap_path').value});if(!r.ok){alert(r.err);$('geominfo').textContent=r.err;return}C.dataset.fitted='';setGeom(r)}
// ---------------- generate / drafts ----------------
function dispCfg(){return {base:$('base').value,vehicle:$('veh').value.trim(),group:$('grp').value,priority:+$('pri').value,label:$('label').value.trim(),preOverrides:preOv()}}
async function generate(){if(dirty&&!(await saveTpl()))return;let roles=cur.pools||[];
 let empty=roles.filter(r=>!(pools[r]||[]).length);if(empty.length){alert(t('gen.poolEmpty',{p:empty.map(plab).join(', ')}));return}
 if($('noself').checked&&roles.length>1&&roles.every(r=>pools[r].length==1)&&new Set(roles.map(r=>pools[r][0])).size<roles.length){alert(t('gen.sameOnly'));return}
 let need=needRoles(),miss=[];if(allSt.length)for(const r of need){let m=(pools[r]||[]).filter(e=>!preOf(e));if(m.length)miss.push(plab(r)+': '+m.join(', '))}
 if(miss.length&&!confirm(t('gen.missQ',{list:miss.join('\n')})))return;
 $('genmsg').textContent=t('gen.running');
 let r=await post('/api/generate',Object.assign(dispCfg(),{templateName:cur.name,pools,strategy:$('strategy').value,noSelf:$('noself').checked,noReuse:$('noreuse').checked,count:+$('cnt').value,settings:collect()}));
 if(!r.ok){$('genmsg').textContent='';alert(r.err);return}
 $('genmsg').innerHTML=`<b style=color:green>${t('gen.done',{n:r.n})}</b>`+(r.skipped&&r.skipped.length?` <span style=color:red title="${esc(r.skipped.map(s=>s.err).join('\n'))}">${t('gen.skipped',{n:r.skipped.length})}</span>`:'')+` <button onclick="showTab('ord')">${t('gen.goSend')}</button>`;
 r.ids.forEach(i=>sel.add(i));if(r.warn)alert(r.warn);tick()}
let grpSig='';function fillGroups(groups,keep){let s=$('grp'),cv=keep!=null?keep:s.value,names=(groups||[]).map(g=>g.name);if(cv&&!names.includes(cv))names.push(cv);
 let sig=names.join('|');if(sig===grpSig&&keep==null)return;grpSig=sig;s.innerHTML=`<option value="">${t('disp.none')}</option>`+names.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');s.value=cv}
function swapPools(){let a=$('swa').value,b=$('swb').value;if(!a||!b||a==b)return;[pools[a],pools[b]]=[pools[b]||[],pools[a]||[]];renderPool();renderSt();saveNow();prevLater()}
async function swapDrafts(){let ds=ordersCache.filter(o=>o.state==DRAFT&&sel.has(o.id));if(!ds.length){alert(t('ord.noDraftSel'));return}
 if(dirty&&!(await saveTpl()))return;
 if(!confirm(t('ord.swapQ',{n:ds.length,tpl:cur.name})+'\n\n'+ds.slice(0,8).map(o=>{let p=[...o.pair];if(p.length>1)[p[0],p[p.length-1]]=[p[p.length-1],p[0]];return `${o.id}: ${o.pairS}  ⇒  ${p.join(' → ')}`}).join('\n')+(ds.length>8?'\n... '+ds.length:'')))return;
 let r=await post('/api/swap_drafts',Object.assign(dispCfg(),{templateName:cur.name,ids:ds.map(o=>o.id)}));if(!r.ok){alert(r.err);return}
 ds.forEach(o=>delete jsonCache[o.id]);ds.forEach(o=>{let id=o.id;if(jsonOpen.has(id))fetch('/api/order?id='+encodeURIComponent(id)).then(x=>x.json()).then(j=>{jsonCache[id]=JSON.stringify(j.body,null,1);tick()})});
 alert(t('ord.swapped',{n:r.n})+(r.errors.length?'\n'+t('ord.notSwapped',{n:r.errors.length})+'\n'+r.errors.map(e=>`${e.id}${e.pair?' ('+e.pair.join('→')+')':''}: ${e.err}`).join('\n'):''));tick()}
const DRAFT='待下发';
function selDrafts(on){ordersCache.filter(o=>o.state==DRAFT).forEach(o=>on?sel.add(o.id):sel.delete(o.id));if(!on)sel.clear();tick()}
async function sendSel(){let ids=ordersCache.filter(o=>o.state==DRAFT&&sel.has(o.id)).sort((a,b)=>a.created-b.created).map(o=>o.id);if(!ids.length){alert(t('ord.noDraftSel'));return}
 if(!confirm(t('ord.sendQ',{base:$('base').value,n:ids.length,iv:$('iv').value,ma:$('maxa').value||t('ord.unl')})))return;
 let r=await post('/api/send',{ids,base:$('base').value,interval:+$('iv').value,maxActive:+$('maxa').value});if(!r.ok)alert(r.err);else ids.forEach(i=>sel.delete(i));tick()}
async function delDrafts(){let ids=ordersCache.filter(o=>o.state==DRAFT&&sel.has(o.id)).map(o=>o.id);if(!ids.length){alert(t('ord.noDraftSel'));return}
 if(!confirm(t('ord.delQ',{n:ids.length})))return;await post('/api/delete_drafts',{ids});ids.forEach(i=>sel.delete(i));tick()}
let jsonOpen=new Set(),jsonCache={},ordTable=null;
async function toggleJson(id){if(jsonOpen.has(id)){jsonOpen.delete(id)}else{jsonOpen.add(id);if(!jsonCache[id]){let r=await (await fetch('/api/order?id='+encodeURIComponent(id))).json();jsonCache[id]=r.body?JSON.stringify(r.body,null,1):t('ord.none')}}tick()}
const esc=s=>String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/"/g,'&quot;');
function stop(){post('/api/stop',{})}
async function cancel(all){let ids=ordersCache.filter(o=>o.state!=DRAFT&&sel.has(o.id)).map(o=>o.id);if(!all&&!ids.length){alert(t('ord.noSentSel'));return}
 if(!confirm(all?t('ord.cancelAllQ'):t('ord.cancelQ',{n:ids.length})))return;let r=await post('/api/cancel',{all,ids});console.log(r);ids.forEach(i=>sel.delete(i))}
// ---------------- robots ----------------
let grpClosed=new Set(JSON.parse(localStorage.getItem('rdsGrpClosed')||'[]')),lastState=null;
function grpToggle(n){grpClosed.has(n)?grpClosed.delete(n):grpClosed.add(n);localStorage.setItem('rdsGrpClosed',JSON.stringify([...grpClosed]));if(lastState)renderRobots(lastState,+$('still').value)}
function grpAll(close){let names=[...document.querySelectorAll('#rt .grp')].map(e=>e.dataset.g);grpClosed=new Set(close?names:[]);localStorage.setItem('rdsGrpClosed',JSON.stringify([...grpClosed]));if(lastState)renderRobots(lastState,+$('still').value)}
function renderRobots(r,still){lastState=r;let groups=(r.groups||[]).map(g=>({name:g.name,ids:g.robots}));let byName={};r.robots.forEach(b=>byName[b.name]=b);let used=new Set();
 let secs=groups.map(g=>{let rs=g.ids.map(id=>byName[id]).filter(Boolean);rs.forEach(b=>used.add(b.name));return {name:g.name,rs,missing:g.ids.filter(id=>!byName[id])}});
 let rest=r.robots.filter(b=>!used.has(b.name)),extra={},UNG=t('rob.ungrouped');rest.forEach(b=>{let k=b.group&&!groups.length?b.group:UNG;(extra[k]=extra[k]||[]).push(b)});
 for(const[k,v]of Object.entries(extra))secs.push({name:k,rs:v,missing:[]});
 const box=$('rt');let ex=new Map([...box.children].map(d=>[d.dataset.g,d]));let want=new Set(secs.map(x=>x.name));for(const[k,d]of ex)if(!want.has(k))d.remove();let prev=null;
 for(const sec of secs){let d=ex.get(sec.name);if(!d){d=document.createElement('div');d.dataset.g=sec.name;let h=document.createElement('div');h.className='grp';h.dataset.g=sec.name;h.onclick=()=>grpToggle(sec.name);d.appendChild(h);
   mkTable(d,['rob.name','rob.xy','rob.station','rob.order','rob.ostate','rob.disp','rob.conn','rob.blocked','rob.batt','rob.idle'].map(k=>t(k)))}
  let rs=sec.rs.sort((a,b)=>a.name.localeCompare(b.name)),nOrd=rs.filter(b=>b.orderActive).length,nW=rs.filter(b=>b.orderActive&&b.idle>still).length,closed=grpClosed.has(sec.name);
  let hh=`${closed?'▶':'▼'} ${esc(sec.name)}<span class=c>${t('rob.sum',{n:rs.length,o:nOrd})}${nW?` · <b style=color:red>⚠${nW}</b>`:''}${sec.missing.length?` · <span class=dim>${t('rob.offline')}: ${esc(sec.missing.join(', '))}</span>`:''}</span>`;
  let h=d.firstChild;if(h._h!==hh){h.innerHTML=hh;h._h=hh}let tb=d.querySelector('table');tb.style.display=closed?'none':'';
  if(!closed)syncRows(tb.tBodies[0],rs.map(b=>{let stk=b.orderActive&&b.idle>still,NO=t('rob.noOrder');
   let oc=b.orderActive?esc(b.order):(b.order?`${NO} <span class=dim title="${esc(b.order)}">(${t('rob.prev')} ${esc(b.order.slice(0,14))}…)</span>`:NO),sc=b.orderActive?`<b>${b.orderState||'?'}</b>`:(b.order?`${NO} <span class=dim>(${b.orderState||''})</span>`:NO);
   return {k:b.name,cls:stk?'stuck':'',c:[esc(b.name),b.x!=null?b.x.toFixed(2)+','+b.y.toFixed(2):'',esc(b.station||''),oc,sc,String(b.dispatchable),String(b.connected),String(b.blocked),b.battery!=null?(b.battery*100).toFixed(0)+'%':'',fmt(b.idle)+(stk?' ⚠'+t('rob.deadlock'):'')]}}));
  let next=prev?prev.nextSibling:box.firstChild;if(next!==d)box.insertBefore(d,next);prev=d}}
const fmt=s=>s<60?s.toFixed(0)+'s':(s/60).toFixed(1)+'m';
const p2=n=>String(n).padStart(2,'0');
function fmtTs(v){if(!v)return '<span class=dim>-</span>';let d=new Date(v*1000),n=new Date(),hms=p2(d.getHours())+':'+p2(d.getMinutes())+':'+p2(d.getSeconds());
 return d.toDateString()==n.toDateString()?hms:(d.getFullYear()!=n.getFullYear()?d.getFullYear()+'-':'')+p2(d.getMonth()+1)+'-'+p2(d.getDate())+' '+hms}
function fmtDur(s){if(s==null||!isFinite(s))return '<span class=dim>-</span>';s=Math.max(0,Math.round(s));let h=Math.floor(s/3600),m=Math.floor(s%3600/60),x=s%60;return h?h+':'+p2(m)+':'+p2(x):m+':'+p2(x)}
// ---------------- orders table ----------------
const OCOLK=['','col.id','col.pair','col.vs','col.veh','col.state','col.blocks','col.created','col.age','col.idle','col.started','col.ended','col.dur','col.err','col.json'];
const OSORT=[null,'id','pairS','vsTag','vehicle','state','blocks','_created','_age','_idle','started','ended','_dur','error',null];
let ordSort=(()=>{try{let v=JSON.parse(localStorage.getItem('ordSort')||'null');if(v&&OSORT[v.i])return v}catch(e){}return {i:7,d:-1}})();
function setOrdSort(i){ordSort=ordSort.i==i?{i,d:-ordSort.d}:{i,d:OSORT[i].startsWith('_')||['started','ended'].includes(OSORT[i])?-1:1};try{localStorage.setItem('ordSort',JSON.stringify(ordSort))}catch(e){}updSortInd();tick()}
function updSortInd(){if(!ordTable)return;for(const th of ordTable.tHead.rows[0].cells){let sp=th.querySelector('.sind');if(sp)sp.textContent=+th.dataset.i===ordSort.i?(ordSort.d>0?' ▲':' ▼'):''}}
function ordCmp(a,b){let k=OSORT[ordSort.i],x=a[k],y=b[k],nx=x==null||x==='',ny=y==null||y==='';
 if(nx||ny)return nx&&ny?(b._created-a._created):nx?1:-1; // empty values always last
 let r=typeof x=='number'&&typeof y=='number'?x-y:String(x).localeCompare(String(y),'zh',{numeric:true});return r*ordSort.d||(b._created-a._created)}
const FSTATES=['待下发','SENT','CREATED','TOBEDISPATCHED','RUNNING','WAITING','FAILED','FINISHED','STOPPED','SEND_FAIL','其它'];
const FKNOWN=new Set(FSTATES.slice(0,-1));
let ordFilt=(()=>{try{return JSON.parse(localStorage.getItem('ordFilter')||'{}')||{}}catch(e){return {}}})();
let grpCollapsed=new Set((()=>{try{return JSON.parse(localStorage.getItem('ordCollapsed')||'[]')}catch(e){return []}})());
let lastGroups=[];
function initFilt(){$('f_states').innerHTML=FSTATES.map(s=>`<label style="margin-right:4px"><input type=checkbox class=fst value="${s}">${stName(s)}</label>`).join('')+` <span class=dim style=font-size:11px>${t('f.noneAll')}</span>`;
 let f=ordFilt;document.querySelectorAll('.fst').forEach(x=>x.checked=(f.states||[]).includes(x.value));$('f_veh').value=f.veh||'';$('f_st').value=f.st||'';$('f_id').value=f.id||'';$('f_stuck').checked=!!f.stuck;$('hidedone').checked=!!f.hide;
 if(f.grp){$('f_grp').innerHTML+=`<option value="${esc(f.grp)}">${esc(f.grp)}</option>`;$('f_grp').value=f.grp}
 document.querySelectorAll('#ofilt input,#ofilt select').forEach(e=>{e.addEventListener('input',saveFilt);e.addEventListener('change',saveFilt)})}
function saveFilt(){ordFilt={states:[...document.querySelectorAll('.fst:checked')].map(x=>x.value),veh:$('f_veh').value.trim(),grp:$('f_grp').value,st:$('f_st').value.trim(),id:$('f_id').value.trim(),stuck:$('f_stuck').checked,hide:$('hidedone').checked};
 try{localStorage.setItem('ordFilter',JSON.stringify(ordFilt))}catch(e){}tick()}
function clearFilt(){document.querySelectorAll('#ofilt input[type=checkbox]').forEach(x=>x.checked=false);['f_veh','f_st','f_id'].forEach(i=>$(i).value='');$('f_grp').value='';saveFilt()}
function fillFiltGroups(names){let s=$('f_grp'),cv=s.value;names=[...new Set(names.concat(cv?[cv]:[]))];let sig=names.join('|');if(s._sig===sig)return;s._sig=sig;
 s.innerHTML=`<option value="">${t('f.all')}</option>`+names.map(n=>`<option value="${esc(n)}">${esc(n)}</option>`).join('');s.value=cv}
function saveCollapsed(){try{localStorage.setItem('ordCollapsed',JSON.stringify([...grpCollapsed]))}catch(e){}}
function toggleGrp(k){grpCollapsed.has(k)?grpCollapsed.delete(k):grpCollapsed.add(k);saveCollapsed();tick()}
function grpCollapseAll(c){for(const g of lastGroups)c?grpCollapsed.add(g.k):grpCollapsed.delete(g.k);saveCollapsed();tick()}
function selGrp(k,on){let g=lastGroups.find(x=>x.k==k);if(!g)return;g.rows.forEach(o=>on?sel.add(o.id):sel.delete(o.id));tick()}
function batchName(m,k){if(k=='drafts')return t('state.draft');if(k=='nobatch')return t('ord.nobatch');let n=m.name||k;if(/^#\d+$/.test(n))return (m.kind=='hist'?t('ord.histBatch'):t('ord.batch'))+' '+n;
 let mm=/^(历史批次|批次) (#\d+)$/.exec(n);return mm?(mm[1]=='历史批次'?t('ord.histBatch'):t('ord.batch'))+' '+mm[2]:n}
const TERM=['FINISHED','STOPPED','MANUAL_FINISHED','CANCELED','CANCELLED','SEND_FAIL','SKIPPED'];/* FAILED is NOT terminal: keeps counting and can be stuck */
async function tick(){try{let r=await (await fetch('/api/state')).json();if(r.groups&&r.groups.length)fillGroups(r.groups);robotsCache=r.robots;ordersCache=r.orders;
 $('run').textContent=(r.running?t('run.on'):t('run.off'))+' · '+t('run.sent')+' '+r.sent+' '+r.msg+' · '+t('run.log')+': '+r.log;
 let now=r.now||Date.now()/1000,T=+$('stuck').value,still=+$('still').value,term=TERM;
 let cnt={};r.orders.forEach(o=>cnt[o.state]=(cnt[o.state]||0)+1);let isAct=o=>!term.includes(o.state)&&o.state!=DRAFT,hasVeh=o=>!!o.assigned,nst=r.orders.filter(o=>isAct(o)&&hasVeh(o)&&o.idle>T).length,ndr=cnt[DRAFT]||0;
 $('sum').innerHTML=Object.entries(cnt).map(([k,v])=>esc(stName(k))+':'+v).join(' ')+(nst?` <b style=color:red>${t('ord.nStuck',{n:nst})}</b>`:'');
 let rst=r.robots.filter(b=>b.orderActive&&b.idle>still).length,nact=r.orders.filter(isAct).length;
 $('tb_rob').innerHTML=`${t('tab.rob')}(${r.robots.length}${rst?`, <span style=color:red>⚠${rst}</span>`:''})`;
 $('tb_ord').innerHTML=`${t('tab.ord')}(${ndr?`${t('state.draft')}${ndr}, `:''}${t('ord.active')}${nact}${nst?`, <span style=color:red>⚠${nst}</span>`:''})`;$('mapsum').innerHTML='| '+t('map.veh')+' '+r.robots.length+(rst?` <b style=color:red>${t('map.stillWithOrder')} ${rst}</b>`:'')+' | '+t('map.orders')+' '+$('sum').innerHTML;
 let selD=r.orders.filter(o=>o.state==DRAFT&&sel.has(o.id)).length;$('selinfo').innerHTML=t('ord.selInfo',{n:ndr,s:`<b>${selD}</b>`});
 for(const o of r.orders){let dr=o.state==DRAFT,done=term.includes(o.state),endT=done?(o.ended||o.changed||now):now;
  o._created=o.created||o.sent;o._age=dr?null:done?Math.max(0,endT-o.sent):o.age;o._idle=dr||(!done&&!hasVeh(o))?null:done?Math.max(0,endT-o.changed):o.idle;
  o._dur=o.started?(o.ended||(done?null:now))-o.started:null;o.pair=o.pair||['?','?'];o.pair=Array.isArray(o.pair)?o.pair:[String(o.pair)];o.pairS=o.pair.join(' → ')}
 let f=ordFilt,fst=new Set(f.states||[]),rgOf={};(r.groups||[]).forEach(g=>g.robots.forEach(id=>rgOf[id]=g.name));
 const ogrp=o=>o.group||(o.body&&o.body.group)||(o.vehicle&&rgOf[o.vehicle])||'';
 fillFiltGroups([...(r.groups||[]).map(g=>g.name),...r.orders.map(ogrp).filter(Boolean)]);
 const stkOf=o=>isAct(o)&&hasVeh(o)&&o.idle>T;
 const match=o=>{let st=o.state;if(fst.size&&!(fst.has(st)||(fst.has('其它')&&!FKNOWN.has(st))))return false;
  if(f.hide&&term.includes(o.state))return false;if(f.stuck&&!stkOf(o))return false;
  if(f.veh&&!(o.vehicle||'').toLowerCase().includes(f.veh.toLowerCase()))return false;if(f.grp&&ogrp(o)!==f.grp)return false;
  if(f.st&&!o.pairS.toLowerCase().includes(f.st.toLowerCase()))return false;if(f.id&&!o.id.toLowerCase().includes(f.id.toLowerCase()))return false;return true};
 let gm=new Map();for(const o of r.orders){let k=o.state==DRAFT?'drafts':(o.batch||'nobatch');if(!gm.has(k)){let m=o.batchMeta||{};
   gm.set(k,{k,name:batchName(k=='drafts'||k=='nobatch'?{}:m,k),meta:k=='drafts'||k=='nobatch'?{}:m,all:[],rows:[]})}
  let g=gm.get(k);g.all.push(o);if(match(o))g.rows.push(o)}
 let gs=[...gm.values()].sort((a,b)=>(b.k=='drafts')-(a.k=='drafts')||((b.meta.start||Math.max(0,...b.all.map(o=>o.sent||0)))-(a.meta.start||Math.max(0,...a.all.map(o=>o.sent||0)))));
 let nMatch=gs.reduce((a,g)=>a+g.rows.length,0),fon=fst.size||f.hide||f.stuck||f.veh||f.grp||f.st||f.id;
 $('f_info').innerHTML=fon?t('f.match',{n:`<b>${nMatch}</b>`,t:r.orders.length}):'';
 gs=gs.filter(g=>g.rows.length);lastGroups=gs;
 if(!ordTable){$('ot').innerHTML='<thead><tr>'+OCOLK.map((h,i)=>{h=h?t(h):'';return OSORT[i]?`<th data-i=${i} style="cursor:pointer;user-select:none" onclick="setOrdSort(${i})">${h}<span class=sind></span></th>`:'<th>'+h+'</th>'}).join('')+'</tr></thead><tbody></tbody>';ordTable=$('ot');updSortInd()}
 let items=[];for(const g of gs){g.rows.sort(ordCmp);let col=grpCollapsed.has(g.k),m=g.meta,sc={};g.rows.forEach(o=>{let s=stName(o.state);sc[s]=(sc[s]||0)+1});
  let nst=g.rows.filter(stkOf).length,stv=g.all.map(o=>o.started).filter(Boolean),anyAct=g.all.some(o=>o.state!=DRAFT&&!term.includes(o.state)),env=g.all.map(o=>o.ended).filter(Boolean);
  let t0=stv.length?Math.min(...stv):null,t1=anyAct?now:(env.length?Math.max(...env):null),allSel=g.rows.every(o=>sel.has(o.id));
  let SC={FINISHED:'#888',FAILED:'#e67e00',RUNNING:'#06c'};SC[t('state.draft')]='#a60';
  let info=[`<b>${col?'▶':'▼'} ${esc(g.name)}</b>`,m.start?t('ord.sentAt')+' '+fmtTs(m.start):'',t('ord.nOrders',{n:`${fon?g.rows.length+'/':''}${g.all.length}`}),
   Object.entries(sc).map(([s,n])=>`<span style="color:${SC[s]||'#333'}">${esc(s)}:${n}</span>`).join(' '),nst?`<b style=color:red>${t('ord.stuckN',{n:nst})}</b>`:'',
   t0?t('ord.total')+' '+fmtDur((t1||now)-t0)+(anyAct?' ('+t('ord.inprog')+')':''):'',m.group?`<span style="background:#eef7e6;padding:0 3px;font-size:11px">${t('ord.grp')}:${esc(m.group)}</span>`:'',
   m.maxActive!=null?`<span class=dim>${t('ord.maxa')} ${m.maxActive}${m.interval!=null?' '+t('ord.ivShort')+' '+m.interval+'s':''}</span>`:'',m.kind=='hist'?`<span class=dim title="${t(m.src=='log'?'ord.histLogTip':'ord.histGapTip')}">(${t(m.src=='log'?'ord.histLog':'ord.histGap')})</span>`:''].filter(Boolean).join(' &nbsp; ');
  items.push({k:'grp:'+g.k,cls:'ghdr',st:'background:#e8eef7',c:[`<input type=checkbox title="${t('ord.selGrp')}" ${allSel?'checked':''} onclick="event.stopPropagation()" onchange="selGrp('${g.k}',this.checked)">`,{h:`<div onclick="toggleGrp('${g.k}')" style="cursor:pointer;user-select:none">${info}</div>`,span:14}]});
  if(col)continue;
  for(const o of g.rows){let dr=o.state==DRAFT,done=term.includes(o.state),stk=isAct(o)&&hasVeh(o)&&o.idle>T;
  let age=o._age,idle=o._idle,dur=o._dur;
  items.push({k:o.id,cls:stk?'stuck':done?'done':'',st:dr?'background:#fffbe6':'',c:[`<input type=checkbox ${sel.has(o.id)?'checked':''} onchange="this.checked?sel.add('${o.id}'):sel.delete('${o.id}')">`,esc(o.id)+(o.template&&o.template!='default'?` <span class=dim>[${esc(o.template)}]</span>`:''),esc(o.pairS),
   o.vsTag?`<span style="background:#e6f0ff;padding:0 3px;font-size:11px">${esc(o.vsTag)}</span>`:'<span class=dim>-</span>',esc(o.vehicle||'')+(o.group?`${o.vehicle?' ':''}<span style="background:#eef7e6;padding:0 3px;font-size:11px" title="${t('disp.groupTip')}">${t('ord.grp')}:${esc(o.group)}</span>`:''),dr?`<b style=color:#a60>${t('state.draft')}</b>`:o.state=='FAILED'?`<b style=color:#e67e00 title="${t('ord.failedTip')}">FAILED</b>`:esc(o.state),esc(o.blocks||''),fmtTs(o._created),dr?`<span class=dim>${t('ord.genAgo',{t:fmt(o.age)})}</span>`:fmt(age),dr?'':idle==null?{h:'<span class=dim>-</span>',title:t('ord.noVehTip')}:{h:fmt(idle),title:''},dr?'':{h:fmtTs(o.started),title:o.startedSrc=='rds'?t('ord.backfillTip'):''},dr?'':{h:fmtTs(o.ended),title:o.endedSrc=='rds'?t('ord.backfillTip'):''},dr?'':{h:fmtDur(dur),title:o.ended?'':t('ord.inprog')},esc(o.error||''),
   `<button onclick="toggleJson('${o.id}')">${jsonOpen.has(o.id)?t('ord.hide'):t('ord.view')}</button>`]});
  if(jsonOpen.has(o.id))items.push({k:'json:'+o.id,c:['',{h:`<pre class=jbox style="margin:0;max-height:300px;overflow:auto;background:#f6f6f6;font-size:11px">${esc(jsonCache[o.id]||t('msg.loading'))}</pre>`,span:14}]})}}
 syncRows(ordTable.tBodies[0],items);
 renderRobots(r,still);draw()}catch(e){console.error(e)}}
loadI18n().then(()=>{initFilt();return initSettings()}).finally(()=>{setInterval(tick,1500);tick()});
