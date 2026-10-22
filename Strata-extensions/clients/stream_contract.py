"""OpenAI SSE transport and a transactional client turn; no runtime authority."""
import codecs
import copy
import json


class StreamError(OSError):
    pass


def require(condition, reason):
    if not condition:
        raise StreamError(reason)


def strict_json(raw):
    def invalid(value):raise StreamError('non-JSON constant: '+value)
    return json.loads(raw,parse_constant=invalid)


class CompletionStream:
    def __init__(self,expected_identity=None):
        self.expected_identity=None
        if expected_identity is not None:
            from .runtime_identity import normalize
            self.expected_identity=normalize(expected_identity)
        self.decoder=codecs.getincrementaldecoder('utf-8')('strict')
        self.buffer=''
        self.data=[]
        self.choices={}
        self.usage=None
        self.done=False
        self.cancelled=False
        self.failure=None
        self.finished=False

    def cancel(self):
        self.cancelled=True

    def feed(self, chunk):
        require(not self.finished and not self.cancelled and self.failure is None,'inactive stream')
        require(type(chunk)is bytes,'transport bytes required')
        try:
            self.buffer+=self.decoder.decode(chunk)
            while '\n' in self.buffer:
                line,self.buffer=self.buffer.split('\n',1)
                if line.endswith('\r'):line=line[:-1]
                self._line(line)
        except (UnicodeError,ValueError,TypeError,KeyError,StreamError)as error:
            self.failure=str(error)
            raise StreamError('invalid or incomplete SSE: '+str(error))from error

    def _line(self,line):
        if not line:
            if self.data:
                self._event('\n'.join(self.data));self.data=[]
            return
        if line.startswith(':'):return
        field,separator,value=line.partition(':')
        if separator and value.startswith(' '):value=value[1:]
        if field=='data':self.data.append(value)
        # Other SSE fields (event/id/retry) do not carry completion deltas.

    def _event(self,data):
        require(not self.done,'completion event after DONE')
        if data=='[DONE]':
            require(self.choices and all(x['finish_reason']is not None for x in self.choices.values()),'DONE without formal finish')
            self.done=True
            return
        value=strict_json(data)
        require(type(value)is dict,'completion object required')
        require(value.get('error')is None,'provider error: '+str(value.get('error')))
        if self.expected_identity is not None:
            from .runtime_identity import same
            require(same(self.expected_identity,value.get('strata_runtime')),'runtime changed or identity unavailable in response')
        if value.get('usage')is not None:
            usage=value['usage'];require(type(usage)is dict,'usage object')
            for key in ('prompt_tokens','completion_tokens','total_tokens'):
                if key in usage:require(type(usage[key])is int and usage[key]>=0,'invalid usage counter')
            if self.usage is not None:require(self.usage==usage,'conflicting usage')
            self.usage=copy.deepcopy(usage)
        rows=value.get('choices',[]);require(type(rows)is list,'choices list')
        for row in rows:
            require(type(row)is dict and type(row.get('index'))is int and row['index']>=0,'choice index')
            state=self.choices.setdefault(row['index'],dict(content='',reasoning_content='',tools={},legacy=None,finish_reason=None))
            delta=row.get('delta',{});require(type(delta)is dict,'delta object')
            require(state['finish_reason']is None or not delta,'delta after formal finish')
            if 'role'in delta:require(delta['role']=='assistant','assistant role required')
            for key in ('content','reasoning_content'):
                if delta.get(key)is not None:
                    require(type(delta[key])is str,'text delta');state[key]+=delta[key]
            if 'tool_calls'in delta:
                require(state['legacy']is None,'mixed legacy/modern function delta')
                require(type(delta['tool_calls'])is list,'tool delta list')
                for tool in delta['tool_calls']:
                    require(type(tool)is dict and type(tool.get('index'))is int and tool['index']>=0,'tool index')
                    t=state['tools'].setdefault(tool['index'],dict(id='',type='function',function=dict(name='',arguments='')))
                    if tool.get('id'):
                        require(type(tool['id'])is str and (not t['id']or t['id']==tool['id']),'tool id changed');t['id']=tool['id']
                    if 'type'in tool:require(tool['type']=='function','tool type')
                    function=tool.get('function',{});require(type(function)is dict,'function delta')
                    for key in ('name','arguments'):
                        if key in function:
                            require(type(function[key])is str,'function text delta');t['function'][key]+=function[key]
            if 'function_call'in delta:
                require(not state['tools'],'mixed legacy/modern function delta')
                function=delta['function_call'];require(type(function)is dict,'legacy function delta')
                if state['legacy']is None:state['legacy']=dict(name='',arguments='')
                for key in ('name','arguments'):
                    if key in function:
                        require(type(function[key])is str,'legacy function text delta');state['legacy'][key]+=function[key]
            terminal=row.get('finish_reason')
            if terminal is not None:
                require(terminal in ('stop','length','tool_calls','function_call','content_filter'),'unrecognized formal finish')
                require(state['finish_reason']is None,'duplicate formal finish')
                state['finish_reason']=terminal

    def finish(self):
        require(not self.finished and not self.cancelled and self.failure is None,'stream did not complete')
        self.finished=True
        try:
            self.buffer+=self.decoder.decode(b'',final=True)
        except UnicodeError as error:
            self.failure=str(error);raise StreamError('truncated UTF8')from error
        require(not self.buffer and not self.data and self.done,'EOF before complete DONE event')
        choices=[]
        for index,state in sorted(self.choices.items()):
            message=dict(role='assistant',content=state['content'])
            if self.expected_identity is not None:message['strata_runtime']=copy.deepcopy(self.expected_identity)
            if state['reasoning_content']:message['reasoning_content']=state['reasoning_content']
            if state['tools']:
                tools=[copy.deepcopy(x)for _,x in sorted(state['tools'].items())]
                ids=set()
                for tool in tools:
                    require(tool['id']and tool['id']not in ids and tool['function']['name'],'incomplete or duplicate tool identity');ids.add(tool['id'])
                    try:arguments=strict_json(tool['function']['arguments'])
                    except (ValueError,TypeError)as error:raise StreamError('incomplete tool arguments')from error
                    require(type(arguments)is dict,'tool arguments must be an object')
                message['tool_calls']=tools
            if state['legacy']is not None:
                legacy=state['legacy'];require(bool(legacy['name']),'incomplete legacy function')
                try:arguments=strict_json(legacy['arguments'])
                except (ValueError,TypeError)as error:raise StreamError('incomplete legacy arguments')from error
                require(type(arguments)is dict,'legacy arguments must be an object')
                message['function_call']=copy.deepcopy(legacy)
            choices.append(dict(index=index,message=message,finish_reason=state['finish_reason']))
        self.finished=True
        return dict(choices=choices,usage=copy.deepcopy(self.usage))


class Turn:
    def __init__(self,history,draft,expected_identity=None):
        self.history=copy.deepcopy(history)
        self.draft=copy.deepcopy(draft)
        self.stream=CompletionStream(expected_identity=expected_identity)
        self.committed=False

    def feed(self,chunk):self.stream.feed(chunk)
    def cancel(self):self.stream.cancel()

    def commit(self,observed_identity=None):
        if self.stream.expected_identity is not None:
            from .runtime_identity import same
            require(same(self.stream.expected_identity,observed_identity),'runtime changed or unavailable before history commit')
        require(not self.committed,'turn already committed')
        result=self.stream.finish()
        require(len(result['choices'])==1,'interactive turn requires one selected response')
        self.history.extend([copy.deepcopy(self.draft),result['choices'][0]['message']])
        self.committed=True
        return result
