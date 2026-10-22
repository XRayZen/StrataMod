"""Family codec hook. It neither owns a producer nor executes tools."""
import importlib.util
import json
from pathlib import Path
import deepseek_recipe as recipe

_path=Path(__file__).resolve().parents[2]/'control/generation_frames.py'
_spec=importlib.util.spec_from_file_location('deepseek_generation_dto',_path)
_dto=importlib.util.module_from_spec(_spec);_spec.loader.exec_module(_dto)

class CodecError(ValueError):
    pass

def prepare_chat(body,tokenizer,context_capacity):
    """Official conversion/encoding; caller supplies its actual context capacity."""
    if type(context_capacity) is not int or context_capacity<=0:raise CodecError('context capacity')
    body=dict(body);legacy=None
    for key in ('max_tokens','max_completion_tokens'):
        if key in body and body[key] is not None:
            if type(body[key]) is not int:raise CodecError('maximum token type')
            if body[key]<=0:
                if legacy is not None:raise CodecError('ambiguous legacy maximum')
                legacy=body.pop(key)
    options=recipe.ConversionOptions().with_model_alias('strata',recipe.ModelVersion.DeepseekV41Flash)
    converted=recipe.ChatCompletionRequest(body).convert(options)
    ids=recipe.DeepseekV41Encoding().with_tokenizer(tokenizer).encode(converted.conversation)
    if legacy is not None:
        remaining=context_capacity-len(ids)
        if remaining<=0:raise CodecError('prompt exhausts context')
        body['max_tokens']=min(remaining,393216)
        converted=recipe.ChatCompletionRequest(body).convert(options)
        checked=recipe.DeepseekV41Encoding().with_tokenizer(tokenizer).encode(converted.conversation)
        if ids!=checked:raise CodecError('maximum normalization changed prompt IDs')
    maximum=converted.resolve_max_tokens(len(ids),context_capacity)
    return dict(converted=converted,input_ids=tuple(ids),inference_options=converted.inference_options,max_tokens=maximum,legacy_maximum=legacy)

class CodecSession:
    """One caller-bound frame stream; normal completion waits for raw integrity.

    Returned intermediate OpenAI deltas are incomplete until a terminal delta.
    The caller retains producer authentication, cancellation and tool authority.
    """
    def __init__(self,context,prepared,tokenizer,*,created=0,prompt_cache_hit_tokens=0,on_recipe_stop=None,cancelled=None):
        self.dto=_dto.GenerationDTO(context);self.failed=None;self.closed=False
        self.pending=[];self.saw_terminal=False;self.push_calls=0;self.pushed_ids=[]
        self.raw=None;self.normalized_finish=None;self.first_eos_index=None
        self.on_recipe_stop=on_recipe_stop;self.cancelled=cancelled or (lambda:False)
        self.recipe_stop_requested=False
        self.want_logprobs=bool(prepared["inference_options"].logprobs)
        count=len(prepared['input_ids'])
        generator=recipe.ChatCompletionRequest.chunk_generator(prepared['converted'],context['request_id'],'strata')
        self.processor=recipe.StreamProcessor(generator,prepared['converted'].parsing_options,tokenizer)
        self.response=recipe.ChatCompletionResponse(context['request_id'],'strata',created,count,prompt_cache_hit_tokens)
        self.usage=recipe.PromptUsage(prompt_tokens=count,prompt_cache_hit_tokens=prompt_cache_hit_tokens)

    def _events(self,chunks):
        output=[]
        for chunk in chunks:
            value=json.loads(chunk.to_json())
            terminal=any(c.get('finish_reason') is not None for c in value.get('choices',[]))
            if terminal:
                self.normalized_finish=next(c['finish_reason'] for c in value['choices'] if c.get('finish_reason') is not None)
                self.saw_terminal=True
            self.response.accumulate(chunk)
            if self.saw_terminal:self.pending.append(value)
            else:output.append(value)
        return output

    def _push(self,chunk):
        if self.processor.finished:raise CodecError('internal push after official completion')
        self.push_calls+=1
        events=self._events(self.processor.push(chunk))
        if self.processor.finished and self.on_recipe_stop and self.first_eos_index is None and not self.dto.ended and not self.recipe_stop_requested:
            self.recipe_stop_requested=True;self.on_recipe_stop()
        return events

    def feed(self,raw):
        if self.closed:raise CodecError('codec session closed')
        try:
            frame=_dto.parse_frame(raw)
            value=self.dto.feed(raw)
            if frame['kind']=='begin':return self._push(recipe.InferenceChunk.ready(prompt_usage=self.usage))
            if frame['kind']=='token_batch':
                if self.want_logprobs and any(x is None for x in self.dto.logprobs[-len(value):]):raise CodecError('requested logprobs missing')
                prior_eos=self.first_eos_index
                offset=value.index(1) if 1 in value else None
                if prior_eos is None and offset is not None:self.first_eos_index=len(self.dto.ids)-len(value)+offset
                if self.processor.finished or prior_eos is not None:return []
                prefix=value if offset is None else value[:offset];events=[]
                if prefix:
                    self.pushed_ids.extend(prefix);offset_start=len(self.dto.ids)-len(value)
                    lp=self.dto.logprobs[offset_start:offset_start+len(prefix)]
                    if any(x is not None for x in lp):
                        if any(x is None for x in lp):raise CodecError('partial logprob association')
                        lp=[(x[0],list(x[1])) for x in lp]
                    else:lp=None
                    events.extend(self._push(recipe.InferenceChunk.tokens(prefix,logprobs=lp)))
                if offset is not None and not self.processor.finished:
                    events.extend(self._push(recipe.InferenceChunk.finish(recipe.InferenceFinishReason.Stop)))
                    if not self.processor.finished:events.extend(self._events(self.processor.finish()))
                return events
            self.raw=value
            if value.get('stop_origin')=='recipe' and not (self.recipe_stop_requested and self.processor.finished):raise CodecError('unrequested recipe stop')
            if self.cancelled():
                self.pending.clear();self.failed='client_cancel';self.close();return []
            if not value['generation_success']:
                self.pending.clear();self.failed=value['finish'];self.close();return []
            events=[]
            if not self.processor.finished:
                reason=recipe.InferenceFinishReason.Stop if value['finish']=='stop' else recipe.InferenceFinishReason.Length
                events.extend(self._push(recipe.InferenceChunk.finish(reason)))
                if not self.processor.finished:events.extend(self._events(self.processor.finish()))
            if self.cancelled():
                self.pending.clear();self.failed='client_cancel';self.close();return []
            events.extend(self.pending);self.pending=[];self.close();return events
        except Exception as exc:
            self.failed=str(exc);self.pending.clear();self.close()
            raise CodecError(str(exc)) from exc

    def end_of_stream(self):
        try:self.dto.result()
        except Exception as exc:
            self.failed=str(exc);self.pending.clear();self.close();raise CodecError(str(exc)) from exc
        return self.result()

    def result(self):
        raw=self.dto.result()
        if not self.closed:raise CodecError('codec raw terminal not consumed')
        return dict(raw=raw,normalized_finish=self.normalized_finish,success=raw['generation_success'] and self.failed is None,response=json.loads(self.response.to_json()) if raw['generation_success'] and self.failed is None else None,push_calls=self.push_calls,recipe_input_ids=tuple(self.pushed_ids),recipe_input_count=len(self.pushed_ids),first_eos_index=self.first_eos_index)

    def close(self):
        if not self.closed:
            self.processor.close() # Official close releases resources, emits no normal terminal.
            self.closed=True
