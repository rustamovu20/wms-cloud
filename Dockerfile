# Containerisation option for the D-section improvement (VM -> container).
# Build:  docker build -t nimbus-wms .
# Run:    docker run -p 8000:8000 nimbus-wms
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

RUN python -c "import app; app.init_db()"

EXPOSE 8000
CMD ["gunicorn", "--workers", "3", "--bind", "0.0.0.0:8000", "app:app"]
