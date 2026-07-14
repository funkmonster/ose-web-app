.PHONY: playtest seed test

# Run the backend against a throwaway SQLite file — never touches data/campaign.db.
playtest:
	cd backend && DB_PATH=../data/playtest.db STATIC_DIR=static uvicorn main:app --reload --host 0.0.0.0 --port 8000

# Populate (or refresh) the scratch DB with a fake campaign/characters/log rows.
seed:
	python backend/scripts/seed_test_data.py data/playtest.db

test:
	cd backend && pytest
