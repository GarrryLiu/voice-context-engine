'use strict';
let topicNames={};
try{topicNames=JSON.parse(localStorage.getItem('voice-topic-names')||'{}')||{};}catch{}
if(typeof topicNames!=='object'||Array.isArray(topicNames))topicNames={};
function topicName(id){return typeof topicNames[id]==='string'?topicNames[id]:id==='main'?'我的工作区':id;}
let connectedAt=null,renderQueued=false,topicSignature='';
function renderProduct(){
 renderQueued=false;
 const branch=$('branch'),active=liveActive();
 $('topic-title').textContent=topicName(branch.value||'main');
 $('topic-count').textContent=String(branch.options.length);
 $('new-topic').disabled=!branch.value||$('fork').disabled||active||starting||switching;
 const signature=JSON.stringify([branch.value,branch.disabled,Array.from(branch.options,o=>[o.value,topicName(o.value)])]);
 if(signature!==topicSignature){topicSignature=signature;
 $('topics').replaceChildren(...Array.from(branch.options,option=>{
  const button=document.createElement('button');button.className='topic'+(option.selected?' active':'');
  button.disabled=branch.disabled;button.setAttribute('aria-current',option.selected?'page':'false');
  const icon=document.createElement('span');icon.className='topic-symbol';icon.textContent=option.value==='main'?'◈':'⑂';
  const label=document.createElement('span');label.className='topic-name';label.textContent=topicName(option.value);button.title=label.textContent;button.append(icon,label);
  button.onclick=()=>{if(branch.disabled||branch.value===option.value)return;branch.value=option.value;branch.dispatchEvent(new Event('change'));};return button;
 }));}
 const text=$('transcript').textContent.trim(),answer=$('answer').textContent.trim();
 document.body.classList.toggle('has-conversation',!!(text&&text!=='等待录音…')||!!(answer&&answer!=='开始一次对话。'));
 const listening=!!liveTracks&&liveReady;
 document.body.classList.toggle('is-live',active);$('live-indicator').hidden=!listening;
 if(listening&&connectedAt===null)connectedAt=Date.now();if(!listening)connectedAt=null;
 $('live-caption').textContent=sources.size?'正在回复 · 开口即可打断':busy?'正在整理你的想法':'正在倾听 · 想到什么就说什么';
}
function scheduleProduct(){if(!renderQueued){renderQueued=true;requestAnimationFrame(renderProduct);}}
const productObserver=new MutationObserver(scheduleProduct);
for(const id of ['branch','fork','status','transcript','answer','live','connection'])productObserver.observe($(id),{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
$('new-topic').onclick=()=>{if($('new-topic').disabled)return;$('topic-name').value='';$('topic-error').textContent='';$('topic-dialog').showModal();$('topic-name').focus();};
$('cancel-topic').onclick=()=>$('topic-dialog').close();
$('topic-form').onsubmit=async event=>{
 event.preventDefault();const name=$('topic-name').value.trim();if(!name)return;
 if(liveActive()||busy||switching){$('topic-error').textContent='请先结束当前对话，再创建思路。';return;}
 const id='thought-'+crypto.randomUUID().slice(0,12);switching=true;$('create-topic').disabled=true;buttons();scheduleProduct();
 try{
  await api('/api/control',{action:'fork',branch:id});await api('/api/control',{action:'switch',branch:id});
  topicNames[id]=name;try{localStorage.setItem('voice-topic-names',JSON.stringify(topicNames));}catch{}
  await refresh();$('topic-dialog').close();status('新的思路，准备好了');
 }catch{$('topic-error').textContent='创建未完成，请检查连接后重试。';}
 finally{switching=false;$('create-topic').disabled=false;buttons();scheduleProduct();}
};
$('help').onclick=()=>$('help-dialog').showModal();$('close-help').onclick=()=>$('help-dialog').close();
const productClock=setInterval(()=>{const seconds=connectedAt===null?0:Math.floor((Date.now()-connectedAt)/1000);$('session-time').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');},1000);
window.addEventListener('pagehide',()=>{clearInterval(productClock);productObserver.disconnect();});
renderProduct();
