"""Focused production adapter checks; synthetic clients, no network/real keys."""
import asyncio
import builtins
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
from types import ModuleType, SimpleNamespace as NS

source = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(source / 'backend' / 'app'))
for key in list(os.environ):
    if key.startswith('AIVE_') or key.endswith('_API_KEY') or key in ('DATABASE_URL', 'RUNTIME_PROFILE', 'APP_ENV', 'APP_STORAGE_ROOT', 'DESKTOP_DB_PATH', 'DESKTOP_VECTOR_ROOT'):
        os.environ.pop(key, None)
os.environ.update(RUNTIME_PROFILE='desktop-native', APP_ENV='desktop-native', APP_DEBUG='false')
isolated_profile = tempfile.TemporaryDirectory(prefix='main4-lazy-check-')
from desktop_native.paths import NativeDesktopPaths
paths = NativeDesktopPaths.from_environment(data_root=Path(isolated_profile.name))
os.environ.update(paths.settings_environment())
paths.ensure_directories()
original_connect = socket.socket.connect
def blocked_connect(sock, address):
    # Windows asyncio creates its internal self-pipe with socketpair's fallback.
    if sys._getframe(1).f_code.co_name == '_fallback_socketpair' and address[0] in ('127.0.0.1', '::1'):
        return original_connect(sock, address)
    raise AssertionError('application network forbidden')
socket.socket.connect = blocked_connect
checks = []
original_import = builtins.__import__

def blocked_import(name, *a, **k):
    if name == 'openai' or name.startswith('openai.'):
        raise AssertionError('SDK loaded before cloud operation')
    return original_import(name, *a, **k)

builtins.__import__ = blocked_import
try:
    from providers.openai_compatible import OpenAICompatibleChatProvider, OpenAIEmbeddingProvider
    from providers.interfaces import ChatRequest, EmbeddingRequest
    from services.transcription import TranscriptionService
    from config import settings
    chat = OpenAICompatibleChatProvider(provider_id='probe-chat', label='Probe', provider_name='test', api_key='synthetic-chat', default_model='chat-default', base_url='https://invalid.example/v1')
    embed = OpenAIEmbeddingProvider(provider_id='probe-embed', label='Probe', api_key='synthetic-embed', default_model='embed-default', default_dimensions=2)
    service = TranscriptionService()
    assert chat.metadata.provider_id == 'probe-chat'
    assert embed.metadata.provider_id == 'probe-embed'
    asyncio.run(chat.health())
    asyncio.run(embed.health())
    settings.OPENAI_API_KEY = ''
    settings.MISTRAL_API_KEY = ''
    for operation in (service._whisper_single('missing-file'), service._voxtral_single('missing-file', None, None)):
        try:
            asyncio.run(operation)
        except ValueError:
            pass
        else:
            raise AssertionError('missing-key guard lost')
    checks.append('imports/construction/metadata/health/missing-key guards require no SDK')
finally:
    builtins.__import__ = original_import

constructed = []
calls = []
failure = {'construct': False, 'request': False}

class Client:
    def __init__(self, **kwargs):
        if failure['construct']:
            raise RuntimeError('synthetic construction failure')
        self.kwargs = kwargs
        constructed.append(self)
        self.chat = NS(completions=NS(create=self.complete))
        self.embeddings = NS(create=self.embedding)
        self.audio = NS(transcriptions=NS(create=self.transcribe))

    def with_options(self, **kwargs):
        calls.append(('options', kwargs))
        return self

    async def complete(self, **kwargs):
        calls.append(('chat', kwargs))
        await asyncio.sleep(0)
        return NS(choices=[NS(message=NS(content='synthetic response'))])

    async def embedding(self, **kwargs):
        calls.append(('embed', kwargs))
        return NS(data=[NS(embedding=[1.0, 2.0]) for _ in kwargs['input']])

    async def transcribe(self, **kwargs):
        calls.append(('transcribe', kwargs))
        if failure['request']:
            raise RuntimeError('synthetic request failure')
        return NS(text='Bridge pattern', duration=1.0, language='en', words=[], segments=[])

sdk = ModuleType('openai')
sdk.AsyncOpenAI = Client
sys.modules['openai'] = sdk

async def exercise():
    before = len(constructed)
    requests = [ChatRequest(messages=[{'role': 'user', 'content': 'probe'}], model='override', temperature=0.7, max_tokens=17, response_format={'type': 'json_object'}) for _ in range(2)]
    results = await asyncio.gather(*(chat.chat(req) for req in requests))
    assert len(constructed) == before + 1
    assert constructed[-1].kwargs == {'api_key': 'synthetic-chat', 'base_url': 'https://invalid.example/v1'}
    assert all(r.text == 'synthetic response' and r.model == 'override' for r in results)
    assert calls[-1][1] == {'model': 'override', 'messages': requests[0].messages, 'temperature': 0.7, 'max_tokens': 17, 'response_format': {'type': 'json_object'}}
    checks.append('concurrent first chat creates one client and preserves request/response contract')
    result = await embed.embed(EmbeddingRequest(texts=['one', 'two'], model='embed-override', dimensions=3))
    await embed.embed(EmbeddingRequest(texts=['three']))
    assert len(constructed) == before + 2
    assert result.embeddings == [[1.0, 2.0], [1.0, 2.0]] and result.dimensions == 3
    assert calls[-1] == ('embed', {'model': 'embed-default', 'input': ['three'], 'dimensions': 2})
    checks.append('embedding overrides/defaults/response and client reuse preserved')
    retry = OpenAICompatibleChatProvider(provider_id='retry', label='Probe', provider_name='test', api_key='', default_model='default')
    failure['construct'] = True
    try:
        await retry.chat(ChatRequest(messages=[]))
    except RuntimeError:
        pass
    else:
        raise AssertionError('construction failure swallowed')
    failure['construct'] = False
    await retry.chat(ChatRequest(messages=[]))
    assert retry._client.kwargs['api_key'] == 'not-configured'
    checks.append('failed construction can retry; prior empty-key adapter behavior retained')
    injected = Client(api_key='injected')
    chat._client = injected
    count = len(constructed)
    await chat.chat(ChatRequest(messages=[]))
    assert len(constructed) == count and chat._client is injected
    checks.append('injected client remains usable')
    with tempfile.TemporaryDirectory() as folder:
        audio = Path(folder) / 'synthetic.wav'
        audio.write_bytes(b'synthetic test bytes')
        for attr, operation in [('OPENAI_API_KEY', lambda: service._whisper_single(str(audio), 'en')), ('MISTRAL_API_KEY', lambda: service._voxtral_single(str(audio), 'en', ['Bridge']))]:
            setattr(settings, attr, 'synthetic-first')
            result = await operation()
            count = len(constructed)
            setattr(settings, attr, 'synthetic-rotated')
            await operation()
            assert len(constructed) == count and result['text'] == 'Bridge pattern'
            assert calls[-2] == ('options', {'api_key': 'synthetic-rotated'})
            assert calls[-1][1]['file'].closed
            failure['request'] = True
            try:
                await operation()
            except RuntimeError:
                pass
            else:
                raise AssertionError('request failure swallowed')
            failure['request'] = False
            assert calls[-1][1]['file'].closed
            checks.append(attr + ': current credentials, reused client and success/failure file cleanup')

asyncio.run(exercise())
print(json.dumps({'status': 'PASS', 'checks': checks, 'network': 'application connections forbidden; Windows asyncio internal socketpair allowed', 'source': str(source)}, indent=2))
