import asyncio
from deep_translator import GoogleTranslator

async def main():
    translator = GoogleTranslator(source='auto', target='pt')
    texts = ["Hello world", "I love you"]
    print("Starting translation...")
    try:
        translated_texts = await asyncio.to_thread(translator.translate_batch, texts)
        print("Translated:", translated_texts)
    except Exception as e:
        print("Error:", e)

asyncio.run(main())
