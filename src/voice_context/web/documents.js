'use strict';
let currentDocument=null,documentDirty=false,documentWriting=false,documentKind='',documentRows=[],documentNext=null;
let documentListRequest=0,documentEditorRequest=0,documentSearchTimer=null,leavePromise=null;
const kindLabels={voice:'Voice note',draft:'Draft',reference:'Reference',note:'Document'};
function documentNotice(text,error=false){$('document-notice').textContent=text;$('document-notice').classList.toggle('error',error);}
async function documentAPI(path,data){
 const response=await fetch('/api/documents'+path,{method:data?'POST':'GET',headers:{...headers,'Content-Type':'application/json'},body:data?JSON.stringify(data):undefined,signal:AbortSignal.timeout(15000)});
 if(!response.ok){const error=Error(response.status===409?'A newer version exists. Your edits are kept. Export them or reload the document.':response.status===404?'This document or version is unavailable.':'Could not complete that change. Check your connection, document size, and selected thought.');error.conflict=response.status===409;throw error;}
 return response.json();
}
function documentFields(){return {title:$('document-title').value.trim()||'Untitled document',content:$('document-content').value,branch:$('document-branch').value,collection:$('document-collection').value.trim()};}
function documentEditorState(){
 $('new-document').disabled=documentWriting;$('import-document').disabled=documentWriting;
 if(!currentDocument)return;
 const fields=documentFields();documentDirty=Object.entries(fields).some(([key,value])=>value!==currentDocument[key]);
 const trashed=currentDocument.status==='trash';
 $('document-save-state').textContent='v'+currentDocument.version+' · '+(documentDirty?'Unsaved changes':'Saved');
 $('save-document').disabled=documentWriting||!documentDirty||trashed;
 for(const id of ['document-title','document-content','document-collection'])$(id).readOnly=trashed||documentWriting;
 $('document-branch').disabled=trashed||documentWriting;
 $('archive-document').hidden=trashed;$('archive-document').textContent=currentDocument.status==='archived'?'Unarchive':'Archive';
 $('trash-document').textContent=trashed?'Restore document':'Move to trash';
 for(const id of ['archive-document','trash-document','document-history','reload-document'])$(id).disabled=documentWriting;
}
function thoughtOptions(select,includeAll=false){
 const selected=select.value;
 select.replaceChildren(...(includeAll?[new Option('All thoughts','')]:[]),...Array.from($('branch').options,o=>new Option(topicName(o.value),o.value)));
 if(Array.from(select.options).some(o=>o.value===selected))select.value=selected;
}
function displayDocument(doc){
 currentDocument=doc;documentDirty=false;$('editor-placeholder').hidden=true;$('document-editor').hidden=false;
 $('document-title').value=doc.title;$('document-content').value=doc.content;$('document-collection').value=doc.collection;
 thoughtOptions($('document-branch'));if(!Array.from($('document-branch').options).some(o=>o.value===doc.branch))$('document-branch').add(new Option(topicName(doc.branch),doc.branch));$('document-branch').value=doc.branch;
 $('document-kind-label').textContent=kindLabels[doc.kind]+' · '+doc.status;
 $('document-source').hidden=!doc.source_text;
 $('document-source-meta').textContent=(doc.filename?'Imported from '+doc.filename:'Spoken in '+topicName(doc.source_branch))+(doc.source_transcript?' · '+doc.source_transcript:'');
 $('document-source-text').textContent=doc.source_text;
 documentEditorState();renderDocumentRows();
 if(document.body.dataset.view==='documents')history.replaceState(null,'','#documents/'+encodeURIComponent(doc.id));
}
async function saveDocument(extra={}){
 if(!currentDocument||documentWriting)return false;
 documentWriting=true;documentEditorState();
 try{
  const doc=await documentAPI('/change',{id:currentDocument.id,version:currentDocument.version,changes:{...documentFields(),...extra}});
  displayDocument(doc);documentNotice('Saved · version '+doc.version);loadDocuments();return true;
 }catch(error){documentNotice(error.message,true);return false;}
 finally{documentWriting=false;documentEditorState();}
}
async function canLeaveDocument(){
 if(documentWriting)return false;if(!documentDirty)return true;if(leavePromise)return leavePromise;
 leavePromise=new Promise(resolve=>{
  const dialog=$('document-unsaved-dialog');dialog.showModal();
  const finish=value=>{dialog.close();leavePromise=null;resolve(value);};
  $('cancel-document-leave').onclick=()=>{if(!documentWriting)finish(false);};
  $('discard-document-changes').onclick=()=>{if(documentWriting)return;displayDocument(currentDocument);finish(true);};
  $('save-document-leave').onclick=async()=>{const ok=await saveDocument();if(ok)finish(true);};
  dialog.oncancel=event=>{event.preventDefault();if(!documentWriting)finish(false);};
 });return leavePromise;
}
async function selectDocument(identifier){
 if(!await canLeaveDocument())return;const request=++documentEditorRequest;
 try{const doc=await documentAPI('/item?id='+encodeURIComponent(identifier));if(request===documentEditorRequest){displayDocument(doc);documentNotice('');}}
 catch(error){documentNotice(error.message,true);}
}
function shortDocumentDate(value){return new Intl.DateTimeFormat('en',{month:'short',day:'numeric'}).format(new Date(value*1000));}
function renderDocumentRows(){
 $('document-list').replaceChildren(...documentRows.map(doc=>{
  const button=document.createElement('button');button.className='document-row'+(currentDocument?.id===doc.id?' selected':'');
  button.setAttribute('aria-label',doc.title);
  const top=document.createElement('div');top.className='document-row-top';
  const type=document.createElement('span');type.className='document-type';type.textContent=kindLabels[doc.kind];
  const date=document.createElement('span');date.textContent=shortDocumentDate(doc.updated);top.append(type,date);
  const title=document.createElement('h2');title.textContent=doc.title;
  const preview=document.createElement('p');preview.textContent=doc.preview||'An empty page, ready for your next idea.';
  const footer=document.createElement('div');footer.className='document-row-footer';const thought=document.createElement('span');thought.textContent='⑂ '+topicName(doc.branch);footer.append(thought);
  if(doc.collection){const collection=document.createElement('span');collection.textContent='· '+doc.collection;footer.append(collection);}
  button.append(top,title,preview,footer);button.onclick=()=>selectDocument(doc.id);return button;
 }));
 $('document-empty').hidden=!!documentRows.length;$('load-more-documents').hidden=documentNext===null;
 $('document-total').textContent=documentRows.length+(documentNext!==null?'+':'')+' items';
}
async function loadDocuments(append=false){
 const request=++documentListRequest;
 const query=new URLSearchParams({query:$('document-search').value,kind:documentKind,status:$('document-status-filter').value,branch:$('document-thought-filter').value,offset:String(append?documentNext||0:0)});
 try{const result=await documentAPI('?'+query);if(request!==documentListRequest)return;documentRows=append?[...documentRows,...result.documents]:result.documents;documentNext=result.next_offset;renderDocumentRows();}
 catch(error){if(request===documentListRequest)documentNotice(error.message,true);}
}
async function showDocuments(identifier=null){
 if(!await canLeaveDocument())return;
 if(liveActive())await endLive('Conversation paused. Your voice notes are saved.');else if(busy)await stopAll();
 if(!$('branch').options.length)await refresh();
 document.body.dataset.view='documents';$('documents-workspace').hidden=false;
 $('nav-documents').classList.add('selected');$('nav-thoughts').classList.remove('selected');$('topic-title').textContent='Documents';
 thoughtOptions($('document-thought-filter'),true);history.replaceState(null,'','#documents'+(identifier?'/'+encodeURIComponent(identifier):''));
 await loadDocuments();if(identifier)await selectDocument(identifier);
}
async function showThoughts(){
 if(!await canLeaveDocument())return false;
 document.body.dataset.view='thoughts';$('documents-workspace').hidden=true;
 $('nav-documents').classList.remove('selected');$('nav-thoughts').classList.add('selected');history.replaceState(null,'',location.pathname);renderProduct();return true;
}
$('nav-documents').onclick=()=>showDocuments();$('nav-thoughts').onclick=showThoughts;
for(const id of ['new-topic','topics'])$(id).addEventListener('click',async event=>{
 if(document.body.dataset.view!=='documents')return;
 const target=id==='topics'?event.target.closest('button'):$(id);if(!target||target.disabled)return;
 event.preventDefault();event.stopImmediatePropagation();if(await showThoughts())target.click();
},true);
for(const id of ['document-title','document-content','document-collection','document-branch'])$(id).addEventListener('input',documentEditorState);
$('document-editor').onsubmit=event=>{event.preventDefault();saveDocument();};
$('archive-document').onclick=()=>saveDocument({status:currentDocument.status==='archived'?'active':'archived'});
$('trash-document').onclick=()=>saveDocument({status:currentDocument.status==='trash'?'active':'trash'});
$('reload-document').onclick=()=>currentDocument&&selectDocument(currentDocument.id);
$('new-document').onclick=async()=>{
 if(!await canLeaveDocument())return;
 try{const doc=await documentAPI('/create',{title:'Untitled document',content:'',branch:$('branch').value});displayDocument(doc);await loadDocuments();$('document-title').focus();$('document-title').select();}
 catch(error){documentNotice(error.message,true);}
};
$('import-document').onchange=async event=>{
 const file=event.target.files[0];event.target.value='';if(!file||!await canLeaveDocument())return;
 if(!/\.(txt|md)$/i.test(file.name)||file.size>131072){documentNotice('Choose a UTF-8 .txt or .md file up to 128 KB.',true);return;}
 try{
  const content=new TextDecoder('utf-8',{fatal:true}).decode(await file.arrayBuffer());
  const doc=await documentAPI('/create',{title:file.name.replace(/\.(txt|md)$/i,'').slice(0,80)||'Imported document',content,kind:'reference',filename:file.name.slice(0,60),branch:$('branch').value});
  displayDocument(doc);await loadDocuments();documentNotice('Reference imported. The original text is kept with this document.');
 }catch{documentNotice('Could not import this file. Use UTF-8 plain text without null characters, up to 128 KB.',true);}
};
$('document-search').oninput=()=>{clearTimeout(documentSearchTimer);documentSearchTimer=setTimeout(()=>loadDocuments(),200);};
for(const id of ['document-thought-filter','document-status-filter'])$(id).onchange=()=>loadDocuments();
for(const button of document.querySelectorAll('.document-tabs button'))button.onclick=()=>{
 documentKind=button.dataset.kind;for(const tab of document.querySelectorAll('.document-tabs button'))tab.classList.toggle('selected',tab===button);loadDocuments();
};
$('load-more-documents').onclick=()=>loadDocuments(true);
$('export-document').onclick=()=>{
 if(!currentDocument)return;const fields=documentFields();const blob=new Blob(['# '+fields.title+'\n\n'+fields.content+'\n'],{type:'text/markdown;charset=utf-8'});const url=URL.createObjectURL(blob);
 const link=document.createElement('a');link.href=url;link.download=fields.title.replace(/[<>:"/\\|?*\u0000-\u001f]/g,'-')+'.md';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
};
async function previewDocumentVersion(){
 try{const doc=await documentAPI('/revision?id='+encodeURIComponent(currentDocument.id)+'&version='+$('document-version-select').value);$('document-version-preview').textContent=doc.title+'\n\n'+doc.content;}
 catch(error){documentNotice(error.message,true);}
}
$('document-history').onclick=async()=>{
 if(!currentDocument||!await canLeaveDocument())return;
 try{const result=await documentAPI('/history?id='+encodeURIComponent(currentDocument.id));$('document-version-select').replaceChildren(...result.versions.map(v=>new Option('Version '+v.version+' · '+shortDocumentDate(v.created)+' · '+v.title,String(v.version))));await previewDocumentVersion();$('document-versions-dialog').showModal();}
 catch(error){documentNotice(error.message,true);}
};
$('document-version-select').onchange=previewDocumentVersion;
$('close-document-versions').onclick=()=>$('document-versions-dialog').close();
$('restore-document-version').onclick=async()=>{
 try{const doc=await documentAPI('/restore',{id:currentDocument.id,version:currentDocument.version,restore_version:Number($('document-version-select').value)});displayDocument(doc);$('document-versions-dialog').close();await loadDocuments();documentNotice('Earlier content restored as version '+doc.version+'.');}
 catch(error){documentNotice(error.message,true);}
};
function updateReplySave(){
 $('save-reply').disabled=busy||liveActive()||!!sources.size||!$('answer').textContent.trim()||$('answer').textContent===ui('开始一次对话。');
}
$('save-reply').onclick=async()=>{
 $('save-reply').disabled=true;
 try{
  const state=await api('/api/state');const groups=new Map();
  for(const segment of state.responses){if(!groups.has(segment.reply))groups.set(segment.reply,[]);groups.get(segment.reply).push(segment);}
  const answer=$('answer').textContent.trim();const match=Array.from(groups).find(([,segments])=>segments.sort((a,b)=>a.sequence-b.sequence).map(s=>s.text).join('').trim()===answer);
  if(!match)throw Error('Wait for the full reply to finish playing before saving it.');
  const doc=await documentAPI('/draft',{reply_id:match[0]});await showDocuments(doc.id);documentNotice('Reply saved as an editable draft. The original transcript is preserved below.');
 }catch(error){status(error.message);}
 finally{updateReplySave();}
};
const documentVoiceObserver=new MutationObserver(updateReplySave);
for(const id of ['status','answer','live'])documentVoiceObserver.observe($(id),{childList:true,subtree:true});
const documentBranchObserver=new MutationObserver(()=>{if(document.body.dataset.view==='documents')thoughtOptions($('document-thought-filter'),true);});
documentBranchObserver.observe($('branch'),{childList:true});
window.addEventListener('beforeunload',event=>{if(documentDirty){event.preventDefault();event.returnValue='';}});
window.addEventListener('pagehide',()=>{documentVoiceObserver.disconnect();documentBranchObserver.disconnect();clearTimeout(documentSearchTimer);});
updateReplySave();
if(location.hash.startsWith('#documents')){const id=location.hash.slice('#documents/'.length);showDocuments(location.hash.startsWith('#documents/')?decodeURIComponent(id):null);}
