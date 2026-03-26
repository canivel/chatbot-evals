FROM python:3.11-slim

WORKDIR /app

# Install uv
RUN pip install uv

# Copy project files
COPY pyproject.toml .
COPY README.md .

# Install dependencies
RUN uv sync --no-dev

# Copy source code
COPY . .

# Expose port
EXPOSE 8000

CMD ["uv", "run", "uvicorn", "evalplatform.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
