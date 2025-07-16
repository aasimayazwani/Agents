### Quick start
```bash
git clone <repo>
cd <repo>
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export OPENAI_API_KEY=sk-...
uvicorn app.main:app --reload
