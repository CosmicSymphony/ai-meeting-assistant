from openai import AsyncOpenAI
from app.config import settings


class OpenAIProvider:
    def __init__(self):
        if not settings.OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is missing. Check your .env file.")

        self.client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)

    async def generate(self, prompt: str) -> str:
        try:
            response = await self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[
                    {"role": "system", "content": "You are an intelligent AI meeting assistant."},
                    {"role": "user", "content": prompt}
                ]
            )
            return response.choices[0].message.content or ""
        except Exception as e:
            print("OPENAI GENERATE ERROR:", repr(e))
            raise
