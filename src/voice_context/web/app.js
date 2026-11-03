'use strict';
const $=id=>document.getElementById(id);
function ui(text){return window.voiceUI?window.voiceUI(text):text;}
const token=document.querySelector('meta[name=voice-token]').content;
let session=localStorage.getItem('voice-session');
if(!session){session=crypto.randomUUID();localStorage.setItem('voice-session',session);}
const headers={'X-Voice-Token':token,'X-Voice-Session':session};
let recorder=null,tracks=null,timer=null,controller=null,context=null,sources=new Set(),cursor=0,generation=0,epoch=0,busy=false,receivedDone=false,failed=false,acks=0,ackFailed=false,starting=false,switching=false,ackController=new AbortController();
async function api(path,data,options={}){const r=await fetch(path,{headers:{...headers,'Content-Type':'application/json'},method:data?'POST':'GET',body:data?JSON.stringify(data):undefined,signal:options.signal});if(!r.ok)throw Error('服务请求失败 ('+r.status+')');return r.json();}
function status(s){$('status').textContent=ui(s);}
function buttons(){const recording=recorder&&recorder.state==='recording';$('record').disabled=busy||starting||switching||!!recording;$('stop').disabled=!recording;$('file').disabled=busy||switching||!!recording;$('fork').disabled=busy||switching||!!recording;$('branch').disabled=switching||starting||!!recording;$('interrupt').disabled=!busy&&!sources.size;}
function setBusy(value){busy=value;buttons();}
async function audioContext(){if(!context)context=new AudioContext({sampleRate:24000});await context.resume();return context;}
function clearPlayback(){generation++;acks=0;ackController.abort();ackController=new AbortController();for(const source of sources){source.onended=null;try{source.stop();}catch{}}sources.clear();cursor=context?context.currentTime:0;}
async function stopAll(){clearPlayback();if(controller)controller.abort();controller=null;try{const state=await api('/api/control',{action:'interrupt'});epoch=state.epoch;}catch{}setBusy(false);status('已停止');}
function finishIfReady(){if(receivedDone&&!sources.size&&!acks){setBusy(false);status(failed?'本轮未完成，可重新录音':ackFailed?'播放确认失败，恢复上下文可能缺少回复':'回复结束，可以继续说');}}
async function play(event,turnGeneration,started){
 if(turnGeneration!==generation||event.epoch!==epoch)return;
 const ctx=await audioContext();
 while(cursor-ctx.currentTime>1.5){await new Promise(r=>setTimeout(r,25));if(turnGeneration!==generation)return;}
 if(turnGeneration!==generation)return;
 const binary=atob(event.data),view=new DataView(new ArrayBuffer(binary.length));
 for(let i=0;i<binary.length;i++)view.setUint8(i,binary.charCodeAt(i));
 if(binary.length%2)throw Error('音频采样格式错误');
 const buffer=ctx.createBuffer(1,binary.length/2,event.sample_rate),samples=buffer.getChannelData(0);
 for(let i=0;i<samples.length;i++)samples[i]=view.getInt16(i*2,true)/32768;
 const node=ctx.createBufferSource();node.buffer=buffer;node.connect(ctx.destination);sources.add(node);
 node.onended=()=>{sources.delete(node);node.disconnect();if(turnGeneration===generation&&event.epoch===epoch){acks++;api('/api/ack',{epoch,request_id:event.request_id,sequence:event.sequence,offset:event.offset},{signal:ackController.signal}).catch(()=>{if(turnGeneration===generation)ackFailed=true;}).finally(()=>{if(turnGeneration===generation){acks--;finishIfReady();}});}};
 const when=Math.max(ctx.currentTime+.03,cursor);node.start(when);cursor=when+buffer.duration;
 if($('first').textContent==='—')$('first').textContent=((performance.now()-started)/1000).toFixed(2)+'s';
 status('正在播放');buttons();
}
async function send(blob,reply=null){
 if(busy)return;
 const before=generation;await audioContext();
 if(before!==generation||busy||(reply&&reply.epoch!==epoch))return;
 clearPlayback();const current=generation,started=performance.now();receivedDone=false;failed=false;ackFailed=false;setBusy(true);
 $('transcript').textContent='';$('answer').textContent='';for(const id of ['stt','first','total'])$(id).textContent='—';status(reply?'正在思考…':'正在上传录音…');
 if(reply)$('transcript').textContent=ui('已确认发言，正在生成回复…');
 controller=new AbortController();
 try{
  const r=await fetch(reply?'/api/reply':'/api/turn',{method:'POST',headers:{...headers,'Content-Type':reply?'application/json':blob.type||'audio/webm'},body:reply?JSON.stringify(reply):blob,signal:controller.signal});
  if(!r.ok)throw Error('录音请求失败 ('+r.status+')');
  const reader=r.body.getReader(),decoder=new TextDecoder();let pending='';
  async function handle(e){if(current!==generation)return;
   if(e.type==='status')status(e.text);
   if(e.type==='partial')$('transcript').textContent+=e.text;
   if(e.type==='transcript'){$('transcript').textContent=e.text;$('stt').textContent=e.stt_seconds.toFixed(2)+'s';status('正在思考…');}
   if(e.type==='reply')epoch=e.epoch;
   if(e.type==='text'&&e.epoch===epoch)$('answer').textContent+=e.text;
   if(e.type==='audio')await play(e,current,started);
   if(e.type==='generated')$('total').textContent=e.total_seconds.toFixed(2)+'s';
   if(e.type==='error'){failed=true;clearPlayback();setBusy(false);status(e.message);}
   if(e.type==='done'){receivedDone=true;finishIfReady();}
  }
  while(true){const {value,done}=await reader.read();if(done)break;pending+=decoder.decode(value,{stream:true});let index;while((index=pending.indexOf('\n'))>=0){const line=pending.slice(0,index);pending=pending.slice(index+1);if(line.trim())await handle(JSON.parse(line));}}
  if(!receivedDone&&current===generation)throw Error('连接中断，回复未完成');
 }catch(error){if(current===generation){clearPlayback();setBusy(false);status(error.name==='AbortError'?'已停止':error.message);}}
 finally{if(current===generation){controller=null;if(failed){setBusy(false);}else finishIfReady();}}
}
async function refresh(){const state=await api('/api/state');epoch=state.epoch;$('branch').replaceChildren(...state.branches.map(b=>{const o=document.createElement('option');o.value=b.id;o.textContent=b.id;o.selected=b.id===state.branch;return o;}));$('transcript').textContent=state.recent.length?state.recent[0].text:ui('等待录音…');const responses=state.responses||[];if(responses.length){const reply=responses[0].reply;$('answer').textContent=responses.filter(r=>r.reply===reply).sort((a,b)=>a.sequence-b.sequence).map(r=>r.text).join('');}else $('answer').textContent=ui('开始一次对话。');$('connection').textContent=ui('本地服务已连接');buttons();}
$('record').onclick=async()=>{if(document.querySelector('meta[name=voice-mode]')?.content==='demo'){status('Demo mode uses typed example input.');return;}if(busy||starting)return;starting=true;buttons();try{await audioContext();tracks=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true},video:false});const preferred=['audio/webm;codecs=opus','audio/mp4','audio/ogg;codecs=opus'].find(t=>MediaRecorder.isTypeSupported(t));recorder=new MediaRecorder(tracks,preferred?{mimeType:preferred}:undefined);const chunks=[];let size=0;recorder.ondataavailable=e=>{if(e.data.size){chunks.push(e.data);size+=e.data.size;if(size>2*1024*1024&&recorder.state==='recording')recorder.stop();}};recorder.onstop=()=>{clearTimeout(timer);tracks.getTracks().forEach(t=>t.stop());const blob=new Blob(chunks,{type:recorder.mimeType});buttons();if(size>2*1024*1024){status('录音超过 2MB，请缩短后重试');return;}send(blob).catch(e=>{setBusy(false);status(e.message);});};recorder.start(250);timer=setTimeout(()=>{if(recorder.state==='recording')recorder.stop();},20000);status('正在录音…');buttons();}catch(error){if(tracks)tracks.getTracks().forEach(t=>t.stop());status('无法使用麦克风：'+error.message);buttons();}finally{starting=false;buttons();}};
$('stop').onclick=()=>{if(recorder&&recorder.state==='recording')recorder.stop();};
$('interrupt').onclick=stopAll;
$('file').onchange=async e=>{if(document.querySelector('meta[name=voice-mode]')?.content==='demo'){status('Demo mode uses typed example input.');return;}const file=e.target.files[0];e.target.value='';if(!file)return;if(file.size>2*1024*1024){status('录音需小于 2MB');return;}try{await send(file);}catch(error){status(error.message);}};
$('branch').onchange=async()=>{if(switching)return;const branch=$('branch').value;switching=true;buttons();try{await stopAll();const s=await api('/api/control',{action:'switch',branch});epoch=s.epoch;$('answer').textContent='';await refresh();status('已切换到 '+branch);}catch(e){status(e.message);}finally{switching=false;buttons();}};
$('fork').onclick=async()=>{const branch=prompt('新分支名称（字母、数字、短横线）');if(!branch)return;try{await api('/api/control',{action:'fork',branch});await api('/api/control',{action:'switch',branch});await refresh();}catch(e){status(e.message);}};
window.addEventListener('pagehide',()=>{if(tracks)tracks.getTracks().forEach(t=>t.stop());clearPlayback();if(controller)controller.abort();});
refresh().catch(e=>{status(e.message);$('connection').textContent=ui('连接失败');});

// Explicit product-facing port. Capture/playback internals stay owned here.
window.voiceRuntime=Object.freeze({$,ui,headers,api,status,refresh,buttons,async submitExample(text){
 if(busy||starting||switching)return false;
 const before=generation,reply=await api('/api/demo/utterance',{text});
 if(before!==generation)return false;
 epoch=reply.epoch;await send(null,reply);return true;
},
 get busy(){return busy;},get starting(){return starting;},get switching(){return switching;},
 get playing(){return sources.size;},get recording(){return recorder?.state==='recording';},
 setSwitching(value){switching=!!value;buttons();}});

window.dispatchEvent(new Event('voiceline:runtime-ready'));
