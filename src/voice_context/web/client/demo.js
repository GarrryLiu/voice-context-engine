import {runtime} from './runtime.js';
if(document.querySelector('meta[name=voice-mode]')?.content==='demo'){
 document.body.dataset.mode='demo';
 const banner=document.createElement('div');banner.className='demo-mode-banner';banner.textContent='DEMO MODE · Typed example input, simulated replies and silent audio · No model calls';
 document.querySelector('.topbar').after(banner);
 const form=document.createElement('form');form.className='demo-input';
 const input=document.createElement('textarea');input.id='demo-text';input.required=true;input.maxLength=32000;input.placeholder='Type a thought to simulate a confirmed voice turn…';input.setAttribute('aria-label','Demo thought');
 const button=document.createElement('button');button.textContent='Send example ↗';button.type='submit';button.id='demo-send';form.append(input,button);document.querySelector('.composer').append(form);
 form.onsubmit=async event=>{event.preventDefault();if(!input.value.trim()||runtime.busy)return;button.disabled=true;
  try{const accepted=await runtime.submitExample(input.value.trim());if(accepted)input.value='';}
  catch{runtime.status('Could not complete the demo turn. Your confirmed text may already be saved.');}
  finally{button.disabled=false;}
 };
}
