# Étape 1 : construire l'interface
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Étape 2 : serveur Python
FROM python:3.11-slim
RUN useradd -m -u 1000 user
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY --chown=user . .
COPY --from=frontend --chown=user /app/frontend/dist ./frontend/dist
USER user
ENV ICA_DATA_DIR=/app/data PORT=7860
EXPOSE 7860
CMD ["sh", "-c", "uvicorn ica.api:app --host 0.0.0.0 --port ${PORT}"]
