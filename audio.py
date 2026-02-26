# audio.py
# Gestion de l'audio : ElevenLabs + ffmpeg (conversion PCM 16kHz mono)

import os
import uuid
import subprocess
import requests

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID")

def generate_audio(text: str, target_path: str | None = None) -> str | None:
    """
    Génère un fichier WAV compatible Twilio :
    - ElevenLabs TTS
    - Conversion PCM 16kHz mono via ffmpeg
    Retourne le chemin du fichier final ou None en cas d'erreur.
    """

    if not ELEVEN_API_KEY or not ELEVEN_VOICE_ID:
        print("ElevenLabs non configuré")
        return None
    
    # 1. Appel ElevenLabs
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "output_format": "wav",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.3
        }
    }

    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        if response.status_code != 200:
            print("Erreur ElevenLabs:", response.status_code, response.text)
            return None
        
        # 2 Sauvegarde du fichier brut
        raw_path = f"/tmp/{uuid.uuid4()}_raw.wav"
        with open(raw_path, "wb") as f:
            f.write(response.content)

        # 3. Conversion en PCM 16kHz mono
        final_path = target_path or f"/tmp/{uuid.uuid4()}.wav"
        ffmpeg_cmd = [
            "ffmpeg", "-y",
            "-i", raw_path,
            "-ac", "1",
            "-ar", "16000",
            "-acodec", "pcm_s16le",
            final_path
        ]
            
        subprocess.run(ffmpeg_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

        return final_path
    
    except Exception as e:
        print("Erreur génération audio:", e)
        return None