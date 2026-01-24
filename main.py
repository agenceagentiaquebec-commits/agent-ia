# ---------------------------------------------------------
# IMPORTS + CHARGEMENT DU .ENV
# ---------------------------------------------------------

from fastapi import FastAPI, Request
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
last_audio_bytes = None
intro_audio_bytes = None

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

    return response.choices[0].message.content


# ---------------------------------------------------------
# Génération AUDIO EN MÉMOIRE (pas de fichiers)
# ---------------------------------------------------------


def generate_audio_bytes(text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream"

    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json",
        "Accept": "audio/wav"
    }

    data = {
        "text": text,
        "model_id": "eleven_turbo_v2",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.3,
            "use_speaker_boost": True
        }
    }

    response = requests.post(url, json=data, headers=headers)
    print("Status code:", response.status_code)
    print("Headers:", response.headers)
    print("Audio lenght:", len(response.content))
    return response.content

#----------------------------------------------------------------------------------
# Générer l'intro une seule fois
# ---------------------------------------------------------------------------------

def load_intro_audio():
    global intro_audio_bytes
    if intro_audio_bytes is None:
        intro_text = (
            "Bonjour, ici Emily des Constructions P Gendreau. "
            "Merci d'avoir appelé aujourd'hui. Comment puis-je vous aider?"
        )
        intro_audio_bytes = generate_audio_bytes(intro_text)

load_intro_audio()

print("Intro audio lenght:", len(intro_audio_bytes))

# ---------------------------------------------------------
# Endpoint Twilio (POST)
# ---------------------------------------------------------

@app.post("/voice")
async def voice(request: Request):
    global conversation_state, last_audio_bytes

    data = await request.form()
    print("Twilio a bien appelé /voice")
    user_message = data.get("SpeechResult", "")

    # Si aucun message n'a été dit -> jouer le message d'accueil fixe
    if not user_message:
        return Response(
            content="""<Response>
<Play>https://agent-ia-rrlb.onrender.com/intro</Play>
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
            content="<Response><Say>Une erreur est survenue, je suis désolé.</Say></Response>",
            media_type="application/xml"
        )

    conversation_state.update(analysis["extracted_info"])

    final_reply = analysis["final_reply"]
    
    # Généer l'audio EN MÉMOIRE
    last_audio_bytes = generate_audio_bytes(final_reply)

    # Emily parle -> puis Twilio écoute
    return Response(
        content=f"""<Response>
<Play>https://agent-ia-rrlb.onrender.com/voice-file</Play>
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
# Endpoint qui sert l'audio depuis la mémoire
# ---------------------------------------------------------

@app.get("/voice-file")
def voice_file():
    global last_audio_bytes
    if last_audio_bytes is None:
        return Response("No audio", status_code=404)
    return Response(last_audio_bytes, media_type="audio/wav")


@app.get("/intro")
def intro_file():
    global intro_audio_bytes
    return Response(intro_audio_bytes, media_type="audio/wav")

# -------------------------------------------------------------------
# Lancer le serveur
# -------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 10000)))