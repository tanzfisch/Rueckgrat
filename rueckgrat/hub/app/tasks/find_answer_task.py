from .task_queue import Task
from . import prompts
from typing import Dict, Any
import random
import datetime

from app.common import get_logger, Utils
logger = get_logger()

# the prompt must fit one llama slot: LLAMA_SERVER_MAX_CONTEXT 8192 / LLAMA_SERVER_N_PARALLEL 2 (compose.yml, the node's .env,
# the hub can't read it). a longer prompt is refused with 400 "exceeds the available context size"
CONTEXT_TOKENS = 4096
REPLY_TOKENS = 300      # the json answer, at most 100 words
PROMPT_TOKENS = 250     # the instructions around the text
LETTERS_PER_TOKEN = 3.5     # the tokenizer splits digits, punctuation and non-ascii characters into a token each


def estimate_tokens(text: str) -> float:
    """on the safe side: checked against the node's tokenizer from 1.0x (numbers, tables) to 2x (english prose)"""
    letters = sum(c.isascii() and c.isalpha() for c in text)
    return len(text) - letters + letters / LETTERS_PER_TOKEN


def fit_tokens(text: str, max_tokens: float) -> str:
    """the start of text that fits max_tokens by estimate_tokens"""
    text = text[:int(max_tokens * LETTERS_PER_TOKEN)]
    used = 0.0
    for i, c in enumerate(text):
        used += 1 / LETTERS_PER_TOKEN if c.isascii() and c.isalpha() else 1
        if used > max_tokens:
            return text[:i]
    return text

class FindAnswerTask(Task):
    PROMPT = prompts.FIND_ANSWER_PROMPT     # information, question, today

    def __init__(self, question: str, information: str, infrastructure):
        super().__init__()
        self.question = question
        self.information = information
        self.infrastructure = infrastructure
        self.answer = None

    def execute(self) -> None:
        try:
            self.answer = self._find_answer()
        except Exception as e:
            logger.error(f"failed to update context {repr(e)}")

    def get_result(self) -> Dict[str, Any]:
        return self.answer
       
    def _find_answer(self):
        try:
            messages = []
            information = fit_tokens(self.information, CONTEXT_TOKENS - REPLY_TOKENS - PROMPT_TOKENS - estimate_tokens(self.question))
            query = self.PROMPT.format(information=information, question=self.question,
                                       today=datetime.date.today().strftime("%A, %d %B %Y"))
            
            #logger.debug(f"find answer query:\n{query}")

            messages.append({"role": "user", "content": query})
        except Exception as e:
            logger.error(f"failed to build query {repr(e)}")            
        
        response_content = self.infrastructure.chat(
            messages=messages, 
            temperature=0.1, 
            seed=random.randint(0, 100000),
            max_new_tokens=REPLY_TOKENS
        )
        if not response_content:
            logger.error(f"failed query")
            return None
        
        reply = Utils.json_loads(response_content)
        if not reply:
            logger.error(f"failed to read answer from:\n{response_content}") 
            return None

        return self._answer(reply)

    def _answer(self, reply) -> Dict[str, Any]:
        """the reply's json in a certain structure"""
        return {
            "answer": Utils.get_nested_value(reply, ["answer"], "no answer"),
            "quality": Utils.get_nested_value(reply, ["quality"], 0),
        }

    