import {runtime,live} from './client/runtime.js';
const {$,ui}=runtime;
const {liveActive}=live;
export let topicNames={};
try{topicNames=JSON.parse(localStorage.getItem('voice-topic-names')||'{}')||{};}catch{}
if(typeof topicNames!=='object'||Array.isArray(topicNames))topicNames={};
export function topicName(id){return typeof topicNames[id]==='string'?topicNames[id]:id==='main'?'Current conversation':'Conversation · '+id.slice(-6);}
let connectedAt=null,renderQueued=false;
export function renderProduct(){
 renderQueued=false;
 const active=liveActive();
 if(!['documents','workspace'].includes(document.body.dataset.view))$('topic-title').textContent='Talk';
 const text=$('transcript').textContent.trim(),answer=$('answer').textContent.trim();
 document.body.classList.toggle('has-conversation',!!(text&&text!==ui('等待录音…'))||!!(answer&&answer!==ui('开始一次对话。')));
 const listening=live.listening;
 document.body.classList.toggle('is-live',active);$('live-indicator').hidden=!listening;
 if(listening&&connectedAt===null)connectedAt=Date.now();if(!listening)connectedAt=null;
 $('live-caption').textContent=runtime.playing?'Speaking · interrupt anytime':runtime.busy?'Thinking it through':'Listening · say what’s on your mind';
}
function scheduleProduct(){if(!renderQueued){renderQueued=true;requestAnimationFrame(renderProduct);}}
const productObserver=new MutationObserver(scheduleProduct);
for(const id of ['branch','fork','status','transcript','answer','live','connection'])productObserver.observe($(id),{childList:true,subtree:true,attributes:true,attributeFilter:['disabled']});
$('help').onclick=()=>$('help-dialog').showModal();$('close-help').onclick=()=>$('help-dialog').close();
const productClock=setInterval(()=>{const seconds=connectedAt===null?0:Math.floor((Date.now()-connectedAt)/1000);$('session-time').textContent=String(Math.floor(seconds/60)).padStart(2,'0')+':'+String(seconds%60).padStart(2,'0');},1000);
window.addEventListener('pagehide',()=>{clearInterval(productClock);productObserver.disconnect();});
renderProduct();
