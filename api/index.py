import sys
import os

# Pastikan root project ada di path
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from app.main import app
from mangum import Mangum

# Handler untuk Vercel serverless
handler = Mangum(app, lifespan="off")
