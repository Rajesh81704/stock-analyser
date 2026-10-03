"""
Vercel Serverless Function Entry Point for FastAPI application
"""
import os
import sys

# Ensure project root directory is on Python path
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from web.app import app

# Export FastAPI ASGI instance for Vercel
app = app
handler = app
