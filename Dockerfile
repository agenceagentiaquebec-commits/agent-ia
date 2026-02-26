
# Base image Python 3.11 slim (rapide et légère)

FROM python:3.11-slim

# Mettre à jour et installer ffmpeg + dépendances système nécessaires 
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Création du dossier de l'application

WORKDIR /app

# Copie des fichiers de dépandances
COPY requirements.txt .

# Installer les dépendances Python en tant qu'utilisateur root (pip nécessite accès)
RUN pip install --no-cache-dir -r requirements.txt

# Copier le code source
COPY . .

# Sécurité : exécuter en tant qu'utilisateur non-root
RUN useradd -m emilyuser
USER emilyuser

# Exposer le port (Optionnel, Cloud Run ignore EXPOSE mais utile localement)
EXPOSE 8080

# Lancer ton app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]