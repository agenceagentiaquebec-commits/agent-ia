# ---------------------------------------------------------
# IMPORTS + CHARGEMENT DU .ENV
# ---------------------------------------------------------

from fastapi import FastAPI, Request
from fastapi.responses import Response, StreamingResponse
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
last_text_to_speak = None  # on stocke le texte

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
        return '{"final_reply": "Je suis désolée, une erreur est survenue.", "extracted_info": {}}'

# ---------------------------------------------------------
# STREAMING AUDIO (vrai streaming ElevenLabs)
# ---------------------------------------------------------


def generate_audio_stream(text):
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVEN_VOICE_ID}/stream"

    headers = {
        "xi-api-key": ELEVEN_API_KEY,
        "Content-Type": "application/json"
    }

    data = {
        "text": text,
        "model_id": "eleven_turbo_v2_5",
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.8,
            "style": 0.3,
            "use_speaker_boost": True
        }
    }

    try:
    # stream=True -> réception chunk par chunk
        response = requests.post(url, json=data, headers=headers, stream=True, timeout=30)

        if response.status_code != 200:
            print("Erreur ElevenLabs:", response.status_code, response.text)
            return None
    
        return response
    except Exception as e:
        print("Erreur streaming ElevenLabs:", e)
        return None

# ---------------------------------------------------------
# Endpoint Twilio (POST)
# ---------------------------------------------------------

@app.post("/voice")
async def voice(request: Request):
    global conversation_state, last_text_to_speak

    data = await request.form()
    print("Twilio a bien appelé /voice")
    user_message = data.get("SpeechResult", "")

    # Si aucun message n'a été dit -> jouer l'intro
    if not user_message:
        last_text_to_speak = (
            "Bonjour, ici Emily des Constructions P Gendreau. "
            "Merci d'avoir appelé aujourd'hui. Comment puis-je vous aider?"
        )
        return Response(
            content=f"""<Response>
<Play>https://emily-backend-996818120694.northamerica-northeast1.run.app/voice-file</Play>
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
        analysis = {"final_reply": "Je suis désolée, une erreur est survenue.", "extracted_info": {}}

    conversation_state.update(analysis.get("extracted_info", {}))

    # On stocke le texte, pas le stream
    last_text_to_speak = analysis["final_reply"]

    # Emily parle -> puis Twilio écoute
    return Response(
        content=f"""<Response>
<Play>https://emily-backend-996818120694.northamerica-northeast1.run.app/voice-file</Play>
<Pause length="1"/>
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
        timeout="3"
        enhanced="true"
        speechModel="default"/>
</Response>""",
        media_type="application/xml"
    )

# ---------------------------------------------------------
# Endpoint STREAMING audio stable
# ---------------------------------------------------------

@app.get("/voice-file")
def voice_file():
    global last_text_to_speak

    if not last_text_to_speak:
        return Response("No audio", status_code=404)
    
    stream = generate_audio_stream(last_text_to_speak)
    
    if stream is None:
        return Response("Erreur audio", status_code=500)
    
    
    def audio_generator():
        for chunk in stream.iter_content(chunk_size=1024):
            if chunk:
                yield chunk

    return StreamingResponse(audio_generator(), media_type="audio/wav")


@app.get("/intro")
def intro_file():
    intro_text = (
        "Bonjour, ici Emily des Constructions P Gendreau. "
        "Merci d'avoir appelé aujourd'hui. Comment puis-je vous aider?"
    )
    intro_stream = generate_audio_stream(intro_text)

    def audio_generator():
        for chunk in intro_stream.iter_content(chunk_size=1024):
            if chunk:
                yield chunk

    return StreamingResponse(audio_generator(), media_type="audio/wav")

# -------------------------------------------------------------------
# Lancer le serveur
# -------------------------------------------------------------------

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))