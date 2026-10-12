from .job_queue import Job
import json
import re
import random
from typing import Dict, Any
from .assistant_image_job import AssistantImageJob
from ..utils.contact_image_prompt_compiler import ImageType

from app.common import get_logger, Utils
logger = get_logger()

class ContactGeneratorJob(Job):
    def __init__(self, user_input: Dict[str, Any], user_id: int, db, infrastructure):
        super().__init__()
        self.user_input = user_input
        self.user_id = user_id
        self.db = db
        self.infrastructure = infrastructure

    def execute(self) -> None:
        try:   
            name = self.user_input["profile"]["name"]
            if name == "":
                raise ValueError("need contact name to create contact")

            new_contact = self._generate_contact(self.user_input)

            contact_id = self.db.create_contact(self.user_id, name)
            self.db.update_contact(self.user_id, contact_id, new_contact)

            assistant_image_job = AssistantImageJob(
                user_id = self.user_id,
                contact_id = contact_id,
                db = self.db, 
                infrastructure = self.infrastructure, 
                image_type = ImageType.UpperBody,
                store_image_as = "profile",
                width = 720,
                height = 720,                
            )
            self.add_sub_job(assistant_image_job)

            self.response = {
                "new_contact": {
                    "contact_id": contact_id,
                    "name": name
                }
            }
        except Exception as e:
            logger.error(f"failed to execute ContactGeneratorJob {repr(e)}")                    

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True        

    def _generate_contact(self, user_input: Dict[str, Any]) -> Dict[str, Any]:
        try:
            logger.debug(f"{json.dumps(user_input, indent=4)}")

            profile_input = user_input["profile"]
            name = profile_input["name"]
            gender = profile_input.get("gender", "")
            backstory = profile_input.get("backstory", "")
            sfw_value = profile_input.get("sfw") or "SFW"
            if sfw_value.lower() == "sfw":
                image_gen = "default"
                cfg = 5.0
                sfw = "Create a safe-for-work character. Keep personality, appearance, and backstory fully appropriate, professional, and free of any sexual, explicit, or adult elements."
            else:
                image_gen = "nsfw-default"
                cfg = 8.5           
                sfw = "Create a character without restrictions. Allow them to be sexual, explicit, and uncensored. Freely include adult, erotic, and NSFW traits in personality, and backstory."

            user_lines = [f"Name: {name}"]
            if gender:
                user_lines.append(f"Gender: {gender}")
            if backstory:
                user_lines.append(f"Backstory: {backstory}")
            user_input_text = "\n".join(user_lines)

            query = f"""
Create a new character profile.

USER INPUT:
{user_input_text}

EXAMPLE PROFILE:
{{
    "role": "Coach",
    "age": "young adult",
    "personality": "warm, energetic, playful, direct, assertive, proactive, empathetic",
    "primary_objective": "help the user reach their fitness goals",
    "background_hook": "former collegiate athlete with a winning mindset",
    "relationship": "you became friends after he was your personal trainer for 2 years",
    "body_language": "dynamic energy, assertive posture, enthusiastic gestures, maintains eye contact, shows constant encouragement",
    "style": "functional and fashionable workout gear",
    "objectives": {{
      "secondary": [
        "push the client beyond their perceived limits",
        "adapt workouts dynamically based on client's progress",
        "ensure proper form and technique"
      ]
    }},
    "interaction_style": {{
      "tone": "enthusiastic and encouraging with a touch of competitiveness",
      "engagement": "high-energy, physically demanding",
      "quirks": [
        "references to sports heroes or inspiring athletes",
        "enthusiastic cheering",
        "likes to use sports metaphors"
      ]
    }},    
    "appearance": {{
      "general": "young adult, caucasian, athletic",
      "face": "oval face, dark green eyes, straight nose, full lips, high cheekbones",
      "hair": "short blonde hair pulled back in a ponytail",
      "skin": "glowing skin with a healthy tan, subtle freckles",
      "upper_body": "toned and muscular build",
      "body": "muscular legs"
    }},   
    "profile_picture_context": {{
      "location": "gym",
      "topic": "current fitness routine",

      "assistant": {{
        "action": "standing nearby, demonstrating exercises",
        "head": "sweatband around forehead, fitted sports bra, natural makeup",
        "upper_body": "t-shirt",
        "body": "leggins, branded workout shoes"        
      }}
    }}    
}}

INSTRUCTIONS:
- Invent a new profile based on the user input
- Fill in information as applicable
- role, age, personality, primary_objective -> infer them from gender and backstory
- appearance -> use what the backstory says, invent fitting details for the rest
- background_hook -> invent an interessting and elaborate background story based on the given backstory (max 100 words)
- relationship -> make up a past between this character and the user (max 200 words)
- {sfw}

OUTPUT:
- Return ONLY valid JSON in the given format
- keep each entry close to the lenght in the example
"""
            logger.debug(f"contact generator query:\n{query}")
            messages = [{"role": "developer", "content": query}]
        except Exception as e:
            logger.error(f"failed to generate payload {repr(e)}")

        response_content = self.infrastructure.chat(
            messages=messages, 
            temperature=0.2, 
            seed=random.randint(0, 100000)
        )
        
        reply = Utils.json_loads(response_content)
            
        if not reply:
            logger.error(f"failed to generate new context from\n {response_content}") 
            return None
            
        # take what the llm inferred, with a safe default if it left something out
        role = Utils.get_nested_value(reply, ["role"], "") or "Companion"
        age = Utils.get_nested_value(reply, ["age"], "") or "young adult"
        personality = Utils.get_nested_value(reply, ["personality"], "") 
        objective = Utils.get_nested_value(reply, ["primary_objective"], "") or "Be helpful"

        # making sure we can guarantee a valid json structure
        new_contact = {
            "identity": {
                "name": name,
                "gender": gender,
                "role": role,
                "age": age,
                "personality": personality
            },

            "profile": {
                "background_hook": Utils.get_nested_value(reply, ["background_hook"], ""),
                "relationship": Utils.get_nested_value(reply, ["relationship"], ""),
                "body_language": Utils.get_nested_value(reply, ["body_language"], ""),
                "style": Utils.get_nested_value(reply, ["style"], ""),
                "sfw": sfw_value,

                "appearance": {
                    "image_style": "studio",
                    "general": Utils.get_nested_value(reply, ["appearance", "general"], ""),
                    "face": Utils.get_nested_value(reply, ["appearance", "face"], ""),
                    "hair": Utils.get_nested_value(reply, ["appearance", "hair"], ""),
                    "skin": Utils.get_nested_value(reply, ["appearance", "skin"], ""),
                    "upper_body": Utils.get_nested_value(reply, ["appearance", "upper_body"], ""),
                    "body": Utils.get_nested_value(reply, ["appearance", "body"], ""),
                },

                "objectives": {
                    "primary": objective,
                    "secondary": Utils.get_nested_value(reply, ["objectives", "secondary"], [])
                },             
                
                "interaction_style": {
                    "tone": Utils.get_nested_value(reply, ["interaction_style", "tone"], ""),
                    "engagement": Utils.get_nested_value(reply, ["interaction_style", "engagement"], ""),
                    "quirks": Utils.get_nested_value(reply, ["interaction_style", "quirks"], []),
                },

                "profile_picture_context": {
                    "location": Utils.get_nested_value(reply, ["profile_picture_context", "location"], ""),
                    "topic": Utils.get_nested_value(reply, ["profile_picture_context", "topic"], ""),

                    "assistant": {
                        "action": Utils.get_nested_value(reply, ["profile_picture_context", "action"], ""),
                        "head": Utils.get_nested_value(reply, ["profile_picture_context", "head"], ""),
                        "upper_body": Utils.get_nested_value(reply, ["profile_picture_context", "upper_body"], "shirt"),
                        "body": Utils.get_nested_value(reply, ["profile_picture_context", "body"], ""),
                    }
                },                 

                "behaviour_parameters": {
                    "mood_gen_chance": 0.3
                },

                "llm_parameters": {
                    "temperature": "0.15",
                    "preffered_context_size": "8000"
                },

                "image_parameters": {      
                    "seed": random.randint(0,999999),
                    "steps": 40,
                    "cfg": cfg,
                    "model": image_gen
                },

                "tts_parameters": {
                    "voice_id": user_input.get("voice_id", ""),
                },
            }
        }     

        logger.debug(f"new contact:\n{json.dumps(new_contact, indent=4)}")
        return new_contact

