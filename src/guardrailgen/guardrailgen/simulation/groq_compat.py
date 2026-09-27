"""Use the OpenAI-compatible SDK already installed by the SafeLLMRA setup.

The library name is not the provider: credentials and every request go to Groq.
This adapter is selected explicitly by the four-terminal integration.
"""
import json
import os
import math

from guardrailgen.compiler.backend import BackendError, GroqBackend


class GroqCompatibilityBackend(GroqBackend):
    def __init__(self,*args,reasoning_effort=None,**kwargs):
        super().__init__(*args,**kwargs)
        self.reasoning_effort=reasoning_effort

    def configuration(self):
        return {**super().configuration(), 'transport': 'openai-0.28-compatible-sdk',
                'reasoning_effort':self.reasoning_effort or 'provider default'}

    def _send(self, body, key):
        import openai
        if openai.__version__ != '0.28.0':
            raise BackendError('backend_error', 'This compatibility adapter requires openai==0.28.0')
        try:
            if self.reasoning_effort:
                body={**body,'reasoning_effort':self.reasoning_effort}
            response = openai.ChatCompletion.create(
                api_key=key, api_base='https://api.groq.com/openai/v1',
                api_type='open_ai', request_timeout=self.timeout, **body)
        except openai.error.Timeout as exc:
            raise BackendError('timeout', 'Groq compatible SDK timed out') from exc
        except openai.error.OpenAIError as exc:
            # Never persist arbitrary provider text, headers, or credentials.
            code = getattr(exc, 'http_status', None)
            if code==429:
                failure=BackendError('rate_limited','Groq rate limit; retry after provider cooldown')
                try:
                    delay=float(exc.headers.get('retry-after',60))
                except (ValueError,TypeError):
                    delay=60.
                failure.retry_after_seconds=max(1.,delay) if math.isfinite(delay) else 60.
                raise failure from exc
            raise BackendError('backend_error', 'Groq compatible SDK failed; HTTP '+str(code)) from exc
        return self._parse_response(response.to_dict_recursive())
