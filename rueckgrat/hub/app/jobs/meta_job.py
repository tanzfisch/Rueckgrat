import json
import time
from .job_queue import Job
from .chat_job import ChatJob
from .thinking_job import ThinkingJob
from .update_context_job import UpdateContextJob
from typing import Dict, Any, List, Optional

from app.common import get_logger, ChatRequest, Utils, MessageQueue
logger = get_logger()

class MetaJob(Job):
    def __init__(self, user_id: int, request: ChatRequest, db, infrastructure, tool_registry):
        super().__init__()
        self.user_id = user_id
        self.request = request
        self.db = db
        self.infrastructure = infrastructure     
        self.tool_registry = tool_registry
        self.message_id = -1
        self.done = False

    def _update_conversation_context(self):
        udate_context_job = UpdateContextJob(self.request, self.db, self.infrastructure)
        self.add_sub_job(udate_context_job)
        self.wait_for([udate_context_job])
        new_context = udate_context_job.result()
    
        conversation = self.db.get_conversation(self.request.conversation_id)
        conversation["title"] = new_context["topic"]
        self.db.update_conversation(self.request.conversation_id, conversation["title"], json.dumps(new_context))        

    def _on_incomming_message(self, message: str):
        data = json.loads(message)

        if "delta" in data:
            delta = data["delta"]
            self.db.append_to_message(self.message_id, delta)

            MessageQueue().send_data({
                "delta": delta,
                "conversation_id": self.request.conversation_id,
                "message_id": self.message_id
            })

        if data.get("error"):
            logger.error(f"chat stream failed: {data['error']}")

        if "response" in data:
            self.response["chat"] = {
                "conversation_id": self.request.conversation_id,
                "role": "assistant",
                "content": data["response"],
                "tool_calls": []
            }
            self.done = True
            
    def _format_websearch_results(self) -> Optional[str]:
        """removes the websearch tool result from self.response, returns the WEBSEARCH_RESULT block or None"""
        if not "websearch_results" in self.response:
            return None

        websearch_response = ""
        websearch_results = self.response.pop("websearch_results")
        if len(websearch_results) > 0:
            websearch_response += f"\nWebsearch results in order of accuracy: "
            for websearch_result in websearch_results:
                websearch_response += f"\n{websearch_result['title']} - {websearch_result['answer']} - source {websearch_result['source']}"
        else:
            logger.error("empty tool response from websearch")

        if websearch_response == "":
            return None
        return f"\n\nWEBSEARCH_RESULT{websearch_response}\n"

    def _format_conversion_results(self) -> Optional[str]:
        """removes the convert tool results from self.response, returns the CONVERSION_RESULT block or None"""
        if not "conversion_results" in self.response:
            return None

        conversion_response = ""
        for conversion in self.response.pop("conversion_results"):
            if "error" in conversion:
                conversion_response += f"\n{conversion['amount']} {conversion['from']} -> {conversion['to']}: failed - {conversion['error']}"
            else:
                date = f", rate date {conversion['date']}" if "date" in conversion else ""
                conversion_response += f"\n{conversion['text']} - source {conversion['source']}{date}"

        if conversion_response == "":
            return None
        return f"\n\nCONVERSION_RESULT{conversion_response}\n"

    def _format_tool_results(self) -> Optional[str]:
        """removes the results of the simple tools (calculate, current_time, date_calc, wikipedia, weather) from self.response, returns the TOOL_RESULT block or None"""
        if not "tool_results" in self.response:
            return None

        tool_response = ""
        for tool_result in self.response.pop("tool_results"):
            if "error" in tool_result:
                tool_response += f"\n{tool_result['tool']}: failed - {tool_result['error']}"
            else:
                tool_response += f"\n{tool_result['tool']}: {tool_result['text']}"

        if tool_response == "":
            return None
        return f"\n\nTOOL_RESULT{tool_response}\n"

    def _run_thinking(self, tool_names: Optional[List[str]] = None) -> Dict[str, Any]:
        """one thinking call as a sub job. tool_names None: with the tool index. a list: with the full prompts
        of these tools, the same path no matter who selected them (request_tools today, other selectors later)"""
        thinking_job = ThinkingJob(
            request=self.request,
            db=self.db,
            infrastructure=self.infrastructure,
            tool_registry=self.tool_registry,
            tool_names=tool_names
        )
        self.add_sub_job(thinking_job)
        self.wait_for([thinking_job])
        return thinking_job.result()

    def execute(self) -> None:
        self.response = {}

        if self.db.get_message_count_by_conversation(self.request.conversation_id) == 0:
            MessageQueue().send_status_message("creating scenario")
        else:
            MessageQueue().send_status_message("update context")

        self._update_conversation_context()

        logger.debug("store incomming message")
        self.db.add_message(self.request.conversation_id, self.request.role, self.request.content, self.request.name)

        try:
            MessageQueue().send_status_message("thinking")
            contact = self.db.get_contact_by_id(self.request.contact_id)

            thinking_response = self._run_thinking()
            logger.debug(f"thinking response (1):\n{Utils.pretty_print(thinking_response)}")

            tool_request = thinking_response.get("tool_request")
            if tool_request and tool_request["names"]:
                # the model asked for tools: second thinking call with their full prompts, its tool calls get executed
                logger.debug(f"tools requested: {tool_request['names']}")
                MessageQueue().send_status_message("thinking some more")
                thinking_response = self._run_thinking(tool_request["names"])
                logger.debug(f"thinking response (2):\n{Utils.pretty_print(thinking_response)}")
            tool_calls = thinking_response["tool_calls"]

            for tool_call in tool_calls:                
                self.tool_registry.execute(
                    user_id=self.user_id,
                    contact_id=self.request.contact_id,
                    conversation_id=self.request.conversation_id,
                    response=self.response,
                    tool_call=tool_call
                )

            MessageQueue().send_status_message("compile response")

            compiled_response = thinking_response['content']
            websearch_block = self._format_websearch_results()
            if websearch_block:
                compiled_response += websearch_block

            conversion_block = self._format_conversion_results()
            if conversion_block:
                compiled_response += conversion_block

            tool_block = self._format_tool_results()
            if tool_block:
                compiled_response += tool_block
            
            logger.debug(f"compiled response:\n{compiled_response}")

            contact_name = Utils.get_nested_value(contact, ["identity", "name"])
            self.message_id = self.db.add_message(self.request.conversation_id, "assistant", "", contact_name)

            MessageQueue().send_status_message("finalize answer")

            chat_job = ChatJob(
                request=self.request,
                db=self.db,
                infrastructure=self.infrastructure, 
                callback=self._on_incomming_message,
                thinking_response=compiled_response
            )

            self.add_sub_job(chat_job)
            self.wait_for([chat_job])

            if self.message_id:
                if "take_photo" in self.response:
                    image_filename = self.response["take_photo"]["filename"]
                    image_url = self.response["take_photo"]["image_path"]
                    self.db.add_attachment(self.message_id, image_filename, image_url, "image/png", 0)        

                if "generate_image" in self.response:
                    image_filename = self.response["generate_image"]["filename"]
                    image_url = self.response["generate_image"]["image_path"]
                    self.db.add_attachment(self.message_id, image_filename, image_url, "image/png", 0)
            
            logger.debug("assistant response generated")

            start = time.time()
            while not self.done:
                if time.time() - start > 300:
                    raise TimeoutError("5 min timeout")
                time.sleep(0.01)

            MessageQueue().set_status("done")

        except Exception as e:
            logger.error(f"failed to execute MetaJob {repr(e)}")

    def result(self) -> Dict[str, Any]:
        return self.response
    
    def has_response(self) -> bool:
        return True