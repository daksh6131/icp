#!/usr/bin/env python3
"""
Run the ICP CRM web application.
"""

import sys
from pathlib import Path

# Add current directory to path
sys.path.insert(0, str(Path(__file__).parent))

from crm.app import app

if __name__ == '__main__':
    print("\n" + "="*50)
    print("  ICP CRM - Lead Management System")
    print("="*50)
    print("\n  Open in browser: http://localhost:8080")
    print("\n  Press Ctrl+C to stop the server")
    print("="*50 + "\n")

    app.run(
        host='0.0.0.0',  # Allow connections from any IP
        port=8080,
        debug=True
    )
