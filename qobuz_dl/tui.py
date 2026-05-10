import sys
import logging
from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input, DataTable, Log, Static
from textual.binding import Binding

class TUILogHandler(logging.Handler):
    """Captura os logs padrão do Python e envia para a TUI."""
    def __init__(self, log_widget):
        super().__init__()
        self.log_widget = log_widget

    def emit(self, record):
        msg = self.format(record)
        # call_from_thread garante que a UI não quebre ao ser atualizada por outras threads
        self.log_widget.app.call_from_thread(self.log_widget.write_line, msg)

class StdoutRedirector:
    """Captura os prints normais (e do tqdm) e envia para a TUI."""
    def __init__(self, log_widget):
        self.log_widget = log_widget

    def write(self, string):
        if string.strip():
            self.log_widget.app.call_from_thread(self.log_widget.write_line, string.strip())

    def flush(self):
        pass

class QobuzTUI(App):
    """A interface interativa do Qobuz-DL Ultimate Edition."""
    
    TITLE = "🎵 QOBUZ-DL ULTIMATE EDITION"
    SUB_TITLE = "[ Motor FLAC Ativo ]"

    CSS = """
    Screen { layout: vertical; }
    #search_bar { dock: top; margin: 1 2; }
    #middle_container { height: 1fr; layout: horizontal; }
    #meta_panel { width: 35%; border: solid cyan; padding: 1 2; content-align: center middle; }
    #track_panel { width: 65%; border: solid yellow; }
    #bottom_panel { height: 15; border: solid green; dock: bottom; layout: vertical; }
    #sys_log { height: 1fr; }
    """

    BINDINGS = [
        Binding("ctrl+d", "toggle_dark", "Modo Escuro"),
        Binding("ctrl+c", "quit", "Sair/Abortar"),
    ]

    def __init__(self, qobuz_app, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.qobuz = qobuz_app
        self._original_stdout = sys.stdout

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(placeholder="Cole a URL do Qobuz (Álbum/Faixa/Playlist) e aperte Enter...", id="search_bar")
        
        with Horizontal(id="middle_container"):
            with Vertical(id="meta_panel"):
                yield Static("🖼️  [ Sistema Pronto ]\n\nAguardando links para download.", id="album_art")
            with Vertical(id="track_panel"):
                yield DataTable(id="tracklist")
                
        with Vertical(id="bottom_panel"):
            # O Textual suporta automaticamente as cores ANSI do color.py
            yield Log(id="sys_log", highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        table = self.query_one(DataTable)
        table.add_columns("Fila de Processamento", "Ação")
        
        log_widget = self.query_one(Log)
        
        # Injeta o redirecionamento
        self.tui_handler = TUILogHandler(log_widget)
        self.tui_handler.setFormatter(logging.Formatter('%(message)s'))
        logging.getLogger().addHandler(self.tui_handler)
        
        sys.stdout = StdoutRedirector(log_widget)

        log_widget.write_line("[*] Interface Terminal conectada ao motor Qobuz-DL.")
        log_widget.write_line(f"[*] Destino: {self.qobuz.directory}")

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        url = event.value.strip()
        if not url: return
        
        self.query_one(Input).value = ""
        log_widget = self.query_one(Log)
        
        if "qobuz.com" in url or "last.fm" in url:
            self.query_one("#album_art", Static).update(f"🔄 Processando URL:\n\n{url}")
            table = self.query_one(DataTable)
            table.add_row(url, "Enviado para o motor")
            
            # Dispara o download numa thread separada
            self.run_download(url)
        else:
            log_widget.write_line(f"[!] URL não suportada: {url}")

    @work(thread=True)
    def run_download(self, url: str) -> None:
        """Executa a lógica de core.py em background."""
        try:
            # Conexão direta com a sua função de download real
            self.qobuz.download_list_of_urls([url])
            self.app.call_from_thread(self.query_one("#album_art", Static).update, "✅ Operação Concluída!\n\nPronto para o próximo.")
        except Exception as e:
            self.app.call_from_thread(self.query_one(Log).write_line, f"\033[91m[!] Erro crítico na thread: {e}\033[0m")

    def on_unmount(self) -> None:
        """Limpa o redirecionamento ao fechar o programa."""
        sys.stdout = self._original_stdout
        logging.getLogger().removeHandler(self.tui_handler)
