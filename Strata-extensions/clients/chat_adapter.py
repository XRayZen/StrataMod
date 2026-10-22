"""Thin selected-family stream adapter and exact patch of the existing chat entry."""
import ast
import copy
import hashlib
import json
import urllib.request
from urllib.parse import urlsplit,urlunsplit
from .stream_contract import CompletionStream,StreamError

EFFORTS=('none','minimal','low','medium','high','xhigh','ultra','max')

def request_body(messages,think,maximum):
    body=dict(model='strata',messages=copy.deepcopy(messages),stream=True)
    if think is not None:
        if think not in EFFORTS:raise ValueError('unsupported provider reasoning effort')
        body['reasoning_effort']=think
    if maximum is not None:
        if type(maximum)is not int:raise ValueError('integer output reservation required')
        body['max_tokens']=maximum # official Recipe handles the existing legacy <=0 convention
    return body

class ChatStream:
    def __init__(self,url,messages,think,maximum,identity_provider=None):
        self.url=url;self.body=request_body(messages,think,maximum)
        self.message=None;self.result=None;self.started=False;self.identity_provider=identity_provider

    def __iter__(self):
        if self.started:raise StreamError('response iterator already consumed')
        self.started=True
        request=urllib.request.Request(self.url,data=json.dumps(self.body).encode(),headers={'Content-Type':'application/json'})
        expected=self.identity_provider()if self.identity_provider is not None else None
        parser=CompletionStream(expected_identity=expected);reason=content=0
        # Retain the original frontend's per-socket-read timeout; not an overall request duration.
        with urllib.request.urlopen(request,timeout=3600)as response:
            while True:
                chunk=response.read1(65536)
                if not chunk:break
                parser.feed(chunk)
                state=parser.choices.get(0)
                if state is not None:
                    r,c=state['reasoning_content'][reason:],state['content'][content:]
                    reason=len(state['reasoning_content']);content=len(state['content'])
                    if r or c:yield r,c
        result=parser.finish()
        if len(result['choices'])!=1 or result['choices'][0]['index']!=0:raise StreamError('chat selected response unavailable')
        if self.identity_provider is not None:
            from .runtime_identity import same
            if not same(expected,self.identity_provider()):raise StreamError('runtime identity changed before chat commit')
        self.result=result;self.message=result['choices'][0]['message']

def stream(url,messages,think,max_tokens):return ChatStream(url,messages,think,max_tokens)

def http_identity(url):
    from .runtime_identity import normalize
    parts=urlsplit(url);metrics=urlunsplit((parts.scheme,parts.netloc,'/metrics','',''))
    try:
        with urllib.request.urlopen(urllib.request.Request(metrics,headers={'Accept':'application/json'}),timeout=3600)as response:
            value=json.loads(response.read())
            if type(value)is not dict:raise ValueError('metrics object unavailable')
            return normalize(value.get('strata_runtime'))
    except ValueError as error:raise StreamError('chat runtime identity unavailable: '+str(error))from error

def bound_stream(url,messages,think,max_tokens):
    # Enabled only by the new identity-declaring immutable client extension.
    return ChatStream(url,messages,think,max_tokens,identity_provider=lambda:http_identity(url))

def derive_chat(raw,expected_sha,*,bind_identity=False):
    """Generate a versioned package artifact, preserving the upstream entry as source."""
    if hashlib.sha256(raw).hexdigest()!=expected_sha:raise ValueError('fixed upstream chat changed')
    source=raw.decode('utf-8');tree=ast.parse(source)
    functions=[x for x in tree.body if isinstance(x,ast.FunctionDef)and x.name=='stream']
    if len(functions)!=1:raise ValueError('upstream stream anchor changed')
    node=functions[0];lines=source.splitlines(keepends=True)
    lines[node.lineno-1:node.end_lineno]=['stream = selected_stream\n']
    source=''.join(lines)
    def replace(old,new):
        nonlocal source
        if source.count(old)!=1:raise ValueError('upstream chat anchor changed: '+old)
        source=source.replace(old,new)
    replace('import urllib.request','import urllib.request\nfrom pathlib import Path\nsys.path.insert(0, str(Path(__file__).resolve().parents[1] / "Strata-extensions"))\nfrom clients.chat_adapter import stream as selected_stream')
    replace('default="medium", choices=["none", "low", "medium", "high"]','default=None, choices='+repr(list(EFFORTS)))
    replace('ap.add_argument("--max-tokens", type=int, default=4096)','ap.add_argument("--max-tokens", type=int, default=None)')
    replace('if level in ("none", "low", "medium", "high"):','if level in '+repr(EFFORTS)+':')
    replace('            for reasoning, content in stream(url, messages, think, a.max_tokens):','            turn = stream(url, messages, think, a.max_tokens)\n            for reasoning, content in turn:')
    replace('messages.append({"role": "assistant", "content": "".join(answer)})','messages.append(turn.message)')
    replace('except OSError as e:','except (OSError, KeyboardInterrupt) as e:')
    source=source.replace('none|low|medium|high','|'.join(EFFORTS))
    source=source.replace('(now: {think})',"(now: {think or 'provider default'})")
    if bind_identity:
        source=source.replace('from clients.chat_adapter import stream as selected_stream','from clients.chat_adapter import bound_stream as selected_stream',1)
    ast.parse(source)
    return source
