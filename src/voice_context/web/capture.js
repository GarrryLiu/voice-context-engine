/* Audio-thread capture. Linear resampling to 24k PCM, bounded pre-roll and VAD. */
class VoiceCapture extends AudioWorkletProcessor {
 constructor(){super();this.outstanding=0;this.halted=false;this.port.onmessage=e=>{if(e.data.type==='ack')this.outstanding=Math.max(0,this.outstanding-1);};this.input=[];this.position=0;this.frame=[];this.pre=[];this.voiced=0;this.quiet=0;this.active=false;this.frames=0;}
 emit(){
  const frame=this.frame;this.frame=[];
  const rms=Math.sqrt(frame.reduce((sum,x)=>sum+x*x,0)/frame.length);
  // Three 20ms voiced frames start a turn; 600ms silence commits it.
  this.voiced=rms>=.018?this.voiced+1:0;
  if(!this.active){this.pre.push(frame);if(this.pre.length>10)this.pre.shift();if(this.voiced<3)return;
   this.active=true;this.frames=0;this.quiet=0;this.port.postMessage({type:'start'});
   for(const f of this.pre)this.send(f);this.pre=[];
  }else this.send(frame);
  this.quiet=rms<.012?this.quiet+1:0;
  if(this.quiet>=30||this.frames>=1000){this.port.postMessage({type:'commit'});this.active=false;this.voiced=0;this.pre=[];}
 }
 send(frame){if(this.halted)return;if(this.outstanding>=10){this.halted=true;this.port.postMessage({type:'overflow'});return;}this.outstanding++;this.frames++;const pcm=new ArrayBuffer(frame.length*2),view=new DataView(pcm);for(let i=0;i<frame.length;i++)view.setInt16(i*2,Math.round(Math.max(-1,Math.min(1,frame[i]))*32767),true);this.port.postMessage({type:'pcm',pcm},[pcm]);}
 process(inputs){
  if(this.halted)return true;
  const channel=inputs[0]&&inputs[0][0];if(!channel)return true;
  for(const x of channel)this.input.push(x);
  const step=sampleRate/24000;
  while(this.position+1<this.input.length){const index=Math.floor(this.position),fraction=this.position-index;this.frame.push(this.input[index]*(1-fraction)+this.input[index+1]*fraction);this.position+=step;if(this.frame.length===480)this.emit();}
  const consumed=Math.floor(this.position);this.input.splice(0,consumed);this.position-=consumed;
  return true;
 }
}
registerProcessor('voice-capture',VoiceCapture);
