# ---------------------------------------------------------
# IMPORTS + CHARGEMENT DU .ENV
# ---------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.responses import Response
from dotenv import load_dotenv
from openai import OpenAI
import os
import requests
import json

# Charger ton fichier .env
load_dotenv()



ELEVEN_API_KEY = os.getenv("ELEVEN_API_KEY")
ELEVEN_VOICE_ID = os.getenv("ELEVEN_VOICE_ID")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


print("OPENAI KEY LOADED:", OPENAI_API_KEY)

client = OpenAI(api_key=OPENAI_API_KEY)
app = FastAPI()

conversation_state = {}

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

    response = client.chat.completions.create(
        model="gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Tu es Emily. Réponds STRICTEMENT en JSON brut, sans ```json, sans ```."},
            {"role": "user", "content": prompt}
        ]
    )

    print("RAW OPENAI RESPONSE:", response)
    return response.choices[0].message.content


# ---------------------------------------------------------
# Fonction pour générer l'audio Emily (WAV compatible Twilio)
# ---------------------------------------------------------
import subprocess

def generate_audio(text, output_filename="emily_twilio.wav"):
    # Générer l'audio Elevenlabs (format non compatible avec twilio)
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream"

    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/wav"
    }

    data = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.3,
            "use_speaker_boost": True
        }
    }



    # Fichier temporaire ElevenLabs
    raw_file = "raw_eleven.wav"

    response = requests.post(url, json=data, headers=headers)

    with open(raw_file, "wb") as f:
        f.write(response.content)

    #Convertir en WAV PCM 16-bit mono 16Khz compatible Twilio
    subprocess.run([
        "ffmpeg",
        "-y",
        "-i",raw_file,
        "-ac", "1",   #mono
        "-ar", "16000", #16 kHz
        "-acodec", "pcm_s16le", #PCM 16-bit
        "-af", "silenceremove=start_periods=1:start_duration=0.1:start_threshold=-40dB:stop_periods=1:stop_duration=0.1:stop_threshold=-40dB",
        output_filename
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)



def generate_intro_audio():
    intro_text = (
        "Bonjour, ici Emily des Constructions P Gendreau."
        "Merci d'avoir appelé aujourd'hui. Comment puis-je vous aider?"
    )
    generate_audio(intro_text, output_filename="emily_intro.wav") 









# ---------------------------------------------------------
# Endpoint pour générer un message d'accueil (test)
# ---------------------------------------------------------

TEXT = """
Bonjour… Emily des Construction PGendreau… merci d’avoir appelé aujourd’hui…
Comment puis‑je vous aider?
"""

@app.get("/generate-voice")
def generate_voice():
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream"

    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/wav"
    }

    data = {
        "text": TEXT,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.3,
            "use_speaker_boost": True
        }
    }

    response = requests.post(url, json=data, headers=headers)

    with open("emily.wav", "wb") as f:
        f.write(response.content)

    return {"status": "ok", "message": "Audio generated", "file": "emily.wav"}


# ---------------------------------------------------------
# Endpoint Twilio (POST) → analyse + réponse vocale
# ---------------------------------------------------------

@app.post("/voice")
async def voice(request: Request):
    global conversation_state

    data = await request.form()
    user_message = data.get("SpeechResult", "")

    # Si aucun message n'a été dit -> jouer le message d'accueil fixe
    if not user_message:
        return Response(
            content="""<Response>
<Play>https://emily-agent.ngrok.app/intro</Play>
<Pause length="1"/>
<Redirect>/listen</Redirect>
</Response>""",
            media_type="application/xml"
        )

    # Analyse OpenAI
    analysis_json = analyze_message(user_message, conversation_state)

    try:
        analysis = json.loads(analysis_json)
    except:
        return Response(
            content="""<Response>
<Say>Une erreur est survenue, je suis désolé.</Say>
</Response>""",
            media_type="application/xml"
        )

    conversation_state.update(analysis["extracted_info"])

    final_reply = analysis["final_reply"]
    generate_audio(final_reply, output_filename="emily_twilio.wav")

    # Emily parle -> puis Twilio écoute
    return Response(
        content="""<Response>
<Play>https://emily-agent.ngrok.app/voice-file</Play>
<Pause length="1"/>
<Redirect>/listen</Redirect>
</Response>""",
        media_type="application/xml"
    )

# la place où Twilio écoute
@app.post("/listen")
async def listen():
    return Response(
        content="""<Response>
<Gather input="speech"
        language="fr-FR"
        action="/voice"
        method="POST"
        speechTimeout="auto"
        timeout="3"
        enhanced="true"
        speechModel="default"/>
</Response>""",
        media_type="application/xml"
    )

# ---------------------------------------------------------
# Endpoint qui sert le fichier audio WAV
# ---------------------------------------------------------

@app.get("/voice-file")
def voice_file():
    return FileResponse("emily_twilio.wav", media_type="audio/wav")


@app.get("/intro")
def intro_file():
    return FileResponse("emily_intro.wav", media_type="audio/wav")