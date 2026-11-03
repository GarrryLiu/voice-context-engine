// Wait on explicit registration; module/defer fetch timing must not affect startup.
if(!window.voiceRuntime||!window.voiceLive)await new Promise(resolve=>{
 const ready=()=>{if(window.voiceRuntime&&window.voiceLive){window.removeEventListener('voiceline:runtime-ready',ready);resolve();}};
 window.addEventListener('voiceline:runtime-ready',ready);ready();
});
// Product modules consume these ports, not mutable voice-engine globals.
export const runtime=window.voiceRuntime;
export const live=window.voiceLive;
if(!runtime||!live)throw Error('Voice runtime ports must initialize before product modules.');
