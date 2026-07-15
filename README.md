# 7Seven Cargo MVP Tracking

A minimal FastAPI project scaffold for the 7Seven Cargo MVP tracking service.

## Features
- Health endpoint at `/health`
- Environment-based settings via `.env`
- Async HTTP integrations for TomTom and OpenWeather
- Pending placeholder for Trafegus integration

## Setup
1. Create a virtual environment.
2. Install dependencies:
   ```bash
   pip install -r requirements.txt
   ```
3. Copy `.env.example` to `.env` and fill in any required values.
4. Run the app:
   ```bash
   uvicorn app.main:app --reload
   ```

## Testing
Run:
```bash
pytest
```
