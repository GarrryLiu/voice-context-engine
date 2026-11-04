import {runtime,live} from './client/runtime.js';
import {registerView,navigate,addNavigationGuard,onNavigation} from './client/navigation.js';
import {topicName,topicNames} from './product.js';
import {documentAPI,showDocuments,showThoughts} from './documents.js';
const {$,ui,api,status,refresh,headers}=runtime;
const {liveActive,endLive,stopAll}=live;
let workspaceData={categories:['Inbox'],sessions:[],links:[]},workspaceVersion=0,workspaceLoaded=false,workspaceLoading=null,workspaceSaving=false,workspacePending=false,workspaceBlocked=false,workspaceSavePromise=null;
let graphSession=null,graphSelected=null,graphCategory='',graphListMode=false,graphScale=1,graphPan={x:0,y:0},graphDrag=null,graphFormDirty=false,graphNameAction='session';
let activeProductSession=null,graphFinishing=false,mapEnabled=false,mapProposal=null,mapWorking=false;
try{activeProductSession=localStorage.getItem('voiceline-active-product-session');}catch{}
const stateLabels={noted:'Noted',open:'Open',confirmed:'Confirmed',tentative:'Tentative',superseded:'Replaced'};
const graphTypes={idea:'Idea',question:'Open question',decision:'Decision',document:'Document',voice:'Voice note'};
function graphEl(tag,cls,text){const el=document.createElement(tag);if(cls)el.className=cls;if(text!==undefined)el.textContent=text;return el;}
function graphNotice(text,error=false){$('graph-notice').textContent=text;$('graph-notice').classList.toggle('error',error);}
async function graphRequest(data){
 const response=await fetch('/api/workspace',{method:data?'POST':'GET',headers:{...headers,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined,signal:AbortSignal.timeout(15000)});
 if(!response.ok){const error=Error(response.status===409?'Another tab changed this workspace. Export your map, then reload to see the latest version.':'Could not save the workspace. Your changes are still visible; use Export map before reloading.');error.conflict=response.status===409;throw error;}
 return response.json();
}
async function loadWorkspace(){
 if(workspaceLoaded)return;if(workspaceLoading)return workspaceLoading;
 workspaceLoading=(async()=>{const result=await graphRequest();workspaceData=result.data;workspaceVersion=result.version;workspaceLoaded=true;updateSessionStrip();})();
 try{await workspaceLoading;}finally{workspaceLoading=null;}
}
function persistWorkspace(){
 workspacePending=true;if(workspaceBlocked)return Promise.resolve(false);if(workspaceSaving)return workspaceSavePromise;
 workspaceSaving=true;graphNotice('Saving workspace…');
 workspaceSavePromise=(async()=>{
  try{while(workspacePending){workspacePending=false;const data=structuredClone(workspaceData);const result=await graphRequest({version:workspaceVersion,data});workspaceVersion=result.version;graphNotice('Saved locally · workspace v'+workspaceVersion);}return true;}
  catch(error){workspacePending=true;workspaceBlocked=true;graphNotice(error.message,true);return false;}
  finally{workspaceSaving=false;updateSessionStrip();}
 })();return workspaceSavePromise;
}
function graphCanLeave(){return !graphFormDirty||window.confirm('Discard unsaved node edits?');}
function selectedGraphSession(){return workspaceData.sessions.find(s=>s.id===graphSession);}
function graphItems(){let items=graphSession?(selectedGraphSession()?.nodes||[]):workspaceData.sessions.filter(s=>!graphCategory||s.category===graphCategory);const q=$('graph-search').value.trim().toLowerCase();return items.filter(n=>(n.title+' '+(n.content||'')).toLowerCase().includes(q));}
function graphPlace(items){
 for(let row=0;row<40;row++)for(let col=0;col<4;col++){
  const x=45+col*235,y=55+row*175;
  if(!items.some(n=>x<n.x+195&&x+195>n.x&&y<n.y+150&&y+150>n.y))return {x,y};
 }
 return {x:45,y:Math.max(0,...items.map(n=>n.y))+175};
}
function graphLinks(){return graphSession?(selectedGraphSession()?.edges||[]):workspaceData.links;}
function inspectorLinks(){return graphSelected===graphSession?workspaceData.links:graphLinks();}
function selectedGraphItem(){return graphSelected===graphSession?selectedGraphSession():graphItems().find(n=>n.id===graphSelected);}
function renderContinuity(){
 const recent=workspaceData.sessions.filter(s=>!s.demo).slice(-3).reverse();
 $('talk-resume').hidden=!recent.length;
 for(const target of ['talk-recent']){
  $(target).replaceChildren(...recent.map(item=>{
   const card=graphEl('article','continuity-card');
   const questions=item.nodes.filter(n=>n.kind==='question').length;
   const drafts=item.nodes.filter(n=>n.kind==='document').length;
   card.append(graphEl('span','continuity-category',item.category),graphEl('h3','',item.title),graphEl('p','',`${item.nodes.length} saved notes · ${questions} open questions · ${drafts} documents`));
   const actions=graphEl('div','continuity-actions');
   const resume=graphEl('button','continuity-resume','Continue talking');resume.onclick=()=>resumeProductSession(item.id);
   const review=graphEl('button','','Review');review.onclick=()=>showGraph(item.id);
   actions.append(resume,review);card.append(actions);return card;
  }));
 }
}
$('talk-browse').onclick=()=>showGraph();
function updateSessionStrip(){
 renderContinuity();
 const item=workspaceData.sessions.find(s=>s.id===activeProductSession&&s.branch===$('branch').value);$('clear-talk-focus').hidden=!item;$('active-session-name').textContent=item?'Continuing: '+item.title:'Talk freely. No setup needed.';
 $('topic-count').textContent=String(workspaceData.sessions.length);
 const recent=workspaceData.sessions.slice(-5).reverse();
 $('topics').replaceChildren(...(recent.length?recent.map(record=>{
  const button=graphEl('button','topic');button.append(graphEl('span','topic-symbol','⑂'),graphEl('span','topic-name',record.title));button.title=record.title;
  button.onclick=()=>showGraph(record.id);return button;
 }):[graphEl('p','recent-empty','Your records will appear here.')]));
}
function graphTransform(){$('graph-scene').style.transform=`translate(${graphPan.x}px,${graphPan.y}px) scale(${graphScale})`;$('graph-zoom-label').textContent=Math.round(graphScale*100)+'%';}
function graphReset(){
 const items=graphItems(),canvas=$('graph-canvas'),width=canvas.clientWidth||600,height=canvas.clientHeight||450;
 if(!items.length){graphScale=1;graphPan={x:25,y:32};graphTransform();return;}
 const left=Math.min(...items.map(n=>n.x)),top=Math.min(...items.map(n=>n.y)),right=Math.max(...items.map(n=>n.x))+174,bottom=Math.max(...items.map(n=>n.y))+135;
 graphScale=Math.max(.35,Math.min(1,(width-60)/(right-left),(height-100)/(bottom-top)));
 graphPan={x:(width-(right-left)*graphScale)/2-left*graphScale,y:(height-(bottom-top)*graphScale)/2-top*graphScale-15};graphTransform();
}
function drawGraphEdges(){
 const svg=$('graph-edges');svg.replaceChildren();const items=graphItems(),width=window.innerWidth<700?158:174;
 for(const [from,to] of graphLinks()){
  const a=items.find(n=>n.id===from),b=items.find(n=>n.id===to);if(!a||!b)continue;
  const x1=a.x+width/2,y1=a.y+52,x2=b.x+width/2,y2=b.y+52;
  const path=document.createElementNS('http://www.w3.org/2000/svg','path');const dx=(x2-x1)*.45;
  path.setAttribute('d',`M${x1},${y1} C${x1+dx},${y1} ${x2-dx},${y2} ${x2},${y2}`);svg.append(path);
 }
}
function renderGraph(){
 renderContinuity();
 const current=selectedGraphSession();
 $('graph-title').textContent=current?current.title:'Your thinking, connected.';
 $('graph-eyebrow').textContent=current?(current.demo?'EXAMPLE RECORD · '+current.category.toUpperCase():current.category.toUpperCase()+' / RECORD'):'CONNECTED THINKING';
 $('graph-subtitle').textContent=current?'Follow an idea. Find a connection. Pick up where you left off.':'Explore a topic. Follow a connection. Keep thinking.';
 $('graph-organize').hidden=!mapEnabled||!current?.branch;$('graph-back').hidden=!current;$('graph-topic-settings').hidden=!current;$('graph-session-actions').hidden=!current;$('graph-demo').hidden=workspaceData.sessions.some(s=>s.demo);
 $('graph-search').placeholder=current?'Find a thought…':'Find a topic…';
 $('graph-scope-label').textContent=current?'Ideas, questions & decisions':'Records connected by you';
 $('graph-categories').replaceChildren(...['',...workspaceData.categories].map(category=>{
  const button=graphEl('button','category-item'+(graphCategory===category&&!current?' selected':''));
  button.append(graphEl('i','category-dot'),graphEl('span','',category||'All topics'),graphEl('span','',String(workspaceData.sessions.filter(s=>!category||s.category===category).length)));
  button.onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphCategory=category;graphSession=null;graphSelected=null;$('graph-search').value='';graphReset();renderGraph();graphHash();};return button;
 }));
 $('graph-session-count').textContent=workspaceData.sessions.length;
 $('graph-session-list').replaceChildren(...workspaceData.sessions.filter(s=>!graphCategory||s.category===graphCategory).map(item=>{
  const group=graphEl('div','topic-tree');
  const button=graphEl('button','session-item'+(graphSession===item.id?' selected':''));button.title=item.title;button.append(graphEl('span','','⑂'),graphEl('span','',item.title));button.onclick=()=>openSessionMap(item.id);group.append(button);
  if(graphSession===item.id){for(const node of item.nodes){const child=graphEl('button','tree-thought'+(graphSelected===node.id?' selected':''),node.title);child.title=node.title;child.onclick=()=>{if(!graphCanLeave())return;selectGraphItem(node.id);};group.append(child);}}
  return group;
 }));
 const items=graphItems();$('graph-nodes').replaceChildren(...items.map(item=>{
  const button=graphEl('button','graph-node'+(item.id===graphSelected?' selected':''));button.dataset.id=item.id;button.dataset.kind=item.kind||'session';button.style.left=item.x+'px';button.style.top=item.y+'px';button.setAttribute('aria-label',(current?'Select thought: ':'Select record: ')+item.title);
  const type=graphEl('span','node-type',current?graphTypes[item.kind]:item.category);if(!current&&item.demo)type.append(graphEl('span','demo-chip','EXAMPLE'));
  button.append(type,graphEl('strong','',item.title));
  if(current){const state=item.content?.match(/^\[(noted|open|confirmed|tentative|superseded)\] /);if(state)button.append(graphEl('span','node-state state-'+state[1],stateLabels[state[1]]));button.append(graphEl('span','node-preview',item.content?.replace(/^\[(noted|open|confirmed|tentative|superseded)\] /,'')||'A little room for your next idea.'));}
  else button.append(graphEl('small','',item.nodes.length+' thoughts · '+item.edges.length+' connections'));
  button.onclick=()=>{if(graphDrag?.moved)return;if(current)selectGraphItem(item.id);else openSessionMap(item.id);};
  button.onpointerdown=event=>{if(event.button!==0)return;event.stopPropagation();graphDrag={id:item.id,clientX:event.clientX,clientY:event.clientY,x:item.x,y:item.y,moved:false};button.setPointerCapture(event.pointerId);};
  button.onpointermove=event=>{if(graphDrag?.id!==item.id)return;const dx=(event.clientX-graphDrag.clientX)/graphScale,dy=(event.clientY-graphDrag.clientY)/graphScale;if(Math.abs(dx)+Math.abs(dy)>4)graphDrag.moved=true;if(!graphDrag.moved)return;item.x=Math.max(0,Math.min(1700,graphDrag.x+dx));item.y=Math.max(0,Math.min(1200,graphDrag.y+dy));button.style.left=item.x+'px';button.style.top=item.y+'px';drawGraphEdges();};
  button.onpointerup=()=>{if(graphDrag?.id!==item.id)return;if(graphDrag.moved){persistWorkspace();setTimeout(()=>{graphDrag=null;},0);}else graphDrag=null;};
  button.onpointercancel=()=>{if(graphDrag?.moved)persistWorkspace();graphDrag=null;};return button;
 }));
 $('graph-clusters').replaceChildren();
 if(!current){for(const category of [...new Set(items.map(n=>n.category))]){
  const members=items.filter(n=>n.category===category);const label=graphEl('span','graph-cluster',category);label.style.left=Math.min(...members.map(n=>n.x))+'px';label.style.top=Math.max(0,Math.min(...members.map(n=>n.y))-24)+'px';$('graph-clusters').append(label);
 }}drawGraphEdges();
 $('graph-empty').hidden=!!items.length;$('graph-empty').querySelector('h2').textContent=$('graph-search').value?'No matching thoughts.':'A thought starts with your voice.';
 $('graph-list').replaceChildren(...items.map(item=>{const button=graphEl('button','graph-row');button.append(graphEl('strong','',item.title),graphEl('small','',current?graphTypes[item.kind]:item.category));button.onclick=()=>current?selectGraphItem(item.id):openSessionMap(item.id);return button;}));
 $('graph-canvas').hidden=graphListMode;$('graph-list').hidden=!graphListMode;
 $('graph-map-toggle').classList.toggle('selected',!graphListMode);$('graph-list-toggle').classList.toggle('selected',graphListMode);
 const linked=new Set(graphLinks().filter(e=>e.includes(graphSelected)).flat());
 for(const node of $('graph-nodes').children)node.classList.toggle('muted-node',!!graphSelected&&graphSelected!==graphSession&&node.dataset.id!==graphSelected&&!linked.has(node.dataset.id));
 $('graph-counts').textContent=items.length+(current?' thoughts':' topics')+' · '+graphLinks().filter(e=>e.every(id=>items.some(n=>n.id===id))).length+' connections';
 renderGraphInspector();
}
function selectGraphItem(id){if(graphSelected===id||!graphCanLeave())return;graphFormDirty=false;graphSelected=id;renderGraph();}
function renderGraphInspector(){
 const current=selectedGraphSession(),item=graphSelected===graphSession?current:selectedGraphItem();$('graph-workspace').classList.toggle('has-selection',!!item);$('graph-inspector-empty').hidden=!!item;$('graph-editor').hidden=!item;if(!item)return;
 const editingTopic=item===current;const nodeContext=current&&!editingTopic;
 $('graph-selection-kind').textContent=nodeContext?(graphTypes[item.kind]||'Thought').toUpperCase():'TOPIC';$('graph-edit-title').value=item.title;
 $('graph-category-label').hidden=!!nodeContext;$('graph-kind-label').hidden=!nodeContext||item.kind==='voice';$('graph-content-label').hidden=!nodeContext;
 $('graph-edit-category').replaceChildren(...workspaceData.categories.map(c=>new Option(c,c)));$('graph-edit-category').value=item.category||current?.category;
 $('graph-edit-kind').value=item.kind||'idea';$('graph-edit-content').value=item.content||'';
 $('graph-open-session').hidden=!!current;$('graph-source').hidden=!item.source;
 $('graph-provenance').textContent=item.source?'Edited notes are separate from the original source.':!current&&item.demo?'Example content for exploring the product. No model calls were made.':current?'Map edits organize this record. Voice resumes its spoken branch context; these edits are not added to model memory.':'A record can grow across conversations. Topic filing is manual in this preview.';
 const candidates=editingTopic?workspaceData.sessions:graphItems();const others=candidates.filter(n=>n.id!==item.id);$('graph-connect-target').closest('.inspector-connections').hidden=false;$('graph-connect-target').replaceChildren(...others.map(n=>new Option(n.title,n.id)));$('graph-connect').disabled=!others.length;
 $('graph-connections').replaceChildren(...inspectorLinks().filter(e=>e.includes(item.id)).map(edge=>{const other=candidates.find(n=>n.id===edge.find(id=>id!==item.id));const b=graphEl('button','','↔ '+(other?.title||'Hidden node')+' ×');b.type='button';b.title='Remove connection';b.onclick=()=>{const links=inspectorLinks();links.splice(links.indexOf(edge),1);persistWorkspace();renderGraph();};return b;}));
}
function graphHash(){history.replaceState(null,'','#library'+(graphSession?'/'+encodeURIComponent(graphSession):''));}
async function enterGraph(id=null){
 try{await loadWorkspace();graphFormDirty=false;document.body.dataset.view='workspace';$('documents-workspace').hidden=true;$('graph-workspace').hidden=false;for(const id of ['nav-thoughts','nav-documents'])$(id).classList.remove('selected');$('nav-workspace').classList.add('selected');graphSession=workspaceData.sessions.some(s=>s.id===id)?id:null;graphSelected=null;$('topic-title').textContent='Workspace';$('graph-search').value='';graphReset();renderGraph();graphHash();}
 catch(error){status('Could not load the workspace. Check the local server.');throw error;}
}
function openSessionMap(id){if(!graphCanLeave())return;graphFormDirty=false;graphSession=id;graphSelected=null;$('graph-search').value='';graphReset();renderGraph();graphHash();}
function graphNameDialog(action){if(!graphCanLeave())return;graphNameAction=action;$('graph-name-heading').textContent=action==='category'?'Make room for a new category.':action==='node'?'Follow a new thought.':'What’s on your mind?';$('graph-name-eyebrow').textContent='A NEW '+(action==='session'?'RECORD':action.toUpperCase());$('graph-name').value='';$('graph-name-dialog').showModal();$('graph-name').focus();}
$('graph-name-cancel').onclick=()=>$('graph-name-dialog').close();
$('graph-name-form').onsubmit=async event=>{
 event.preventDefault();const title=$('graph-name').value.trim();if(!title)return;
 try{await loadWorkspace();if(graphNameAction==='category'){if(title.length>60||workspaceData.categories.includes(title))throw Error('Choose a unique category name, up to 60 characters.');workspaceData.categories.push(title);graphCategory=title;}
 else if(graphNameAction==='node'){const s=selectedGraphSession();if(!s)return;const id=crypto.randomUUID();s.nodes.push({id,title,content:'',kind:'idea',...graphPlace(s.nodes),source:null});if(graphSelected)s.edges.push([graphSelected,id]);graphSelected=id;graphFormDirty=false;}
 else{const id=crypto.randomUUID();workspaceData.sessions.push({id,title,category:graphCategory||'Inbox',branch:null,demo:false,...graphPlace(workspaceData.sessions),nodes:[],edges:[]});graphSession=id;graphSelected=null;}
 $('graph-name-dialog').close();await persistWorkspace();renderGraph();graphReset();graphHash();}
 catch(error){graphNotice(error.message,true);}
};
$('graph-editor').oninput=event=>{if(event.target.id==='graph-connect-target')return;graphFormDirty=true;graphNotice('Unsaved node edits · save changes to keep them.');};
$('graph-editor').onsubmit=event=>{event.preventDefault();const item=selectedGraphItem();if(!item)return;item.title=$('graph-edit-title').value.trim()||item.title;if(graphSession&&item.id!==graphSession){item.content=$('graph-edit-content').value;if(item.kind!=='voice')item.kind=$('graph-edit-kind').value;}else item.category=$('graph-edit-category').value;graphFormDirty=false;persistWorkspace();renderGraph();};
$('graph-connect').onclick=()=>{const target=$('graph-connect-target').value;if(!target||!graphSelected||!graphCanLeave())return;const links=inspectorLinks();if(!links.some(e=>e.includes(target)&&e.includes(graphSelected)))links.push([graphSelected,target]);graphFormDirty=false;persistWorkspace();renderGraph();};
$('graph-close-selection').onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphSelected=null;renderGraph();};
$('graph-open-session').onclick=()=>openSessionMap(graphSelected);
const graphDelete=graphEl('button','','Remove from map');graphDelete.type='button';$('graph-editor').append(graphDelete);
graphDelete.onclick=()=>{const item=selectedGraphItem();if(!item||!window.confirm('Remove this '+(graphSession?'node':'record')+' from the map? Original voice notes and documents will be kept.'))return;
 if(graphSession&&item.id!==graphSession){const s=selectedGraphSession();s.nodes=s.nodes.filter(n=>n.id!==item.id);s.edges=s.edges.filter(e=>!e.includes(item.id));}
 else{workspaceData.sessions=workspaceData.sessions.filter(s=>s.id!==item.id);workspaceData.links=workspaceData.links.filter(e=>!e.includes(item.id));if(activeProductSession===item.id){activeProductSession=null;try{localStorage.removeItem('voiceline-active-product-session');}catch{}}}
 graphFormDirty=false;graphSelected=null;if(!selectedGraphSession())graphSession=null;persistWorkspace();renderGraph();graphHash();};
$('graph-source').onclick=async()=>{
 const item=selectedGraphItem();if(!item||!graphCanLeave())return;
 try{const result=await api('/api/maps/provenance?node='+encodeURIComponent(item.id));
  if(result.evidence.length){$('map-evidence-items').replaceChildren(...result.evidence.map(e=>{
   const row=graphEl('article','outcome-item');row.append(graphEl('p','',e.quote));const open=graphEl('button','','Open full voice note ↗');open.onclick=async()=>{if(await showDocuments(e.document_id))$('map-evidence-dialog').close();};row.append(open);return row;
  }));$('map-evidence-dialog').showModal();}
  else if(item.source){graphFormDirty=false;await showDocuments(item.source);}
 }catch{graphNotice('Could not open sources. Your notes are kept.',true);}
};
$('map-evidence-close').onclick=()=>$('map-evidence-dialog').close();
function showGraph(id=null){return navigate('workspace',id);}
registerView('workspace',enterGraph);addNavigationGuard(graphCanLeave);onNavigation(name=>{if(name!=='workspace')graphFormDirty=false;});
$('graph-topic-settings').onclick=()=>selectGraphItem(graphSession);
$('graph-back').onclick=()=>showGraph();$('nav-workspace').onclick=()=>showGraph();$('library-records').onclick=()=>showGraph();
$('graph-new-session').onclick=()=>graphNameDialog('session');$('graph-empty-new').onclick=()=>graphSession?graphNameDialog('node'):showThoughts();$('graph-add-category').onclick=()=>graphNameDialog('category');$('graph-add-node').onclick=()=>graphNameDialog('node');
$('graph-search').oninput=()=>{if(!graphCanLeave()){$('graph-search').value='';return;}graphFormDirty=false;graphSelected=null;renderGraph();};
$('graph-map-toggle').onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphListMode=false;renderGraph();};$('graph-list-toggle').onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphListMode=true;renderGraph();};
function zoomGraph(factor,cx,cy){const old=graphScale;graphScale=Math.min(1.8,Math.max(.35,graphScale*factor));graphPan.x=cx-(cx-graphPan.x)*graphScale/old;graphPan.y=cy-(cy-graphPan.y)*graphScale/old;graphTransform();}
$('graph-zoom-in').onclick=()=>zoomGraph(1.2,200,180);$('graph-zoom-out').onclick=()=>zoomGraph(1/1.2,200,180);$('graph-fit').onclick=graphReset;
$('graph-canvas').addEventListener('wheel',event=>{event.preventDefault();const rect=$('graph-canvas').getBoundingClientRect();zoomGraph(event.deltaY<0?1.08:1/1.08,event.clientX-rect.left,event.clientY-rect.top);},{passive:false});
$('graph-canvas').onpointerdown=event=>{if(event.target.closest('button')||event.button!==0)return;graphDrag={pan:true,clientX:event.clientX,clientY:event.clientY,x:graphPan.x,y:graphPan.y};$('graph-canvas').setPointerCapture(event.pointerId);};
$('graph-canvas').onpointermove=event=>{if(!graphDrag?.pan)return;graphPan={x:graphDrag.x+event.clientX-graphDrag.clientX,y:graphDrag.y+event.clientY-graphDrag.clientY};graphTransform();};
$('graph-canvas').onpointerup=()=>{if(graphDrag?.pan)graphDrag=null;};
async function resumeProductSession(id=graphSession){
 if(!graphCanLeave()||workspaceBlocked)return;
 if(runtime.starting||runtime.switching||runtime.recording){status('Finish your recording before continuing a topic.');return;}
 const item=workspaceData.sessions.find(s=>s.id===id);if(!item)return;
 runtime.setSwitching(true);
 try{if(liveActive())await endLive('Microphone paused to restore your topic.');else if(runtime.busy)await stopAll();if(!$('branch').options.length)await refresh();if(!item.branch){const branch='session-'+crypto.randomUUID().slice(0,16);await api('/api/control',{action:'new_branch',branch});item.branch=branch;topicNames[branch]=item.title;try{localStorage.setItem('voice-topic-names',JSON.stringify(topicNames));}catch{}if(!await persistWorkspace())throw Error('workspace unsaved');}
 await api('/api/control',{action:'switch',branch:item.branch});await refresh();activeProductSession=item.id;try{localStorage.setItem('voiceline-active-product-session',item.id);}catch{}graphFormDirty=false;runtime.setSwitching(false);await showThoughts();updateSessionStrip();status('Topic restored. Start talking when you’re ready.');}
 catch{status('Could not restore this topic. Your saved notes are kept.');graphNotice('Could not resume this record. Check the local server.',true);}
 finally{runtime.setSwitching(false);}
}
$('graph-continue').onclick=()=>resumeProductSession();
async function finishProductSession(){
 if(graphFinishing)return;
 if(runtime.starting||runtime.switching||runtime.recording){status('Send your recording before reviewing notes.');return;}
 graphFinishing=true;$('finish-session').disabled=true;
 try{
  if(liveActive())await endLive('Microphone paused for review.');else if(runtime.busy)await stopAll();
  await loadWorkspace();await refresh();const branch=$('branch').value;
  if(mapEnabled){await generateMap(branch);return;}
  let item=workspaceData.sessions.find(s=>s.id===activeProductSession&&s.branch===branch)||workspaceData.sessions.find(s=>s.branch===branch);
  const documents=[];let offset=0;
  do{const result=await documentAPI('?'+new URLSearchParams({branch,status:'active',offset:String(offset)}));documents.push(...result.documents);offset=result.next_offset;}while(offset!==null);
  if(!documents.length&&!item){await showDocuments();return;}
  if(!item){item={id:crypto.randomUUID(),title:documents.find(d=>d.kind==='voice')?.title||'Conversation notes',category:'Inbox',branch,demo:false,...graphPlace(workspaceData.sessions),nodes:[],edges:[]};workspaceData.sessions.push(item);}
  for(const doc of documents){
   if(item.nodes.some(n=>n.source===doc.id))continue;
   const full=await documentAPI('/item?id='+encodeURIComponent(doc.id));
   item.nodes.push({id:crypto.randomUUID(),title:doc.title,content:full.content,kind:doc.kind==='voice'?'voice':'document',...graphPlace(item.nodes),source:doc.id});
  }
  if(!await persistWorkspace())throw Error('workspace unsaved');
  activeProductSession=item.id;try{localStorage.setItem('voiceline-active-product-session',item.id);}catch{}
  updateSessionStrip();await showGraph(item.id);showOutcome(item);
 }catch{status('Could not collect these notes. Confirmed words are still saved in Workspace → Documents.');}
 finally{graphFinishing=false;$('finish-session').disabled=false;}
}
let outcomeRecord=null;
function showOutcome(item){
 outcomeRecord=item.id;$('outcome-notice').textContent='';
 $('outcome-title').textContent=item.title;
 const voice=item.nodes.filter(n=>n.kind==='voice').length;
 $('outcome-description').textContent=`${voice} original voice note${voice===1?'':'s'} · ${item.nodes.length-voice} other saved notes. Your spoken context is ready to resume.`;
 $('outcome-items').replaceChildren(...item.nodes.slice(-4).map(node=>{
  const row=graphEl('article','outcome-item');row.append(graphEl('small','',graphTypes[node.kind]||'Note'),graphEl('strong','',node.title),graphEl('p','',node.content.slice(0,240)||'No text yet.'));return row;
 }));$('talk-outcome').showModal();
}
$('outcome-close').onclick=()=>$('talk-outcome').close();
$('outcome-open').onclick=async()=>{if(await showGraph(outcomeRecord))$('talk-outcome').close();};
$('outcome-continue').onclick=async()=>{$('talk-outcome').close();await resumeProductSession(outcomeRecord);};
$('finish-session').onclick=finishProductSession;
$('clear-talk-focus').onclick=async()=>{
 if(runtime.starting||runtime.switching||runtime.recording){status('Send your recording before clearing focus.');return;}
 runtime.setSwitching(true);$('clear-talk-focus').disabled=true;
 try{
  if(liveActive())await endLive('Microphone paused.');else if(runtime.busy)await stopAll();
  const branch='talk-'+crypto.randomUUID().slice(0,16);
  await api('/api/control',{action:'new_branch',branch});await api('/api/control',{action:'switch',branch});
  activeProductSession=null;try{localStorage.removeItem('voiceline-active-product-session');}catch{}
  await refresh();updateSessionStrip();status('Ready to talk freely. Your previous record is kept in Workspace.');
 }catch{status('Could not clear focus. Your saved notes are kept.');}
 finally{runtime.setSwitching(false);$('clear-talk-focus').disabled=false;}
};
const recordBranchObserver=new MutationObserver(updateSessionStrip);recordBranchObserver.observe($('branch'),{childList:true});
window.addEventListener('pagehide',()=>recordBranchObserver.disconnect());

$('graph-demo').onclick=async()=>{
 if(!graphCanLeave()||workspaceData.sessions.some(s=>s.demo))return;graphFormDirty=false;
 const node=(id,title,content,kind,x,y)=>({id,title,content,kind,x,y,source:null});
 const prefix=crypto.randomUUID().slice(0,8);const example=(suffix,title,category,x,y,nodes,edges)=>({id:prefix+suffix,title,category,branch:null,demo:true,x,y,nodes,edges});
 for(const c of ['Product','Research','Personal'])if(!workspaceData.categories.includes(c))workspaceData.categories.push(c);
 const sessions=[example('a','A voice-first thinking space','Product',40,110,[node('a','Thinking out loud','A place to explore ideas before they become a finished document. Voice is the starting point, not the final format.','idea',35,140),node('b','Keep the thread','A session can be resumed across days. Ideas keep their sources and their connections.','idea',275,35),node('c','Who is this for?','Start with people who think by talking: researchers, builders, and anyone working through an unfinished idea.','question',275,240),node('d','Start with one clear loop','Speak → organize → revisit → continue. Make this feel natural before adding more features.','decision',515,140)],[['a','b'],['a','c'],['b','d'],['c','d']]),example('b','The cost of a good conversation','Research',320,35,[node('a','Stage-aware orchestration','Route transcription, reasoning, and synthesis independently. Measure latency and cost separately.','idea',40,100),node('b','What should trigger escalation?','Can uncertainty, task complexity, and available context guide model selection?','question',280,35),node('c','A fair comparison','Compare routing policies on the same recorded interactions, with quality checks and cancellation scenarios.','document',280,230)],[['a','b'],['a','c']]),example('c','A calmer morning routine','Personal',320,255,[node('a','Leave space to think','A short walk and a voice note before opening the inbox.','idea',45,140),node('b','Try it for a week','Notice whether thoughts are easier to return to later.','decision',290,140)],[['a','b']]),example('d','From conversation to knowledge','Product',595,155,[node('a','Not every sentence is a node','Meaningful topics, decisions, and questions deserve a place on the map.','idea',45,130),node('b','Make structure editable','Suggested connections should stay suggestions until the user chooses them.','decision',290,130)],[['a','b']])];
 const startY=workspaceData.sessions.length?Math.max(...workspaceData.sessions.map(s=>s.y))+190:0;for(const s of sessions){s.y+=startY;}
 workspaceData.sessions.push(...sessions);workspaceData.links.push([sessions[0].id,sessions[1].id],[sessions[0].id,sessions[2].id],[sessions[1].id,sessions[3].id],[sessions[2].id,sessions[3].id]);const saved=await persistWorkspace();graphSession=null;graphCategory='';graphReset();renderGraph();if(saved)graphNotice('Example workspace · sample content only. Your real sessions are kept separately.');
};
window.addEventListener('beforeunload',event=>{if(graphFormDirty||workspacePending||workspaceSaving){event.preventDefault();event.returnValue='';}});
const graphTools=graphEl('div','graph-data-tools');
for(const [label,fn] of [['Export map',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(workspaceData,null,2)],{type:'application/json'}));const a=graphEl('a');a.href=url;a.download='voiceline-workspace.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}],['Reload',async()=>{if(!graphCanLeave()||((workspacePending||workspaceBlocked)&&!window.confirm('Reload the saved workspace? Export first to keep unsaved map changes.')))return;workspaceLoaded=false;try{await loadWorkspace();workspacePending=false;workspaceBlocked=false;graphSelected=null;graphFormDirty=false;if(!selectedGraphSession())graphSession=null;renderGraph();graphNotice('Loaded the latest saved workspace.');}catch{graphNotice('Could not reload the workspace.',true);}}]]){const b=graphEl('button','',label);b.onclick=fn;graphTools.append(b);}
document.querySelector('.graph-heading-actions').append(graphTools);
loadWorkspace().catch(()=>{});


const graphResizeObserver=new ResizeObserver(()=>{if(document.body.dataset.view==='workspace'){graphReset();drawGraphEdges();}});graphResizeObserver.observe($('graph-canvas'));window.addEventListener('pagehide',()=>graphResizeObserver.disconnect());

// Suggestions are stored separately; only explicit Apply changes the workspace.
function mapConnections(edges,titles,label='Suggested connections'){
 const details=graphEl('details','map-connections');details.append(graphEl('summary','',label+' · '+edges.length));
 for(const edge of edges){const row=graphEl('div','map-connection');row.append(graphEl('p','',titles.get(edge.from)+' → '+titles.get(edge.to)+' · '+edge.relation));for(const source of edge.evidence)row.append(graphEl('blockquote','',source.quote));details.append(row);}
 return details;
}
async function generateMap(branch){
 if(mapWorking||!graphCanLeave()||workspaceBlocked)return;
 if(workspaceSaving&&!await workspaceSavePromise)return;
 mapWorking=true;mapProposal=null;$('map-proposal-topics').replaceChildren();
 $('map-proposal-title').textContent='Organizing your conversation…';$('map-proposal-notice').textContent='Reading saved voice notes. This calls your configured text model.';
 $('map-proposal-apply').disabled=true;$('map-proposal-cancel').disabled=true;$('map-proposal-dialog').showModal();
 try{
  const notes=await documentAPI('?'+new URLSearchParams({branch,kind:'voice',status:'active'}));
  if(!notes.documents.length){$('map-proposal-title').textContent='A thought starts with your voice';$('map-proposal-notice').textContent='There are no saved voice notes in this conversation yet. Start talking, then return here.';return;}
  const result=await api('/api/maps/propose',{branch},{signal:AbortSignal.timeout(150000)});mapProposal=result;
  $('map-proposal-title').textContent=result.proposal.title;
  const sourceById=new Map(result.sources.map(s=>[s.id,s]));
  $('map-proposal-topics').replaceChildren(...result.proposal.topics.map(topic=>{
   const card=graphEl('section','map-topic-preview');card.append(graphEl('h3','',topic.title),graphEl('p','',topic.summary));
   for(const node of topic.nodes){
    const row=graphEl('article','map-node-preview');row.append(graphEl('small','',graphTypes[node.kind]+' · '+(stateLabels[node.state]||node.state)),graphEl('strong','',node.title),graphEl('p','',node.content));
    const evidence=graphEl('details');evidence.append(graphEl('summary','',node.evidence.length+' source excerpts'));
    for(const e of node.evidence){const quote=graphEl('blockquote','',e.quote);quote.title='Source '+e.source;const open=graphEl('button','','Read source ↗');open.onclick=async()=>{if(await showDocuments(sourceById.get(e.source).document_id))$('map-proposal-dialog').close();};evidence.append(quote,open);}
    row.append(evidence);card.append(row);
   }
   const connections=mapConnections(topic.edges,new Map(topic.nodes.map(n=>[n.key,n.title])));card.append(connections);return card;
  }));
  if(result.proposal.links.length)$('map-proposal-topics').append(mapConnections(result.proposal.links,new Map(result.proposal.topics.map(t=>[t.key,t.title])),'Connections between topics'));
  $('map-proposal-notice').textContent=result.already_applied?'This conversation already has a saved map. Saving again will not duplicate it.':result.proposal.topics.length+' topics · '+result.proposal.links.length+' cross-topic connections. Review the suggestions and evidence, then save or close.';
  $('map-proposal-apply').disabled=false;
 }catch{$('map-proposal-title').textContent='Could not generate a map';$('map-proposal-notice').textContent='No map changes were saved. Your voice notes are kept. Check model configuration, or try again if the conversation changed.';}
 finally{mapWorking=false;$('map-proposal-cancel').disabled=false;}
}
$('map-proposal-cancel').onclick=()=>$('map-proposal-dialog').close();
$('map-proposal-dialog').addEventListener('cancel',event=>{if(mapWorking)event.preventDefault();});
$('map-proposal-apply').onclick=async()=>{
 if(!mapProposal||mapWorking)return;mapWorking=true;$('map-proposal-apply').disabled=true;$('map-proposal-cancel').disabled=true;
 try{const result=await api('/api/maps/apply',{id:mapProposal.id});workspaceData=result.workspace.data;workspaceVersion=result.workspace.version;workspaceLoaded=true;workspacePending=false;workspaceBlocked=false;
  $('map-proposal-dialog').close();graphFormDirty=false;updateSessionStrip();await showGraph();graphNotice(result.already_applied?'This map was already saved.':'Suggested map saved. Open a topic to review and edit its ideas.');
 }catch{$('map-proposal-notice').textContent='Could not save: the conversation or workspace may have changed. Close and generate a fresh suggestion. Original notes are kept.';}
 finally{mapWorking=false;$('map-proposal-cancel').disabled=false;$('map-proposal-apply').disabled=false;}
};
$('graph-organize').onclick=()=>generateMap(selectedGraphSession()?.branch);
api('/api/maps/status').then(result=>{mapEnabled=result.enabled;if(mapEnabled){$('finish-session').textContent='Finish & organize ↗';document.querySelector('.talk-save-hint').textContent='Your words are saved as you go. Finish to review AI-suggested topics and source excerpts before saving.';if(document.body.dataset.mode==='demo')document.querySelector('.demo-mode-banner').textContent='VOICE DEMO · Typed input, fixed replies and silent audio · Map suggestions use a real model on request';}if(document.body.dataset.view==='workspace')renderGraph();}).catch(()=>{});
