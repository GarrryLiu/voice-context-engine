import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from voice_context.gateway import Pipeline
from voice_context.documents import DocumentConflict


class DocumentTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.path=str(Path(self.tmp.name)/'documents.db')
        self.p=Pipeline(self.path);self.p.engine.fork('main');self.store=self.p.transcripts.documents
    def tearDown(self):self.p.close();self.tmp.cleanup()
    def speech(self,identifier='speech',text='A voice note about the launch plan.'):
        self.p.submit(identifier,'main','session',text);return self.store.get('voice:'+identifier)
    def test_final_capture_atomic_idempotent_and_edit_keeps_original(self):
        self.p.submit('partial','main','session','not final',final=False)
        self.assertEqual(self.store.listing()['documents'],[])
        with patch.object(self.store,'capture',side_effect=RuntimeError('disk failure')):
            with self.assertRaises(RuntimeError):self.speech()
        self.assertIsNone(self.p.engine.db.execute('SELECT 1 FROM transcripts WHERE id=?',('speech',)).fetchone())
        doc=self.speech();self.speech()
        self.assertEqual(len(self.store.listing()['documents']),1)
        changed=self.store.update(doc['id'],1,{'title':'Launch plan','content':'Edited working note.'})
        self.assertEqual(changed['source_text'],doc['content']);self.assertEqual(changed['version'],2)
        self.store.backfill();self.assertEqual(self.store.get(doc['id'])['content'],'Edited working note.')
    def test_conflict_versions_restore_and_restart(self):
        doc=self.speech();self.store.update(doc['id'],1,{'content':'Second version.'})
        other=Pipeline(self.path)
        try:
            with self.assertRaises(DocumentConflict):other.transcripts.documents.update(doc['id'],1,{'content':'Stale editor.'})
            self.assertEqual(other.transcripts.documents.get(doc['id'])['content'],'Second version.')
        finally:other.close()
        restored=self.store.restore(doc['id'],2,1)
        self.assertEqual(restored['version'],3);self.assertEqual(restored['content'],doc['content'])
        self.assertEqual(len(self.store.history(doc['id'])),3)
        self.assertEqual(self.store.revision(doc['id'],2)['content'],'Second version.')
    def test_archive_trash_search_collection_and_thought_link(self):
        doc=self.speech();self.p.engine.fork('child','main')
        changed=self.store.update(doc['id'],1,{'collection':'Research','branch':'child','status':'archived'})
        self.assertEqual(self.store.listing()['documents'],[])
        self.assertEqual(len(self.store.listing(query='research',branch='child',status='archived')['documents']),1)
        self.assertEqual(changed['source_branch'],'main')
        changed=self.store.update(doc['id'],2,{'status':'trash'})
        self.assertEqual(len(self.store.listing(status='trash')['documents']),1)
        self.assertEqual(self.store.update(doc['id'],3,{'status':'active'})['version'],4)
    def test_reference_and_plain_text_validation(self):
        doc=self.store.create('Reference','Untrusted <script>markup</script>.','main','reference','input.md')
        self.assertEqual(doc['source_text'],doc['content'])
        self.store.update(doc['id'],1,{'content':'Revised text'})
        self.assertEqual(self.store.get(doc['id'])['source_text'],'Untrusted <script>markup</script>.')
        with self.assertRaises(ValueError):self.store.create('x','x'*131073,'main')
        with self.assertRaises(ValueError):self.store.create('x','text','missing')
        with self.assertRaises(ValueError):self.store.update(doc['id'],2,{'source_text':'replacement'})
        self.store.create('100% complete','literal wildcard','main')
        self.assertEqual(len(self.store.listing(query='%')['documents']),1)
    def test_existing_speech_backfill_and_pagination(self):
        # Simulate pre-document transcripts while keeping transaction/outbox behavior.
        with patch.object(self.store,'capture',return_value=None):self.speech_legacy()
        self.store.backfill();self.assertEqual(self.store.get('voice:legacy')['source_text'],'Older speech.')
        for i in range(101):self.store.create('Note '+str(i),'Content','main')
        first=self.store.listing(kind='note');second=self.store.listing(kind='note',offset=first['next_offset'])
        self.assertEqual(len(first['documents']),100);self.assertEqual(len(second['documents']),1)
    def speech_legacy(self):self.p.submit('legacy','main','session','Older speech.')
    def test_reply_requires_complete_playback_and_source_is_frozen(self):
        doc=self.speech();self.p.sessions.open('session','main',100)
        ticket=self.p.sessions.begin('session','reply',12000)
        self.p.sessions.segment(ticket,0,'A useful draft.')
        db=self.p.engine.db
        with db:db.execute("INSERT INTO output_chunks(reply,sequence,segment,bytes,sha256,rendered,acknowledged) VALUES ('reply',0,0,4,'test',4,0)")
        self.p.sessions.seal(ticket)
        with self.assertRaises(ValueError):self.store.draft('reply','session')
        with db:db.execute("UPDATE output_chunks SET acknowledged=4 WHERE reply='reply'")
        draft=self.store.draft('reply','session');again=self.store.draft('reply','session')
        self.assertEqual(draft['id'],again['id']);self.assertEqual(draft['content'],'A useful draft.')
        self.assertEqual(draft['source_transcript'],'speech');self.assertEqual(draft['source_text'],doc['content'])
        with self.assertRaises(ValueError):self.store.draft('reply','another-session')
