import './client/demo.js';
import './product.js';
import './documents.js';
import './workspace.js';
import {navigate} from './client/navigation.js';
const hash=location.hash;
let view='thoughts',id=null;
const documentsPrefix=hash.startsWith('#library/documents')?'#library/documents':hash.startsWith('#documents')?'#documents':null;
if(documentsPrefix){view='documents';if(hash.startsWith(documentsPrefix+'/'))id=decodeURIComponent(hash.slice(documentsPrefix.length+1));}
else{
 const libraryPrefix=hash.startsWith('#library')?'#library':hash.startsWith('#workspace')?'#workspace':null;
 if(libraryPrefix){view='workspace';if(hash.startsWith(libraryPrefix+'/'))id=decodeURIComponent(hash.slice(libraryPrefix.length+1));}
}
navigate(view,id).catch(()=>window.voiceRuntime.status('Could not open this view. Check the local service.'));
