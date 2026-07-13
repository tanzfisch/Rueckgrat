from .job_queue import Job
from typing import Dict, Any
import json
import re
import random

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

class FindAnswerJob(Job):
    def __init__(self, question: str, information: str, infrastructure):
        super().__init__()
        self.question = question
        self.information = information
        self.infrastructure = infrastructure

    def execute(self) -> None:
        try:
            self.answer = self._find_answer()
        except Exception as e:
            logger.error(f"failed to update context {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.answer
       
    def _find_answer(self):
        try:
            messages = []
            query = f"""
Find the answer to a search query in a given text. 

TEXT:
{self.information}

SEARCH QUERY:
{self.question}

Respond with a json structure like this:
{{
    "answer": "the answer to the question",
    "quality": 1-10
}}

Give a concise answer (maximum of 100 words).
Rate the quality of the source from 1 to 10 in terms of how well it answeres the question and how current the information is.
"""
            
            logger.debug(f"find answer query:\n{query}")

            messages.append({"role": "user", "content": query})
        except Exception as e:
            logger.error(f"failed to build query {repr(e)}")            
        
        response_content = self.infrastructure.chat(
            messages=messages, 
            temperature=0.1, 
            seed=random.randint(0, 100000)
        )
        if not response_content:
            logger.error(f"failed query")
            return None
        
        reply = Utils.json_loads(response_content)
        if not reply:
            logger.error(f"failed to read answer from:\n{response_content}") 
            return None

        # making sure we can guarantee a certain json structure
        answer = {
            "answer": Utils.get_nested_value(reply, ["answer"], "no answer"),
            "quality": Utils.get_nested_value(reply, ["quality"], 0),
        }

        return answer

    