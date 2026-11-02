"""Reusable provider ports; implementations own SDK timeouts and audio format."""
from dataclasses import dataclass
from threading import Event
from typing import Any,Iterable,Iterator,Protocol


@dataclass(frozen=True)
class Transcript:
    text:str
    final:bool


class STTProvider(Protocol):
    name:str # include model/config revision in live adapters
    def stream(self,audio:Iterable[bytes],cancelled:Event,request_id:str)->Iterator[Transcript]:...


class TextProvider(Protocol):
    name:str
    def stream(self,context:dict[str,Any],cancelled:Event,request_id:str)->Iterator[str|bytes]:...


class TTSProvider(Protocol):
    name:str
    def stream(self,text:str,cancelled:Event,request_id:str)->Iterator[bytes]:...
