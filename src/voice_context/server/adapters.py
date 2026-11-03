"""Composition adapter retaining the current shared transaction/connection owner."""
from contextlib import contextmanager
from types import SimpleNamespace
from ..product.product_workspace import ProductWorkspace


class RuntimeProductAccess:
    def __init__(self,runtime):self.runtime=runtime

    @contextmanager
    def open(self,session):
        conversation=self.runtime.session(session)
        with conversation.lock:
            pipeline=conversation.pipeline
            yield SimpleNamespace(documents=pipeline.transcripts.documents,
                                  workspace=ProductWorkspace(pipeline.engine.db),
                                  branch=pipeline.sessions.get(session)['branch'])
