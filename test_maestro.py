import asyncio
from qobuz_dl.settings import QobuzDLSettings

# Importe os ficheiros da pasta onde os guardou (ajuste se a pasta se chamar diferente)
from core.maestro import MaestroEngine
from core.qobuz_provider import QobuzProvider

async def main():
    print("1. A ligar o motor do Maestro...")
    engine = MaestroEngine()
    
    print("2. A carregar configurações padrão...")
    settings = QobuzDLSettings()
    
    print("3. A instalar o plugin da Qobuz...")
    plugin_qobuz = QobuzProvider(settings)
    engine.register_provider(plugin_qobuz)
    
    print("\n--- A TESTAR O ROTEAMENTO ---")
    # Vamos enviar uma URL falsa para ver se o Maestro sabe para quem a entregar
    urls_teste = ["https://play.qobuz.com/album/123456789"]
    await engine.process_batch(urls_teste)
    
    print("\n[✔] Teste concluído sem falhas críticas!")

if __name__ == "__main__":
    asyncio.run(main())