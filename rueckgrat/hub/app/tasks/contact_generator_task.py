from .task_queue import Task
from . import prompts
import json
import random
from typing import Dict, Any
from .assistant_image_task import AssistantImageTask
from ..utils.contact_image_prompt_compiler import ImageType
from ..utils.contact_model import Contact

from app.common import get_logger, Utils, IMAGE_STYLES, DEFAULT_IMAGE_STYLE
logger = get_logger()

class ContactGeneratorTask(Task):
    def __init__(self, user_input: Dict[str, Any], user_id: int, db, infrastructure):
        super().__init__(user_id=user_id)
        self.user_input = user_input
        self.db = db
        self.infrastructure = infrastructure

    def execute(self) -> None:
        try:   
            name = self.user_input["profile"]["name"]
            if name == "":
                raise ValueError("need contact name to create contact")

            contact = Contact.model_validate(self._generate_contact(self.user_input))

            contact_id = self.db.create_contact(self.get_user_id(), name)
            self.db.update_contact(self.get_user_id(), contact_id, contact)

            if self.user_input["profile"].get("companion"):
                self.db.set_contact_companion(self.get_user_id(), contact_id, True)

            assistant_image_task = AssistantImageTask(
                user_id = self.get_user_id(),
                contact_id = contact_id,
                db = self.db, 
                infrastructure = self.infrastructure, 
                image_type = ImageType.UpperBody,
                store_image_as = "profile",
                width = 720,
                height = 720,                
            )
            self.add_sub_task(assistant_image_task)

            self.response = {
                "new_contact": {
                    "contact_id": contact_id,
                    "name": name
                }
            }
        except Exception as e:
            logger.error(f"failed to execute ContactGeneratorTask {repr(e)}")                    

    def get_result(self) -> Dict[str, Any]:
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
            image_style = str(profile_input.get("image_style") or "").strip().lower()
            if image_style not in IMAGE_STYLES:
                logger.debug(f"unknown image style '{image_style}', using {DEFAULT_IMAGE_STYLE}")
                image_style = DEFAULT_IMAGE_STYLE
            if sfw_value.lower() == "sfw":
                image_gen = "default"
                cfg = 5.0
                sfw = prompts.CONTACT_GENERATOR_SFW_PART
            else:
                image_gen = "nsfw-default"
                cfg = 8.5           
                sfw = prompts.CONTACT_GENERATOR_UNRESTRICTED_PART

            user_lines = [f"Name: {name}"]
            if gender:
                user_lines.append(f"Gender: {gender}")
            if backstory:
                user_lines.append(f"Backstory: {backstory}")
            user_lines.append(f"Image style: {image_style.replace('_', ' ')} ({IMAGE_STYLES[image_style]['positive']})")
            user_input_text = "\n".join(user_lines)

            query = prompts.CONTACT_GENERATOR_PROMPT.format(user_input=user_input_text, sfw=sfw)
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
        role = Utils.get_nested_value(reply, ["role"], "Assistant")
        personality = Utils.get_nested_value(reply, ["personality"], "")
        objective = Utils.get_nested_value(reply, ["primary_objective"], "be helpful")        

        # making sure we can guarantee a valid json structure
        new_contact = {
            "identity": {
                "name": name,
                "gender": gender,
                "role": role,
                "personality": personality
            },

            "profile": {
                "background_hook": Utils.get_nested_value(reply, ["background_hook"], ""),
                "relationship": Utils.get_nested_value(reply, ["relationship"], ""),
                "body_language": Utils.get_nested_value(reply, ["body_language"], ""),
                "style": Utils.get_nested_value(reply, ["style"], ""),
                "sfw": sfw_value,

                "appearance": {
                    "image_style": image_style,
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

