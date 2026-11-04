import {runtime,live} from './runtime.js';
const views=new Map(),guards=new Set(),listeners=new Set();
let navigating=false;
export function registerView(name,enter){if(views.has(name))throw Error('Duplicate view');views.set(name,enter);}
export function addNavigationGuard(guard){guards.add(guard);return ()=>guards.delete(guard);}
export function onNavigation(listener){listeners.add(listener);return ()=>listeners.delete(listener);}
export async function navigate(name,id=null){
 if(navigating)return false;
 if(runtime.starting||runtime.switching||runtime.recording){runtime.status('Send your recording before changing views.');return false;}
 navigating=true;
 try{
  for(const guard of guards)if(!await guard())return false;
  if(name!=='thoughts'){if(live.liveActive())await live.endLive('Conversation paused.');else if(runtime.busy)await live.stopAll();}
  const enter=views.get(name);if(!enter)throw Error('Unknown view');
  await enter(id);
  document.body.dataset.view=name;
  for(const [view,panel] of [['documents','documents-workspace'],['workspace','graph-workspace']])document.getElementById(panel).hidden=view!==name;
  const library=name==='workspace'||name==='documents';
  document.getElementById('nav-thoughts').classList.toggle('selected',name==='thoughts');
  document.getElementById('nav-workspace').classList.toggle('selected',library);
  document.getElementById('library-sections').hidden=!library;
  document.getElementById('library-records').classList.toggle('selected',name==='workspace');
  document.getElementById('nav-documents').classList.toggle('selected',name==='documents');
  for(const listener of listeners)listener(name);
  return true;
 }catch{runtime.status('Could not change views. Check the local service and try again.');return false;}finally{navigating=false;}
}
