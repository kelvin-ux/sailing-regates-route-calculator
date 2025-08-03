# README

## Environment Configuration

To set up the development environment, follow these steps:

```bash
pip install poetry

poetry install

poetry shell # If dosen't work install from command bellow and retry 

poetry self add poetry-plugin-shell
```

## Run the Application

Once the environment is ready, you can start the FastAPI server by using one of those commands:

```bash
fastapi run

uvicorn app.main:app --reload
```

API will be available at `http://127.0.0.1:8000/docs` or `http://0.0.0.0:8000/docs` by default.

## Tests 

Test are available runage:

```bash
poetry run pytest app/test/database/database.py -v # database module only

# API test to be implemented
```