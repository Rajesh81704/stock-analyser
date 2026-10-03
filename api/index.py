"""
Vercel Serverless Function Entry Point for FastAPI application
"""
import os
import sys

# Ensure project root directory is on Python path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from web.app import app

# Export FastAPI instance for Vercel
app = app
