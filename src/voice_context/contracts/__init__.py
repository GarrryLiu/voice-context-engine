"""Versioned product/runtime boundary. Standard library only; no provider imports.

ProductSessionId identifies a long-lived user artifact. InteractionSessionId
identifies a runtime client handle; BranchId identifies its context lineage.
They are intentionally distinct even when serialized as strings on HTTP v1.
"""
from typing import Any,Literal,NewType,NotRequired,Protocol,TypedDict

CONTRACT_VERSION='1'
ProductSessionId=NewType('ProductSessionId',str)
InteractionSessionId=NewType('InteractionSessionId',str)
BranchId=NewType('BranchId',str)
ControlAction=Literal['fork','new_branch','switch','interrupt']


class WorkspaceSnapshot(TypedDict):
    version:int
    data:dict[str,Any]


class RuntimeState(TypedDict):
    session:InteractionSessionId
    branch:BranchId
    epoch:int
    branches:list[dict[str,Any]]
    recent:list[dict[str,Any]]
    responses:list[dict[str,Any]]


class PlaybackAck(TypedDict):
    epoch:int
    request_id:str
    sequence:int
    offset:int


class VoiceEvent(TypedDict):
    type:Literal['status','partial','transcript','reply','text','audio','generated','error','done']
    request_id:NotRequired[str]
    epoch:NotRequired[int]
    text:NotRequired[str]
    data:NotRequired[str]


class RuntimeControl(Protocol):
    def state(self,session:InteractionSessionId)->RuntimeState:...
    def controls(self,session:InteractionSessionId,action:ControlAction,branch:BranchId|None=None)->RuntimeState:...
    def acknowledge(self,session:InteractionSessionId,data:PlaybackAck)->bool:...


class ProductData(Protocol):
    def workspace(self,session:InteractionSessionId,data:WorkspaceSnapshot|None=None)->WorkspaceSnapshot:...
    def documents(self,session:InteractionSessionId,action:str,data:dict[str,Any])->Any:...


def capabilities(mode='connected'):
    """Additive HTTP v1 discovery; never includes model configuration or secrets."""
    if mode not in {'connected','demo'}:raise ValueError('unknown mode')
    return {'contract_version':CONTRACT_VERSION,'mode':mode,'features':{'live_voice':mode=='connected','audio_input':mode=='connected','demo_text':mode=='demo'},
            'endpoints':{'state':'/api/state','control':'/api/control','turn':'/api/turn',
                         'reply':'/api/reply','ack':'/api/ack','live':'/api/live',
                         'workspace':'/api/workspace','documents':'/api/documents'},
            'limits':{'audio_bytes':2097152,'document_request_bytes':262144,'workspace_request_bytes':2100000},
            'semantics':{'confirmed_speech':'durable_before_acknowledgement',
                         'playback':'explicit_ack_required','workspace':'optimistic_version',
                         'new_branch':'independent_context','map_edits':'not_model_memory'}}
