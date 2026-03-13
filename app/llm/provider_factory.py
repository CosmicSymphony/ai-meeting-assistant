from app.llm.openai_provider import OpenAIProvider

_provider = None

def get_llm_provider():
    global _provider
    if _provider is None:
        _provider = OpenAIProvider()
    return _provider