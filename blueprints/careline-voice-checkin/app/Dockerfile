FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml .
RUN pip install --no-cache-dir fastapi uvicorn httpx
COPY careline ./careline
COPY web ./web
EXPOSE 8100
CMD ["uvicorn", "careline.main:app", "--host", "0.0.0.0", "--port", "8100"]
