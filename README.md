# Sailing Route Optimizer

This project provides an intelligent sailing route planning system for both competitive sailors and recreational boaters. It calculates optimal routes by considering weather conditions, marine obstacles, and vessel characteristics.

## Features

- Smart route planning using advanced pathfinding algorithms (A*, Dijkstra)
- Live weather data integration (OpenWeatherMap API)
- Obstacle management with a database of marine hazards and restricted areas
- Vessel profiles with customizable polar characteristics
- Route statistics and estimated times
- REST API built with FastAPI and Python
- PostgreSQL with PostGIS support for geospatial data (production)
- SQLite support for local development and testing

## Project Structure

```
sailing-regats-route-calculator/
├── app/
│   ├── api/
│   ├── core/
│   ├── db/
│   ├── models/
│   ├── schemas/
│   ├── services/
│   └── main.py
├── tests/
│   └── database/
├── pyproject.toml
├── README.md
└── ...
```

## Environment Configuration

1. Install Poetry:

    ```bash
    pip install poetry
    ```

2. Install dependencies:

    ```bash
    poetry install
    ```

3. Activate the virtual environment:

    ```bash
    poetry shell
    # If it fails, try:
    poetry self add poetry-plugin-shell
    ```

4. Configure environment variables:

    - For development, create a `.env.dev` file in the project root with at least:

        ```
        SQLALCHEMY_DATABASE_URI=sqlite+aiosqlite:///./database.db
        DEBUG=True
        ```

    - For production, configure your PostgreSQL/PostGIS connection string.

## Running the Application

To start the FastAPI server:

```bash
uvicorn app.main:app --reload
```

The API documentation will be available at `http://127.0.0.1:8000/docs`.

## Testing

To run db unit tests:

```bash
poetry run pytest app/test/database/database.py -v
```

Additional API tests will be implemented soon and run similarly.

## Notes

- The backend uses SQLite for local development and PostgreSQL/PostGIS for production.
- Environment-specific settings are managed via `.env.dev` and `.env.production` files.
- For weather data, obtain an API key from OpenWeatherMap and add it to your environment variables if needed.

## License

This project is licensed under the MIT License.