"""Browser E2E only: simulated provider facts, isolated DB, real B HTTP routes.
Never used by the normal application; no production mock switch is installed.
"""
from pathlib import Path
import os
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.main import app
from app.recommendation_api import recommendation_engine
from test_recommendations import engine
import uvicorn

app.dependency_overrides[recommendation_engine] = engine
if __name__ == '__main__':
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ['E2E_BACKEND_PORT']),log_level='warning')
