FROM python:3.11-slim

# Installer ffmpeg
RUN apt-get update && apt-get install -y ffmpeg libsndfile1

#Installer les dépendances Python
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copier ton code
COPY . .

# Lancer ton app
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]