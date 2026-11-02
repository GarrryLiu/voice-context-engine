'use strict';
let liveSocket=null,liveTracks=null,liveNode=null,liveSource=null,liveReady=false,liveStarting=false,liveClosed=false;
const liveActive=()=>!!liveSocket||liveStarting;
function liveButtons(){const active=liveActive();$('live').disabled=liveStarting;$('live').textContent=active?'结束连续对话':'开始连续对话';$('record').disabled=active||busy||starting||switching;$('file').disabled=active||busy;$('branch').disabled=active||switching;$('fork').disabled=active||busy;}
async function endLive(message='连续对话已结束'){
 liveClosed=true;liveReady=false;liveStarting=false;
 if(liveNode){liveNode.port.onmessage=null;liveNode.disconnect();liveNode=null;}
 if(liveSource){liveSource.disconnect();liveSource=null;}
 if(liveTracks){liveTracks.getTracks().forEach(t=>t.stop());liveTracks=null;}
 const socket=liveSocket;liveSocket=null;if(socket)socket.close();
 await stopAll();status(message);liveButtons();
}
$('live').onclick=async()=>{
 if(liveActive()){await endLive();return;}
 if(busy||starting||switching)return;
 liveStarting=true;liveClosed=false;liveButtons();status('正在连接实时转写…');
 try{
  const ctx=await audioContext();await ctx.audioWorklet.addModule('/capture.js');
  const socket=new WebSocket(location.origin.replace(/^http/,'ws')+'/api/live');liveSocket=socket;
  const timeout=setTimeout(()=>{if(!liveReady&&liveSocket===socket)endLive('实时转写连接超时，请重试');},15000);
  socket.onopen=()=>socket.send(JSON.stringify({token,session}));
  socket.onerror=()=>{if(liveSocket===socket)endLive('实时转写连接失败，请重试');};
  socket.onclose=()=>{clearTimeout(timeout);if(liveSocket===socket)endLive('实时转写连接已结束，请重新开始');};
  socket.onmessage=async message=>{
   if(liveSocket!==socket)return;
   try{
    const e=JSON.parse(message.data);
    if(e.type==='ready'){
     if(liveReady)return;liveReady=true;clearTimeout(timeout);
     const capture=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true,autoGainControl:true},video:false});
     if(liveSocket!==socket||liveClosed){capture.getTracks().forEach(t=>t.stop());return;}
     liveTracks=capture;liveStarting=false;
     liveSource=ctx.createMediaStreamSource(liveTracks);liveNode=new AudioWorkletNode(ctx,'voice-capture');
     liveNode.port.onmessage=event=>{
      if(liveSocket!==socket||!liveReady)return;
      if(socket.readyState!==WebSocket.OPEN||socket.bufferedAmount>65536){endLive('上传积压，已停止麦克风，请重试');return;}
      const frame=event.data;
      if(frame.type==='overflow'){endLive('采集积压，已停止麦克风，请重试');return;}
      if(frame.type==='start'){
       // Stop local playback before any server/network acknowledgement.
       clearPlayback();if(controller)controller.abort();controller=null;setBusy(false);
       $('transcript').textContent='';$('answer').textContent='';status('正在听…');
      }
      if(frame.type==='pcm'){socket.send(frame.pcm);liveNode.port.postMessage({type:'ack'});}
      else socket.send(JSON.stringify({type:frame.type}));
     };
     liveSource.connect(liveNode);liveNode.connect(ctx.destination);status('连续对话中，可以开始说话');liveButtons();
    }
    if(e.type==='speech_started')epoch=e.epoch;
    if(e.type==='partial'&&e.epoch===epoch)$('transcript').textContent+=e.text;
    if(e.type==='transcript'){
     epoch=e.epoch;$('transcript').textContent=e.text;
     await send(null,{transcript_id:e.transcript_id,epoch:e.epoch});liveButtons();
    }
    if(e.type==='error')await endLive(e.message);
   }catch{await endLive('实时对话未完成，请重试');}
  };
 }catch{await endLive('无法启动连续对话，请检查麦克风权限和连接');}
};
// Shared manual-turn state changes must keep capture controls consistent.
const liveObserver=new MutationObserver(liveButtons);liveObserver.observe($('status'),{childList:true});
window.addEventListener('pagehide',()=>{liveClosed=true;if(liveTracks)liveTracks.getTracks().forEach(t=>t.stop());if(liveSocket)liveSocket.close();});
