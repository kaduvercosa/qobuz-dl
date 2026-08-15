#!/usr/bin/env python3
"""
Qobuz-DL Nothing OS Edition - Entry Point Launcher
"""
import uvicorn
import os
import sys

def main():
    print("=" * 60)
    print("  ( NOTHING )  QOBUZ-DL // LOSSLESS AUDIO ENGINE")
    print("  Version: 2.4.0-nothing | High-Res FLAC 24-Bit/192kHz")
    print("=" * 60)
    print("  [>] Interface Web: http://localhost:8000")
    print("  [>] Pressione Ctrl+C para encerrar o servidor.")
    print("=" * 60)
    
    # Ensure current directory is in python path
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )

if __name__ == "__main__":
    main()
