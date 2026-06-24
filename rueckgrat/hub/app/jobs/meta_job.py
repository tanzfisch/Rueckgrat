from .job_queue import Job
from .chat_job import ChatJob
from app.utils.message_queue import MessageQueue
from typing import Dict, Any

from app.common import get_logger, ChatRequest, Utils
logger = get_logger()

class MetaJob(Job):
    def __init__(self, user_id: int, request: ChatRequest, db, infrastructure, tool_registry):
        super().__init__()
        self.user_id = user_id
        self.request = request
        self.db = db
        self.infrastructure = infrastructure     
        self.tool_registry = tool_registry
            
    def execute(self) -> None:
        self.response = {}

        logger.debug("store incomming message")
        self.db.add_message(self.request.conversation_id, self.request.role, self.request.content, self.request.name)

        try:
            MessageQueue().send_status_message("thinking")
            contact = self.db.get_contact_by_id(self.request.contact_id)
            chat_job = ChatJob(self.request, self.db, self.infrastructure, self.tool_registry)
            self.add_sub_job(chat_job)
            self.wait_for([chat_job])
            chat_response = chat_job.result()
            logger.debug(f"chat response:\n{Utils.pretty_print(chat_response)}")
            
            tool_calls = chat_response["tool_calls"]

            for tool_call in tool_calls:                
                self.tool_registry.execute(
                    user_id=self.user_id,
                    contact_id=self.request.contact_id,
                    conversation_id=self.request.conversation_id,
                    response=self.response,
                    tool_call=tool_call
                )

            # handle tool outputs
            tool_response = ""

            if "websearch_results" in self.response:
                websearch_results = self.response["websearch_results"]
                self.response.pop("websearch_results")
                if len(websearch_results) > 0:
                    tool_response += f"\nWebsearch results in order of accuracy: "
                    for websearch_result in websearch_results:                        
                        tool_response += f"\n{websearch_result['title']} - {websearch_result['answer']} - source {websearch_result['source']}"
                else:
                    logger.error("empty tool response from websearch")

            if tool_response != "":
                tool_response = f"{chat_response['content']}\n\nWEBSEARCH_RESULT{tool_response}\n"

                logger.debug(f"tool response:\n{tool_response}")

                MessageQueue().send_status_message("finalize answer ...")
                chat_job = ChatJob(self.request, self.db, self.infrastructure, self.tool_registry, tool_response)
                self.add_sub_job(chat_job)
                self.wait_for([chat_job])
                chat_response = chat_job.result()                
                logger.debug(f"tool based chat response:\n{Utils.pretty_print(chat_response)}")

            self.response["chat"] = chat_response
            contact_name = Utils.get_nested_value(contact, ["identity", "name"])            
            message_id = self.db.add_message(self.request.conversation_id, "assistant", self.response["chat"]["content"], contact_name)

            if message_id:
                if "take_photo" in self.response:
                    image_filename = self.response["take_photo"]["filename"]
                    image_url = self.response["take_photo"]["image_path"]
                    self.db.add_attachment(message_id, image_filename, image_url, "image/png", 0)        

                if "generate_image" in self.response:
                    image_filename = self.response["generate_image"]["filename"]
                    image_url = self.response["generate_image"]["image_path"]
                    self.db.add_attachment(message_id, image_filename, image_url, "image/png", 0)
            
            logger.debug("assistant response generated")

            logger.debug("... done")
            MessageQueue().set_status("done")

        except Exception as e:
            logger.error(f"failed to execute MetaJob {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True