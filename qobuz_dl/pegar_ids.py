from pyrogram import Client

# Usa a sessão que já foi criada -- não é necessário API_ID aqui.
app = Client("qobuz_session")

async def listar_meus_canais():
    async with app:
        print("\n=== LENDO SEUS CHATS RECENTES ===")
        # Lê as suas 20 conversas mais recentes
        async for dialog in app.get_dialogs(limit=20):
            if dialog.chat.title:
                print(f"Nome: {dialog.chat.title} | ID: {dialog.chat.id}")
        print("=================================\n")

if __name__ == "__main__":
    app.run(listar_meus_canais())