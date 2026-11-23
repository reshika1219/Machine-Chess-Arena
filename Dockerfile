FROM python:3.12-slim

# Stockfish from Debian lives in /usr/games
RUN apt-get update && apt-get install -y --no-install-recommends stockfish \
    && rm -rf /var/lib/apt/lists/*
ENV PATH="/usr/games:${PATH}"

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir -e ".[web]"

EXPOSE 8000
ENTRYPOINT ["aichess"]
CMD ["--help"]
