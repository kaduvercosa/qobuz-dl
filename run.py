#!/usr/bin/env python3
"""
Qobuz-DL Unified - Single Entry Point Launcher
Executes the full-stack application (Python Backend Engine + Web Client) together.
"""
import os
import sys
import subprocess
import signal
import time
import argparse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BACKEND_DIR = os.path.join(BASE_DIR, "backend")
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

def run_standalone(host="0.0.0.0", port=8000, reload=False):
    """Runs the FastAPI server serving both API endpoints and the full web frontend."""
    print("=" * 65)
    print("  🎵 QOBUZ-DL // UNIFIED LOSSLESS AUDIO ENGINE & WEB CLIENT")
    print(f"  🚀 Servidor Integrado Ativo em: http://localhost:{port}")
    print("  ✨ Motor de Download FLAC 24-Bit/192kHz + Interface Web")
    print("  🛑 Pressione Ctrl+C para encerrar.")
    print("=" * 65)

    sys.path.insert(0, BACKEND_DIR)
    os.chdir(BACKEND_DIR)
    
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info"
    )

def run_concurrent(host="0.0.0.0", port=8000, nextjs_port=3000):
    """Runs FastAPI backend on port 8000 and Next.js frontend on port 3000 concurrently."""
    print("=" * 65)
    print("  🎵 QOBUZ-DL // MODO CONCORRENTE (NEXT.JS + FASTAPI)")
    print(f"  ⚡ Backend API & WebSocket: http://localhost:{port}")
    print(f"  🎨 Frontend Next.js Dev:    http://localhost:{nextjs_port}")
    print("  🛑 Pressione Ctrl+C para encerrar ambos os serviços.")
    print("=" * 65)

    processes = []
    
    try:
        # 1. Start Python FastAPI backend
        backend_cmd = [sys.executable, "-m", "uvicorn", "app.main:app", "--host", host, "--port", str(port)]
        p_backend = subprocess.Popen(backend_cmd, cwd=BACKEND_DIR)
        processes.append(p_backend)

        # 2. Start Next.js frontend if npm is available
        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        try:
            p_frontend = subprocess.Popen([npm_cmd, "run", "dev", "--", "-p", str(nextjs_port)], cwd=FRONTEND_DIR)
            processes.append(p_frontend)
        except Exception as e:
            print(f"[!] Aviso: Node.js/npm não encontrado no PATH ({e}). Rodando apenas backend integrado.")

        # Monitor processes
        while True:
            time.sleep(1)
            for p in processes:
                if p.poll() is not None:
                    print(f"Processo {p.pid} finalizado com código {p.returncode}.")
                    return
    except KeyboardInterrupt:
        print("\nEncerrando todos os serviços...")
    finally:
        for p in processes:
            if p.poll() is None:
                p.terminate()
                try:
                    p.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    p.kill()
        print("Serviços finalizados com sucesso.")

def main():
    parser = argparse.ArgumentParser(description="Qobuz-DL Unified Launcher")
    parser.add_argument("--dev", action="store_true", help="Executa Next.js Dev Server e FastAPI concorrentemente")
    parser.add_argument("--port", type=int, default=8000, help="Porta do servidor backend (padrão: 8000)")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="Host do servidor (padrão: 0.0.0.0)")
    parser.add_argument("--reload", action="store_true", help="Habilita auto-reload no FastAPI")
    args = parser.parse_args()

    if args.dev:
        run_concurrent(host=args.host, port=args.port)
    else:
        run_standalone(host=args.host, port=args.port, reload=args.reload)

if __name__ == "__main__":
    main()
