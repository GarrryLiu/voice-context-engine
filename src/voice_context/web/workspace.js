'use strict';
let workspaceData={categories:['Inbox'],sessions:[],links:[]},workspaceVersion=0,workspaceLoaded=false,workspaceLoading=null,workspaceSaving=false,workspacePending=false,workspaceBlocked=false,workspaceSavePromise=null;
let graphSession=null,graphSelected=null,graphCategory='',graphListMode=false,graphScale=1,graphPan={x:0,y:0},graphDrag=null,graphFormDirty=false,graphNameAction='session';
let activeProductSession=null;
try{activeProductSession=localStorage.getItem('voiceline-active-product-session');}catch{}
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
 workspaceSaving=true;
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
function selectedGraphItem(){return graphItems().find(n=>n.id===graphSelected);}
function updateSessionStrip(){const item=workspaceData.sessions.find(s=>s.id===activeProductSession);$('active-session-name').textContent=item?item.title:'A little room to think.';}
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
 const current=selectedGraphSession();
 $('graph-title').textContent=current?current.title:'Your thinking, connected.';
 $('graph-eyebrow').textContent=current?(current.demo?'EXAMPLE SESSION · '+current.category.toUpperCase():current.category.toUpperCase()+' / SESSION'):'CONNECTED THINKING';
 $('graph-subtitle').textContent=current?'Follow an idea. Find a connection. Pick up where you left off.':'Every conversation is a starting point. See where it takes you.';
 $('graph-back').hidden=!current;$('graph-session-actions').hidden=!current;$('graph-demo').hidden=workspaceData.sessions.some(s=>s.demo);
 $('graph-search').placeholder=current?'Find a thought…':'Find a session…';
 $('graph-scope-label').textContent=current?'Ideas, questions & decisions':'Sessions connected by you';
 $('graph-categories').replaceChildren(...['',...workspaceData.categories].map(category=>{
  const button=graphEl('button','category-item'+(graphCategory===category&&!current?' selected':''));
  button.append(graphEl('i','category-dot'),graphEl('span','',category||'All sessions'),graphEl('span','',String(workspaceData.sessions.filter(s=>!category||s.category===category).length)));
  button.onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphCategory=category;graphSession=null;graphSelected=null;$('graph-search').value='';graphReset();renderGraph();graphHash();};return button;
 }));
 $('graph-session-count').textContent=workspaceData.sessions.length;
 $('graph-session-list').replaceChildren(...workspaceData.sessions.filter(s=>!graphCategory||s.category===graphCategory).map(item=>{const button=graphEl('button','session-item');button.append(graphEl('span','','⑂'),graphEl('span','',item.title));button.onclick=()=>openSessionMap(item.id);return button;}));
 const items=graphItems();$('graph-nodes').replaceChildren(...items.map(item=>{
  const button=graphEl('button','graph-node'+(item.id===graphSelected?' selected':''));button.dataset.id=item.id;button.dataset.kind=item.kind||'session';button.style.left=item.x+'px';button.style.top=item.y+'px';button.setAttribute('aria-label',(current?'Select thought: ':'Select session: ')+item.title);
  const type=graphEl('span','node-type',current?graphTypes[item.kind]:item.category);if(!current&&item.demo)type.append(graphEl('span','demo-chip','EXAMPLE'));
  button.append(type,graphEl('strong','',item.title));
  if(current)button.append(graphEl('span','node-preview',item.content||'A little room for your next idea.'));
  else button.append(graphEl('small','',item.nodes.length+' thoughts · '+item.edges.length+' connections'));
  button.onclick=()=>{if(graphDrag?.moved)return;selectGraphItem(item.id);};button.ondblclick=()=>{if(!current)openSessionMap(item.id);};
  button.onpointerdown=event=>{if(event.button!==0)return;event.stopPropagation();graphDrag={id:item.id,clientX:event.clientX,clientY:event.clientY,x:item.x,y:item.y,moved:false};button.setPointerCapture(event.pointerId);};
  button.onpointermove=event=>{if(graphDrag?.id!==item.id)return;const dx=(event.clientX-graphDrag.clientX)/graphScale,dy=(event.clientY-graphDrag.clientY)/graphScale;if(Math.abs(dx)+Math.abs(dy)>4)graphDrag.moved=true;if(!graphDrag.moved)return;item.x=Math.max(0,Math.min(1700,graphDrag.x+dx));item.y=Math.max(0,Math.min(1200,graphDrag.y+dy));button.style.left=item.x+'px';button.style.top=item.y+'px';drawGraphEdges();};
  button.onpointerup=()=>{if(graphDrag?.id!==item.id)return;if(graphDrag.moved){persistWorkspace();setTimeout(()=>{graphDrag=null;},0);}else graphDrag=null;};
  button.onpointercancel=()=>{if(graphDrag?.moved)persistWorkspace();graphDrag=null;};return button;
 }));
 $('graph-clusters').replaceChildren();drawGraphEdges();
 $('graph-empty').hidden=!!items.length;$('graph-empty').querySelector('h2').textContent=$('graph-search').value?'No matching thoughts.':'A thought starts with your voice.';
 $('graph-list').replaceChildren(...items.map(item=>{const button=graphEl('button','graph-row');button.append(graphEl('strong','',item.title),graphEl('small','',current?graphTypes[item.kind]:item.category));button.onclick=()=>current?selectGraphItem(item.id):openSessionMap(item.id);return button;}));
 $('graph-canvas').hidden=graphListMode;$('graph-list').hidden=!graphListMode;
 $('graph-map-toggle').classList.toggle('selected',!graphListMode);$('graph-list-toggle').classList.toggle('selected',graphListMode);
 $('graph-counts').textContent=items.length+(current?' thoughts':' sessions')+' · '+graphLinks().filter(e=>e.every(id=>items.some(n=>n.id===id))).length+' connections';
 renderGraphInspector();
}
function selectGraphItem(id){if(graphSelected!==id&&!graphCanLeave())return;graphFormDirty=false;graphSelected=id;renderGraph();}
function renderGraphInspector(){
 const item=selectedGraphItem(),current=selectedGraphSession();$('graph-inspector-empty').hidden=!!item;$('graph-editor').hidden=!item;if(!item)return;
 $('graph-selection-kind').textContent=current?(graphTypes[item.kind]||'Thought').toUpperCase():'SESSION';$('graph-edit-title').value=item.title;
 $('graph-category-label').hidden=!!current;$('graph-kind-label').hidden=!current||item.kind==='voice';$('graph-content-label').hidden=!current;
 $('graph-edit-category').replaceChildren(...workspaceData.categories.map(c=>new Option(c,c)));$('graph-edit-category').value=item.category||current?.category;
 $('graph-edit-kind').value=item.kind||'idea';$('graph-edit-content').value=item.content||'';
 $('graph-open-session').hidden=!!current;$('graph-source').hidden=!item.source;
 $('graph-provenance').textContent=item.source?'Edited notes are separate from the original source.':!current&&item.demo?'Example content for exploring the product. No model calls were made.':current?'Map edits organize this session. Voice resumes its spoken branch context; these edits are not added to model memory.':'A product session can span multiple voice conversations.';
 const others=graphItems().filter(n=>n.id!==item.id);$('graph-connect-target').replaceChildren(...others.map(n=>new Option(n.title,n.id)));$('graph-connect').disabled=!others.length;
 $('graph-connections').replaceChildren(...graphLinks().filter(e=>e.includes(item.id)).map(edge=>{const other=graphItems().find(n=>n.id===edge.find(id=>id!==item.id));const b=graphEl('button','','↔ '+(other?.title||'Hidden node')+' ×');b.type='button';b.title='Remove connection';b.onclick=()=>{const links=graphLinks();links.splice(links.indexOf(edge),1);persistWorkspace();renderGraph();};return b;}));
}
function graphHash(){history.replaceState(null,'','#workspace'+(graphSession?'/'+encodeURIComponent(graphSession):''));}
async function showGraph(id=null){
 if(!await canLeaveDocument()||!graphCanLeave())return;
 if(liveActive())await endLive('Conversation paused.');else if(busy)await stopAll();
 try{await loadWorkspace();graphFormDirty=false;document.body.dataset.view='workspace';$('documents-workspace').hidden=true;$('graph-workspace').hidden=false;for(const id of ['nav-thoughts','nav-documents'])$(id).classList.remove('selected');$('nav-workspace').classList.add('selected');graphSession=workspaceData.sessions.some(s=>s.id===id)?id:null;graphSelected=null;$('topic-title').textContent='Workspace';$('graph-search').value='';graphReset();renderGraph();graphHash();}
 catch(error){status('Could not load the workspace. Check the local server.');}
}
function openSessionMap(id){if(!graphCanLeave())return;graphFormDirty=false;graphSession=id;graphSelected=null;$('graph-search').value='';graphReset();renderGraph();graphHash();}
function graphNameDialog(action){if(!graphCanLeave())return;graphNameAction=action;$('graph-name-heading').textContent=action==='category'?'Make room for a new category.':action==='node'?'Follow a new thought.':'What’s on your mind?';$('graph-name-eyebrow').textContent='A NEW '+action.toUpperCase();$('graph-name').value='';$('graph-name-dialog').showModal();$('graph-name').focus();}
$('graph-name-cancel').onclick=()=>$('graph-name-dialog').close();
$('graph-name-form').onsubmit=async event=>{
 event.preventDefault();const title=$('graph-name').value.trim();if(!title)return;
 try{await loadWorkspace();if(graphNameAction==='category'){if(title.length>60||workspaceData.categories.includes(title))throw Error('Choose a unique category name, up to 60 characters.');workspaceData.categories.push(title);graphCategory=title;}
 else if(graphNameAction==='node'){const s=selectedGraphSession();if(!s)return;const id=crypto.randomUUID();s.nodes.push({id,title,content:'',kind:'idea',...graphPlace(s.nodes),source:null});if(graphSelected)s.edges.push([graphSelected,id]);graphSelected=id;graphFormDirty=false;}
 else{const id=crypto.randomUUID();workspaceData.sessions.push({id,title,category:graphCategory||'Inbox',branch:null,demo:false,...graphPlace(workspaceData.sessions),nodes:[],edges:[]});graphSession=id;graphSelected=null;}
 $('graph-name-dialog').close();await persistWorkspace();renderGraph();graphReset();graphHash();}
 catch(error){graphNotice(error.message,true);}
};
$('graph-editor').oninput=()=>{graphFormDirty=true;};
$('graph-editor').onsubmit=event=>{event.preventDefault();const item=selectedGraphItem();if(!item)return;item.title=$('graph-edit-title').value.trim()||item.title;if(graphSession){item.content=$('graph-edit-content').value;if(item.kind!=='voice')item.kind=$('graph-edit-kind').value;}else item.category=$('graph-edit-category').value;graphFormDirty=false;persistWorkspace();renderGraph();};
$('graph-connect').onclick=()=>{const target=$('graph-connect-target').value;if(!target||!graphSelected||!graphCanLeave())return;const links=graphLinks();if(!links.some(e=>e.includes(target)&&e.includes(graphSelected)))links.push([graphSelected,target]);graphFormDirty=false;persistWorkspace();renderGraph();};
$('graph-close-selection').onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphSelected=null;renderGraph();};
$('graph-open-session').onclick=()=>openSessionMap(graphSelected);
const graphDelete=graphEl('button','','Remove from map');graphDelete.type='button';$('graph-editor').append(graphDelete);
graphDelete.onclick=()=>{const item=selectedGraphItem();if(!item||!window.confirm('Remove this '+(graphSession?'node':'session')+' from the map? Original voice notes and documents will be kept.'))return;
 if(graphSession){const s=selectedGraphSession();s.nodes=s.nodes.filter(n=>n.id!==item.id);s.edges=s.edges.filter(e=>!e.includes(item.id));}
 else{workspaceData.sessions=workspaceData.sessions.filter(s=>s.id!==item.id);workspaceData.links=workspaceData.links.filter(e=>!e.includes(item.id));if(activeProductSession===item.id){activeProductSession=null;try{localStorage.removeItem('voiceline-active-product-session');}catch{}}}
 graphFormDirty=false;graphSelected=null;persistWorkspace();renderGraph();};
$('graph-source').onclick=()=>{const source=selectedGraphItem()?.source;if(source&&graphCanLeave()){graphFormDirty=false;showDocuments(source);}};
$('graph-back').onclick=()=>showGraph();$('nav-workspace').onclick=()=>showGraph();
$('graph-new-session').onclick=()=>graphNameDialog('session');$('graph-empty-new').onclick=()=>graphNameDialog(graphSession?'node':'session');$('graph-add-category').onclick=()=>graphNameDialog('category');$('graph-add-node').onclick=()=>graphNameDialog('node');
$('graph-search').oninput=()=>{if(!graphCanLeave()){$('graph-search').value='';return;}graphFormDirty=false;graphSelected=null;renderGraph();};
$('graph-map-toggle').onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphListMode=false;renderGraph();};$('graph-list-toggle').onclick=()=>{if(!graphCanLeave())return;graphFormDirty=false;graphListMode=true;renderGraph();};
function zoomGraph(factor,cx,cy){const old=graphScale;graphScale=Math.min(1.8,Math.max(.35,graphScale*factor));graphPan.x=cx-(cx-graphPan.x)*graphScale/old;graphPan.y=cy-(cy-graphPan.y)*graphScale/old;graphTransform();}
$('graph-zoom-in').onclick=()=>zoomGraph(1.2,200,180);$('graph-zoom-out').onclick=()=>zoomGraph(1/1.2,200,180);$('graph-fit').onclick=graphReset;
$('graph-canvas').addEventListener('wheel',event=>{event.preventDefault();const rect=$('graph-canvas').getBoundingClientRect();zoomGraph(event.deltaY<0?1.08:1/1.08,event.clientX-rect.left,event.clientY-rect.top);},{passive:false});
$('graph-canvas').onpointerdown=event=>{if(event.target.closest('button')||event.button!==0)return;graphDrag={pan:true,clientX:event.clientX,clientY:event.clientY,x:graphPan.x,y:graphPan.y};$('graph-canvas').setPointerCapture(event.pointerId);};
$('graph-canvas').onpointermove=event=>{if(!graphDrag?.pan)return;graphPan={x:graphDrag.x+event.clientX-graphDrag.clientX,y:graphDrag.y+event.clientY-graphDrag.clientY};graphTransform();};
$('graph-canvas').onpointerup=()=>{if(graphDrag?.pan)graphDrag=null;};
async function resumeProductSession(){
 if(!graphCanLeave()||workspaceBlocked)return;
 const item=selectedGraphSession();if(!item)return;
 try{if(!$('branch').options.length)await refresh();if(!item.branch){const branch='session-'+crypto.randomUUID().slice(0,16);await api('/api/control',{action:'new_branch',branch});item.branch=branch;topicNames[branch]=item.title;try{localStorage.setItem('voice-topic-names',JSON.stringify(topicNames));}catch{}if(!await persistWorkspace())throw Error('workspace unsaved');}
 await api('/api/control',{action:'switch',branch:item.branch});await refresh();activeProductSession=item.id;try{localStorage.setItem('voiceline-active-product-session',item.id);}catch{}graphFormDirty=false;await showThoughts();updateSessionStrip();status('Session ready. Start a conversation to continue.');}
 catch{graphNotice('Could not resume this session. Your map is kept; check the local server.',true);}
}
$('graph-continue').onclick=resumeProductSession;
async function finishProductSession(){
 try{if(liveActive())await endLive('Session ended.');else if(busy)await stopAll();await loadWorkspace();await refresh();
 const branch=$('branch').value;let item=workspaceData.sessions.find(s=>s.id===activeProductSession&&s.branch===branch)||workspaceData.sessions.find(s=>s.branch===branch);
 if(!item){item={id:crypto.randomUUID(),title:topicName(branch)==='My workspace'?'An untitled thought':topicName(branch),category:'Inbox',branch,demo:false,...graphPlace(workspaceData.sessions),nodes:[],edges:[]};workspaceData.sessions.push(item);}
 let offset=0;
 do{const result=await documentAPI('?'+new URLSearchParams({branch,status:'active',offset:String(offset)}));for(const doc of result.documents){if(item.nodes.some(n=>n.source===doc.id))continue;const full=await documentAPI('/item?id='+encodeURIComponent(doc.id));const id=crypto.randomUUID(),n=item.nodes.length;item.nodes.push({id,title:doc.title,content:full.content,kind:doc.kind==='voice'?'voice':'document',...graphPlace(item.nodes),source:doc.id});/* No inferred links: the user decides how ideas connect. */}offset=result.next_offset;}while(offset!==null);
 if(!await persistWorkspace())throw Error('workspace unsaved');activeProductSession=item.id;try{localStorage.setItem('voiceline-active-product-session',item.id);}catch{}await showGraph(item.id);graphNotice('Session saved. Voice notes are kept with their original sources. Add connections to organize your thinking.');}
 catch{status('Could not organize the session. Your original voice notes are still saved in Documents.');}
}
$('finish-session').onclick=finishProductSession;
$('graph-demo').onclick=async()=>{
 if(!graphCanLeave()||workspaceData.sessions.some(s=>s.demo))return;graphFormDirty=false;
 const node=(id,title,content,kind,x,y)=>({id,title,content,kind,x,y,source:null});
 const prefix=crypto.randomUUID().slice(0,8);const example=(suffix,title,category,x,y,nodes,edges)=>({id:prefix+suffix,title,category,branch:null,demo:true,x,y,nodes,edges});
 for(const c of ['Product','Research','Personal'])if(!workspaceData.categories.includes(c))workspaceData.categories.push(c);
 const sessions=[example('a','A voice-first thinking space','Product',40,110,[node('a','Thinking out loud','A place to explore ideas before they become a finished document. Voice is the starting point, not the final format.','idea',35,140),node('b','Keep the thread','A session can be resumed across days. Ideas keep their sources and their connections.','idea',275,35),node('c','Who is this for?','Start with people who think by talking: researchers, builders, and anyone working through an unfinished idea.','question',275,240),node('d','Start with one clear loop','Speak → organize → revisit → continue. Make this feel natural before adding more features.','decision',515,140)],[['a','b'],['a','c'],['b','d'],['c','d']]),example('b','The cost of a good conversation','Research',320,35,[node('a','Stage-aware orchestration','Route transcription, reasoning, and synthesis independently. Measure latency and cost separately.','idea',40,100),node('b','What should trigger escalation?','Can uncertainty, task complexity, and available context guide model selection?','question',280,35),node('c','A fair comparison','Compare routing policies on the same recorded interactions, with quality checks and cancellation scenarios.','document',280,230)],[['a','b'],['a','c']]),example('c','A calmer morning routine','Personal',320,255,[node('a','Leave space to think','A short walk and a voice note before opening the inbox.','idea',45,140),node('b','Try it for a week','Notice whether thoughts are easier to return to later.','decision',290,140)],[['a','b']]),example('d','From conversation to knowledge','Product',595,155,[node('a','Not every sentence is a node','Meaningful topics, decisions, and questions deserve a place on the map.','idea',45,130),node('b','Make structure editable','Suggested connections should stay suggestions until the user chooses them.','decision',290,130)],[['a','b']])];
 const startY=workspaceData.sessions.length?Math.max(...workspaceData.sessions.map(s=>s.y))+190:0;for(const s of sessions){s.y+=startY;}
 workspaceData.sessions.push(...sessions);workspaceData.links.push([sessions[0].id,sessions[1].id],[sessions[0].id,sessions[2].id],[sessions[1].id,sessions[3].id],[sessions[2].id,sessions[3].id]);const saved=await persistWorkspace();graphSession=null;graphCategory='';graphReset();renderGraph();if(saved)graphNotice('Example workspace · sample content only. Your real sessions are kept separately.');
};
// Keep the existing document editor available as a secondary source library.
const originalShowThoughts=showThoughts;showThoughts=async function(){if(!graphCanLeave())return false;const ok=await originalShowThoughts();if(ok){graphFormDirty=false;$('graph-workspace').hidden=true;$('nav-workspace').classList.remove('selected');}return ok;};
const originalShowDocuments=showDocuments;showDocuments=async function(id=null){if(!graphCanLeave())return;await originalShowDocuments(id);if(document.body.dataset.view==='documents'){graphFormDirty=false;$('graph-workspace').hidden=true;$('nav-workspace').classList.remove('selected');}};
$('nav-thoughts').onclick=()=>showThoughts();$('nav-documents').onclick=()=>showDocuments();
window.addEventListener('beforeunload',event=>{if(graphFormDirty||workspacePending||workspaceSaving){event.preventDefault();event.returnValue='';}});
const graphTools=graphEl('div','graph-data-tools');
for(const [label,fn] of [['Export map',()=>{const url=URL.createObjectURL(new Blob([JSON.stringify(workspaceData,null,2)],{type:'application/json'}));const a=graphEl('a');a.href=url;a.download='voiceline-workspace.json';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}],['Reload',async()=>{if(!graphCanLeave()||((workspacePending||workspaceBlocked)&&!window.confirm('Reload the saved workspace? Export first to keep unsaved map changes.')))return;workspaceLoaded=false;try{await loadWorkspace();workspacePending=false;workspaceBlocked=false;graphSelected=null;graphFormDirty=false;if(!selectedGraphSession())graphSession=null;renderGraph();graphNotice('Loaded the latest saved workspace.');}catch{graphNotice('Could not reload the workspace.',true);}}]]){const b=graphEl('button','',label);b.onclick=fn;graphTools.append(b);}
document.querySelector('.graph-heading-actions').append(graphTools);
loadWorkspace().catch(()=>{});
if(location.hash.startsWith('#workspace'))showGraph(location.hash.startsWith('#workspace/')?decodeURIComponent(location.hash.slice(11)):null);

const graphResizeObserver=new ResizeObserver(()=>{if(document.body.dataset.view==='workspace'){graphReset();drawGraphEdges();}});graphResizeObserver.observe($('graph-canvas'));window.addEventListener('pagehide',()=>graphResizeObserver.disconnect());
