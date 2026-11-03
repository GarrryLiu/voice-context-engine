import './client/demo.js';
import './product.js';
import './documents.js';
import './workspace.js';
import {navigate} from './client/navigation.js';
const hash=location.hash;
let view='thoughts',id=null;
if(hash.startsWith('#documents')){view='documents';if(hash.startsWith('#documents/'))id=decodeURIComponent(hash.slice(11));}
if(hash.startsWith('#workspace')){view='workspace';if(hash.startsWith('#workspace/'))id=decodeURIComponent(hash.slice(11));}
navigate(view,id).catch(()=>window.voiceRuntime.status('Could not open this view. Check the local service.'));
