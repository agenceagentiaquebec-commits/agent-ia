# ---------------------------------------------------------
# IMPORTS + CHARGEMENT DU .ENV
# ---------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.responses import Response, FileResponse
from dotenv import load_dotenv
from openai import OpenAI
from threading import Lock
import os
import requests
import json
import uuid
import subprocess
import threading

# Charger ton fichier .env
load_dotenv()

ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI()

conversation_state = {}
last_audio_file = None  # on stock un fichier WAV, pas un stream
pending_audio_file = None # Fichier généré en arrière-plan
last_call_sid = None # Pour détecter un nouvel appel

# -------------------------------------------------------------
# Génération WAV + Conversion FFMPEG
# -------------------------------------------------------------

def generate_wav_file(text):
    global pending_audio_file

    # 1. Génération Elevenlabs
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}"
    headers = {"xi-api-key": ELEVEN_API_KEY, "Content-Type": "application/json"}
    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "output_format": "wav",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.3,
            "use_speaker_boost": True
        }
    }

    response = requests.post(url, json=data, headers=headers)
    if response.status_code != 200:
        print("Erreur ElevenLabs", response.status_code, response.text)
        return None
    
    raw_filename = f"/tmp/{uuid.uuid4()}_raw.wav"
    with open(raw_filename, "wb") as f:
        f.write(response.content)

    # 2. Conversion FFMPEG -> WAV PCM 16 kHz mono
    final_filename = f"/tmp/{uuid.uuid4()}.wav"
    ffmpeg_cmd = [
        "ffmpeg", "-y",
        "-i", raw_filename,
        "-ac", "1",
        "-ar", "16000",
        "-acodec", "pcm_s16le",
        final_filename
    ]

    try:
        subprocess.run(ffmpeg_cmd, check=True)
        pending_audio_file = final_filename
        return final_filename
    except Exception as e:
        print("Erreur conversion ffmpeg:", e)
        return None

# ---------------------------------------------------------
# Fonction d'analyse OpenAI
# ---------------------------------------------------------

def analyze_message(user_message, conversation_state):
    prompt = f"""
Tu es Emily, agente virtuelle pour Construction P Gendreau.

Voici l'état actuel de la conversation :
{conversation_state}

Voici ce que le client vient de dire :
"{user_message}"

Analyse ce message et retourne STRICTEMENT un JSON brut.
IMPORTANT :
- Pas de ```json
- Pas de ```
- Pas de texte avant ou après
- Seulement du JSON valide

Le JSON doit contenir :
- intent
- extracted_info
- missing_info
- next_question
- reformulation
- final_reply
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {"role": "system", "content": "Tu es Emily. Réponds STRICTEMENT en JSON brut, sans ```json, sans ```."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content

    except Exception as e:
        print("Erreur OpenAI:", e)
        return '{"final_reply": "Je suis désolée, une erreur est survenue."}'

# ---------------------------------------------------------
# Thread de génération asynchrone
# ---------------------------------------------------------

def background_generation(user_message):
    global last_audio_file, pending_audio_file

    analysis_json = analyze_message(user_message, conversation_state)
    
    try:
        analysis = json.loads(analysis_json)
    except:
        analysis = {"final_reply": "Je suis désolée, une erreur est survenue.", "extracted_info": {}}

    conversation_state.update(analysis.get("extracted_info", {}))

    # Génération audio
    final_reply = analysis.get("final_reply", "Je suis désolée, une erreur est survenue.")
    generate_wav_file(final_reply)

    # Quand prêt -> devient la réponse officielle
    last_audio_file = pending_audio_file

# ---------------------------------------------------------
# Endpoint Twilio (POST)
# ---------------------------------------------------------

@app.post("/voice")
async def voice(request: Request):
    global last_audio_file, pending_audio_file, last_call_sid

    data = await request.form()
    print("Twilio a bien appelé /voice")
    call_sid = data.get("CallSid")
    user_message = data.get("SpeechResult", "")
    

    # 1. Réponse instantanée
    instant_reply = "/tmp/instant.wav"

    # -------------------------------------------------
    # 1. Détection d'un nouvel appel -> jouer l'intro
    # -------------------------------------------------
    if call_sid != last_call_sid:
        last_call_sid = call_sid
        generate_wav_file(
            "Bonjour, ici Emily des Constructions P Gendreau. "
            "Merci d'avoir appelé aujourd'hui. Comment puis-je vous aider?"
        )
        # Attendre que le fichier soit prêt
        if pending_audio_file:
            os.rename(pending_audio_file, instant_reply)
        
        last_audio_file = instant_reply
        
        return Response(
            content=f"""<Response>
<Play>https://emily-backend-996818120694.northamerica-northeast1.run.app/voice-file</Play>
<Redirect>/listen</Redirect>
</Response>""",
            media_type="application/xml"
        )

    # -------------------------------------------------
    # 2. Réponse instantanée pour les tours suivants
    # -------------------------------------------------

        # Génère une phrase instantanée une seule fois
        generate_wav_file("hum, parfait, bien reçu...")

        if pending_audio_file:
            os.rename(pending_audio_file, instant_reply)

        last_audio_file = instant_reply

    # 3. Lance la génération en arrière-plam
    threading.Thread(target=background_generation, args=(user_message,)).start()

    # 4. Twilio joue la réponse instantanée
    return Response(
        content=f"""<Response>
<Play>https://emily-backend-996818120694.northamerica-northeast1.run.app/voice-file</Play>
<Redirect>/listen</Redirect>
</Response>""",
            media_type="application/xml"
        )

# ----------------------------------------
# la place où Twilio écoute
# ----------------------------------------

@app.post("/listen")
async def listen():
    return Response(
        content="""<Response>
<Gather input="speech"
        language="fr-FR"
        action="/voice"
        method="POST"
        speechTimeout="auto"
        timeout="3"/>
</Response>""",
        media_type="application/xml"
    )
#removed from Gather()
# enhanced="true"
#        speechModel="default"

# ---------------------------------------------------------
# Endpoint WAV Final
# ---------------------------------------------------------

@app.get("/voice-file")
def voice_file():
    global last_audio_file

    # Toujours renvoyer un fichier valide
    if last_audio_file and os.path.exists(last_audio_file):
        return FileResponse(last_audio_file, media_type="audio/wav")

    #FallBack ultime
    if os.path.exists("/tmp/instant.wav"):
        return FileResponse("/tmp/instant.wav", media_type="audio/wav")
    
    return Response("No audio", status_code=200)

# -------------------------------------------------------------------
# Lancer le serveur
# -------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))