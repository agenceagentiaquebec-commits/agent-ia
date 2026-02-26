# llm.py
# Intelligence d'Emily : analyse, empathie, questions, résumé final

import os
import json
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)


# ------------------------------------------------------
# 1. Analyse d'un message utilisateur
# ------------------------------------------------------

def analyze_message(user_message: str, extracted_info: dict):
    """
    Analyse le message utilisateur et renvoie un JSON structuré :
    {
        "intent": "...",
        "extracted_info": {...},
        "missing_info": [...],
        "empathy": "...",
        "next_question": "...",
        "final_reply": "..."
    }
    """

    prompt = f"""
Tu es Emily, agente virtuelle professionnelle pour Construction P. Gendreau.

Ton rôle :
- comprendre le message de l'utilisateur
- répondre avec empathie
- extraire les informations importantes
- déterminer ce qui manque
- poser la prochaine question logique
- produire une réponse naturelle et utile

Voici les informations déjà extraites :
{json.dumps(extracted_info, ensure_ascii=False)}

Voici le message utilisateur :
"{user_message}"

Tu dois retourner STRICTEMENT un JSON valide, sans texte avant ou après.and

Le JSON doit contenir :
- "intent" : intention principale
- "extracted_info" : dictionnaire mis à jour
- "missing_info" : liste des infos manquantes parmi :
    ["nom", "prenom", "adresse", "ville", "code_postal", "telephone", "raison_appel", "budget"]
- "empathy" : une phrase empathique adaptée au problème
- "next_question" : la prochaine question logique pour compléter les infos
- "final_reply" : la résponse complète d'Emily (empathie + question)
"""
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Tu es Emily, agente virtuelle professionnelle. Réponds uniquement en JSON brut"},
                {"role": "user", "content": prompt}
            ]
        )

        content = resp.choices[0].message["content"]
        return json.loads(content)
    
    except Exception as e:
        print("Erreur analyse LLM:", e)
        return {
            "intent": "inconnu",
            "extracted_info": extracted_info,
            "missing_info": [],
            "empathy": "Je suis désolée, une erreur est survenue.",
            "next_question": "Pouvez-vous reformuler s'il vous plaît ?",
            "final_reply": "Je suis décolée, une erreur est survenue."
        }
    
# ------------------------------------------------------------------
# 2. Résumé final structuré
# ------------------------------------------------------------------

def generate_final_summary(extracted_info: dict, intent: str):
    """
    Génère un résumé final structuré pour Google Sheets + email.
    """

    prompt = f"""
Tu es Emily, agente virtuelle.

Voici les informations extraites :
{json.dumps(extracted_info, ensure_ascii=False)}

Intent principale : {intent}

Génère STRICTEMENT un JSON avec :
- "resume_conversationnel"
- "intent_principale"
- "actions_a_prendre"
"""
    
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": "Tu es Emily. Réponds uniquement en JSON brut."},
                {"role": "user", "content": prompt}
            ]
        )

        return json.loads(resp.choices[0].message["content"])
    
    except Exception as e:
        print("Erreur résumé LLM:", e)
        return {
            "resume_conversationnel": "Résumé indisponible.",
            "intent_principale": intent,
            "actions_a_prendre": "Vérifier manuellement."
        }