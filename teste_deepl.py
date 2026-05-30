import deepl

CHAVE_DEEPL = "a68c0b52-08d0-4fe1-bb8a-bc2b38650657:fx"

try:
    print("Conectando ao DeepL...")
    translator = deepl.Translator(CHAVE_DEEPL)
    
    # Checando o uso da conta
    usage = translator.get_usage()
    print(f"Status da cota: {usage}")
    
    # Tentando uma traduC'C#o simples
    resultado = translator.translate_text("Hello, world!", target_lang="PT-BR")
    print(f"TraduC'C#o: {resultado.text}")

except deepl.exceptions.QuotaExceededException:
    print("ERRO EXATO: O DeepL confirmou que a cota estourou.")
except deepl.exceptions.AuthorizationException:
    print("ERRO EXATO: O DeepL recusou a chave (verifique se copiou algum espaC'o em branco junto).")
except Exception as e:
    print(f"OUTRO ERRO: {e}")
