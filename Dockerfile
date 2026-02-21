FROM python:3.11-slim

# Mettre à jour et installer ffmpeg + dépendances système nécessaires 
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg libsndfile1 \
    build-essential \
    gcc \
    libffi-dev \
    libssl-dev \
&& rm -rf /var/lib/apt/lists/*

#Créer un utilisateur non-root pour exécuter l'app (meilleure sécurité)
RUN useradd --create-home appuser
WORKDIR /app
COPY --chown=appuser:appuser requirements.txt .

# Installer les dépendances Python en tant qu'utilisateur root (pip nécessite accès)
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code (propriétaire appuser)
COPY --chown=appuser:appuser . .

# Exposer le port (Optionnel, Cloud Run ignore EXPOSE mais utile localement)
EXPOSE 8080

# Exécuter en tant qu'utilisateur non-root
USER appuser

# Lancer ton app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]