import asyncio
from deep_translator import GoogleTranslator

async def test():
    texts = ["Hello", "World", "This is a test"]
    separator = " |&| "
    joined = separator.join(texts)
    print("Joined:", joined)

    translator = GoogleTranslator(source='auto', target='pt')
    translated = translator.translate(joined)
    print("Translated joined:", translated)

    parts = translated.split("|&|")
    print("Split parts:", parts)

asyncio.run(test())
