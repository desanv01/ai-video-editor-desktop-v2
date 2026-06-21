"""Test DeepSeek JSON response_format support."""
import asyncio, json
from openai import AsyncOpenAI
from config import settings

async def test():
    client = AsyncOpenAI(
        api_key=settings.DEEPSEEK_API_KEY,
        base_url=settings.DEEPSEEK_BASE_URL,
    )
    # Test 1: with response_format
    print("=== Test 1: With response_format=json_object ===")
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "Say hello in JSON format with a greeting field"}],
            response_format={"type": "json_object"},
            max_tokens=100,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        print(f"  Response: {content[:300]}")
        parsed = json.loads(content)
        print(f"  ✅ Valid JSON: {json.dumps(parsed)[:200]}")
    except Exception as e:
        print(f"  ❌ Error: {e}")

    # Test 2: without response_format
    print("\n=== Test 2: Without response_format ===")
    try:
        response = await client.chat.completions.create(
            model="deepseek-v4-flash",
            messages=[{"role": "user", "content": "Say hello in JSON format with a greeting field"}],
            max_tokens=100,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        print(f"  Response: {content[:300]}")
        try:
            parsed = json.loads(content)
            print(f"  ✅ Valid JSON: {json.dumps(parsed)[:200]}")
        except json.JSONDecodeError:
            print(f"  ❌ NOT valid JSON")
    except Exception as e:
        print(f"  ❌ Error: {e}")

asyncio.run(test())
