"""
the tools' texts for the llm: every prompt of a tool (its instructions with parameters and examples), its one line for the
tool index (*_DESCRIPTION), the notes its results and planned results give the reply, the texts of its own llm calls, and
the sections ToolRegistry wraps around the tools' instructions. each Tool class picks its own constants from here.
the laya decision questions (Tool.question) stay with their tools, they are tuned with their scores.

plain constants are used as they are: the tool prompts hold literal json examples with single braces, never call .format on them.
templates, filled with str.format (literal braces doubled):
  TOOL_PLANNED_PART                           name: the tool's name
  TOOLS_RECOMMENDED_PART, TOOLS_REPLY_PART,
  TOOLS_OPTIONAL_PART, TOOLS_MANDATORY_PART   tools: the instructions of the offered tools (ToolRegistry.get_tools_prompt)
  RUN_CODE_WRITER_PROMPT                      run_timeout: seconds the program may run
  MAP_LOOKING_UP_PART                         query: the address of the call
  MAP_SHOWN_PART                              name: the found place's display name
  POLL_SHOWN_PART                             question, options (joined by " | "), choices: POLL_ONE_CHOICE_PART or POLL_SEVERAL_CHOICES_PART
  WRITE_FILE_ATTACHED_PART                    file_names: the files, comma separated
  SEARCH_MEMORY_CONVERSATION_QUESTION_PART    summary: the start of an earlier conversation's summary
  SPAWN_JOB_REPORT_PROMPT                     prompt, summary, details, attachments: SPAWN_JOB_ATTACHMENTS_PART or ""
  SPAWN_JOB_ATTACHMENTS_PART                  names: one "- name" line per held file
  SPAWN_JOB_CANCELLED_PROMPT                  prompt, name: the job's name
  SPAWN_JOB_FAILED_PROMPT                     prompt, name, reason
"""

# ---------------------------------------------------------------- tool index, how the tools are offered (ToolRegistry, Tool)

TOOL_PLANNED_PART = "{name} runs in the background, its result is shown to the user under your answer when it is done"

TOOLS_RECOMMENDED_PART = """
These tools may be needed, the detection was not sure. YOU decide whether the user's latest message really asks for what a tool does.
Call one only when it clearly fits the message, not because it is offered. Their full instructions:
{tools}

HOW TO CALL:
Call a recommended tool only when the message needs it. If none of them fits, output nothing for them.
If you do call a tool, write ONE line of JSON per call, exactly in the format shown above, with the values for the query filled in.
Writing about a call does nothing, only a JSON line runs the tool. Do not describe the call in words, no headings like "TOOL CALL:", no analysis.
"""

TOOLS_REPLY_PART = """
TOOLS IN YOUR REPLY:
You can use these tools on your own in any reply, the user does not have to ask for them. Their full instructions:
{tools}

HOW TO CALL:
Write your reply to the user first. Only when a tool is useful, add ONE line of JSON per call at the very end of your reply, exactly in the format shown above.
The user does not see these lines. Never mention or describe a call in your reply, only a JSON line runs the tool. Most replies need no call.
"""

TOOLS_OPTIONAL_PART = """
These tools are optional: YOU decide on your own whether to use them. The user does not ask for them and does not have to mention them.
Judge from the conversation whether a tool helps you answer well, e.g. remembering something worth keeping or looking up an earlier memory. Their full instructions:
{tools}

HOW TO CALL:
Call an optional tool whenever you find it useful for this message, also when the user did not ask for it. If none of them is useful, output nothing for them.
If you do call a tool, write ONE line of JSON per call, exactly in the format shown above, with the values for the query filled in.
Writing about a call does nothing, only a JSON line runs the tool. Do not describe the call in words, no headings like "TOOL CALL:", no analysis.
"""

TOOLS_MANDATORY_PART = """
These tools must be called. Their full instructions:
{tools}

HOW TO CALL:
Your answer MUST be the tool calls, ONE line of JSON per call, exactly in the format shown above, with the values for the query filled in. Do not skip any of them.
Writing about a call does nothing, only a JSON line runs the tool. Do not describe the call in words, no headings like "TOOL CALL:", no analysis.
"""

# ---------------------------------------------------------------- notes shared by the image tools (generate_image, take_photo)

IMAGE_ATTACHED_NOTE_PART = "it is attached to your message"

# ---------------------------------------------------------------- calculator

CALCULATOR_DESCRIPTION = "exact arithmetic and math (sums, percentages, tips, powers, roots, trigonometry)"

CALCULATOR_PROMPT = """
CALCULATE:
Use for any arithmetic or math (sums, percentages, tips, powers, roots, trigonometry).
Operators: + - * / // % ** ( )
Functions: sqrt, abs, round, min, max, floor, ceil, exp, ln, log10, log2, sin, cos, tan (radians), factorial
Constants: pi, e

Parameters:
- expression (string, required): the math expression to evaluate

Example:
{"tool": "calculate", "expression": "0.15 * 84.50"}
"""

# ---------------------------------------------------------------- run_code

RUN_CODE_DESCRIPTION = "writes a small program and runs it in a sandbox container, returns its output"

RUN_CODE_WRITER_PROMPT = """You write one complete program for the task below. It runs once in a fresh sandbox, what it prints comes back to you.

Reply with ONLY the source code of the program as plain text: no JSON, no explanation, no markdown fences.

Rules:
- One single file. Print every result to stdout, the program gets no input.
- Python, unless the task or the user asks for another language: javascript, cpp, java or go.
- Header lines at the very top, only when needed, always with # (they are removed before the program runs):
# language: cpp
# requires: numpy, pandas
- "language" when it is not python. "requires" lists packages to install first: pip for python, npm for javascript, apt for cpp, go modules for go. java can't install packages, use only its standard library.
- When the user gave code to run, reply with that code unchanged (add header lines if it needs packages).
- It must finish within {run_timeout} seconds. Keep the output short."""

RUN_CODE_PROMPT = """
RUN_CODE:
Use when the user asks you to run or execute code, or to work something out with a program: exact results with big numbers, simulations, data processing, checking that code works. A separate step writes one program file for your task and runs it in a fresh sandbox, you get its output, errors and exit code back.
You may also use it on your own when an exact check is better than guessing:
- verify a calculation, a count or an idea (primes, digits, dates, regex matches)
- debug: reproduce an error in isolation to find its cause
- benchmark: compare snippets for speed or output
- explore an unfamiliar function or library by trying it
- validate math or logic before you rely on it in a longer plan
- prototype a small piece to see if an approach works before using it
Do not use it when the user only wants to see or discuss code, or for simple arithmetic (calculator).

Parameters:
- task (string, required): what the program must do and print, with all the values it needs. When the user gave code to run, write "run the code from the user's message", do not copy the code here.
- language (string, optional): "python" (default), "javascript", "cpp", "java" or "go"

Examples:
{"tool": "run_code", "task": "compute the 50th Fibonacci number and print it"}
{"tool": "run_code", "task": "run the code from the user's message", "language": "javascript"}
"""

# ---------------------------------------------------------------- conversion

CONVERSION_DESCRIPTION = "converts amounts between currencies, crypto and physical units, prices gold/silver/platinum in any currency"

CONVERSION_PROMPT = """
CONVERT:
Use for converting an amount between units: currencies and crypto (live rates), precious metals (gold, silver, platinum, palladium) in any currency, and physical units (length, mass, volume, area, temperature, speed, time, data, energy, power, pressure). Prefer this over websearch for exchange rates and metal prices. One call per conversion.

Parameters:
- amount (number, required): the value to convert
- from (string, required): source unit (e.g. "USD", "BTC", "oz gold", "km", "°C", "GB")
- to (string, required): target unit

Example:
{"tool": "convert", "amount": 100, "from": "USD", "to": "EUR"}
"""

# ---------------------------------------------------------------- current_time

CURRENT_TIME_DESCRIPTION = "current date, time and weekday in a city or time zone"

CURRENT_TIME_PROMPT = """
CURRENT TIME:
Use when you need the current date, time, or weekday in a location.

Parameters:
- timezone (string, required): IANA name ("Pacific/Auckland") or city ("Auckland", "Munich")

Example:
{"tool": "current_time", "timezone": "Pacific/Auckland"}
"""

# ---------------------------------------------------------------- date_calc

DATE_CALC_DESCRIPTION = "days between two dates, or a date plus/minus a number of days"

DATE_CALC_PROMPT = """
DATE CALCULATION:
Use for days between two dates or a date plus/minus a number of days. Dates are YYYY-MM-DD or "today".

Parameters:
- start (string, required): start date
- end (string, optional): end date (for difference)
- days (number, optional): number of days to add/subtract
- timezone (string, required): IANA name or city

Example (difference):
{"tool": "date_calc", "start": "today", "end": "2026-12-25", "timezone": "Pacific/Auckland"}

Example (offset):
{"tool": "date_calc", "start": "today", "days": 90, "timezone": "Pacific/Auckland"}
"""

# ---------------------------------------------------------------- fetch_url

FETCH_URL_DESCRIPTION = "reads a web page the user gives a link to and returns a condensed summary of it"

FETCH_URL_PROMPT = """
FETCH_URL:
Use when the user gives a URL and wants to know what is on the page.

Parameters:
- url (string, required): the full URL
- focus (string, optional): what to focus on (omit for general summary)

Example:
{"tool": "fetch_url", "url": "https://example.com/article", "focus": "release date"}
"""

# ---------------------------------------------------------------- image_gen

IMAGE_GEN_DESCRIPTION = "generates a picture from a description when the user asks for an image"

IMAGE_GEN_PLANNED_PART = "an image is being generated, it gets attached to your message"

IMAGE_GEN_PROMPT = """
IMAGE GENERATION:
Use when the user asks you to generate, create, or visualize a picture.

Parameters:
- positive_prompt (string, required): the image description

Example:
{"tool": "generate_image", "positive_prompt": "a red bicycle in a sunny park"}
"""

# ---------------------------------------------------------------- map

MAP_DESCRIPTION = "shows the user a map bubble of a place or an address, tapping it opens the maps app"

MAP_NO_ADDRESS_PART = "no address given, no map is shown"

MAP_LOOKING_UP_PART = ("a map of {query} is being looked up, it is shown under your answer once it is found. "
                  "Do not write coordinates or map links in your answer text and do not say the map is shown, "
                  "at most one short line that you are checking the map.")

MAP_SHOWN_PART = ("a map of {name} is shown to the user, tapping it opens their maps app. "
             "Do not write coordinates or map links in your answer text, at most one short line that points to the map.")

MAP_PROMPT = """
SHOW_MAP:
Use when the user asks where a place is, how to get there, or wants to see it on a map, or when you suggest going to or meeting at a specific place. The map is shown under your answer, tapping it opens the user's maps app.
Do not use it for places in stories, roleplay or memories, for an address the user only mentions in passing (their home, their office), or for questions about a place that don't need a map (weather, time, history, facts).

Parameters:
- address (string, required): the address or the place, as precise as you know it, with the city
- label (string, optional): a short name for the pin

One map per message. Do not write coordinates or map links in your answer text.

Example:
{"tool": "show_map", "address": "Sky Tower, Victoria Street West, Auckland", "label": "Sky Tower"}
"""

# ---------------------------------------------------------------- poll

POLL_DESCRIPTION = "shows the user a poll bubble with options to tap, one choice or several"

POLL_INVALID_PART = "the poll was invalid, no poll is shown"

POLL_SHOWN_PART = ("the poll is shown to the user: \"{question}\" "
              "({choices}: {options}). "
              "Do not write the question, the options or further questions in your answer text, they are only in the tool call. At most one short line that points to the poll.")

POLL_ONE_CHOICE_PART = "one choice"

POLL_SEVERAL_CHOICES_PART = "several choices"

POLL_PROMPT = """
POLL:
Use when the user asks for a poll, a vote, a quiz or options to choose from, or when a multiple choice question fits your answer better than an open question. The user picks from the options, the choice comes back as their next message.

Parameters:
- question (string, required): the question, short
- options (list of strings, required): 2 to 8 short options
- mode (string, optional): "single" (one choice, default) or "multi" (several choices)

Put the question and the options only in the tool call. Do not write them or a list of further questions in your answer text, at most one short line that points to the poll.
One poll per message: for a questionnaire or quiz, put the first question in the poll and ask the next one in a new poll after the user answered.

Example:
{"tool": "poll", "question": "Where should we go tonight?", "options": ["Cinema", "Restaurant", "Stay home"], "mode": "single"}
"""

# ---------------------------------------------------------------- remember

REMEMBER_DESCRIPTION = "save one short fact to remember in later conversations (about the user, their life, plans, preferences or your relationship)"

REMEMBER_PROMPT = """
REMEMBER:

Whenever the user tells you a durable fact about themselves that will still be true later (name, identity, relationships, long-term history, location, job, health and allergies, pets, hobbies, lasting preferences, plans with a date), store it. Skip temporary wants or comments about media/videos.

Write in third person. Max 200 characters. One fact only.

Parameters:
- text (string, required): the fact

Example:
{"tool": "remember", "text": "The user's sister is called Anna and lives in Hamburg"}
"""

# ---------------------------------------------------------------- search_memory

SEARCH_MEMORY_DESCRIPTION = ("what the user told you before (name, where they live, family, work, plans, preferences, etc) and what you talked about in earlier conversations. "
                             "Use for any personal question about the user, e.g. \"do you know where I was born?\", even without \"remember\"")

SEARCH_MEMORY_CONVERSATION_QUESTION_PART = "Is this earlier conversation about the user's question? Summary of the conversation: {summary}"

SEARCH_MEMORY_PROMPT = """
SEARCH MEMORY:

Call this tool whenever you need to recall a fact about the user or anything from past interactions with them (name, location, family, work, preferences, previous statements, etc.). Do not guess or invent details.

Parameters:
- query (string, required): what to look for (max 100 characters)

Example:
{"tool": "search_memory", "query": "where the user lives"}
"""

# ---------------------------------------------------------------- spawn_job

SPAWN_JOB_DESCRIPTION = "hands a task to a background job: long or multi-step work, research with its own analysis, watching something, or repeating on a schedule and reporting back later"

SPAWN_JOB_REPORT_PROMPT = """A background job you started for the user has finished.

JOB_PROMPT:
{prompt}

JOB_RESULT:
{summary}
{details}
{attachments}
Tell the user in one or two short sentences that the job is done and what it found. Reply with the message only.
"""

SPAWN_JOB_ATTACHMENTS_PART = """
ATTACHED (already with your message, files as download buttons, images shown):
{names}
Do NOT write their code or content into your message, only say what they are.
"""

SPAWN_JOB_CANCELLED_PROMPT = """The user cancelled a background job you started for them, it was stopped before it finished.

JOB_PROMPT:
{prompt}

Tell the user in one or two short sentences that the job "{name}" is stopped, and react to the cancel as it fits the conversation. Reply with the message only.
"""

SPAWN_JOB_FAILED_PROMPT = """A background job you started for the user has failed, it stopped before it was finished.

JOB_PROMPT:
{prompt}

WHY IT FAILED:
{reason}

Tell the user in one or two short sentences that the job "{name}" failed and why, in plain words. Reply with the message only.
"""

# the reply that starts a job only says so: the job does the work, its report comes as a new message later
SPAWN_JOB_HANDED_OFF_PART = ("Do NOT do the task yourself in this reply: no code, no file contents, no research, no results, no lists, "
                        "no drafts and no plan. Only tell the user in one or two short sentences that you are on it and report back when it is done.")

SPAWN_JOB_RUNNING_PART = "a background job is running in this conversation already, it got the user's message and adjusts its plan after its current step. " + SPAWN_JOB_HANDED_OFF_PART

SPAWN_JOB_STARTED_PART = "a background job was started and is doing the task now. " + SPAWN_JOB_HANDED_OFF_PART

SPAWN_JOB_PROMPT = """
SPAWN_JOB:
Use to hand a task to a background job, so the conversation can go on meanwhile.
Use it for tasks that take long, have several steps, keep watching something, or repeat on a schedule and report back later.
A conversation has one job at a time: while it runs, the user's messages go to it and it adjusts its plan.

Parameters:
- prompt (string, required): the full instructions for the job, in the user's own words. Keep every detail the user gave: what to do, when or how often, and when to report back. Never add names, numbers, tickers or places the user did not say. If the user says "these" or "my" without naming them, keep it like that and add: ask the user which ones.

Examples:
{"tool": "spawn_job", "prompt": "find three reviews of the new Pixel phone and summarize them"}
{"tool": "spawn_job", "prompt": "every Friday check the prices of my two favourite games and message me if one is on sale (ask the user which games)"}
"""

# ---------------------------------------------------------------- take_photo

TAKE_PHOTO_DESCRIPTION = "takes a photo of yourself, the user or both in the current situation"

TAKE_PHOTO_PLANNED_PART = "you are taking a picture, it gets attached to your message"

TAKE_PHOTO_PROMPT = """
TAKE PHOTO:
Use sparingly, only when you genuinely want to take a photo of yourself, the user, or both in the current situation. Do not use for every request. Also use when the user explicitly asks for one or if you want to demonstrate something to the user.

Parameters:
- subject (string, required): "self", "user", or "both"

Example:
{"tool": "take_photo", "subject": "both"}
"""

# ---------------------------------------------------------------- weather

WEATHER_DESCRIPTION = "current weather and 3 day forecast for a place"

WEATHER_PROMPT = """
WEATHER:
Use for current weather and 3-day forecast. Prefer this over websearch for weather.

Parameters:
- location (string, required): city or place name

Example:
{"tool": "weather", "location": "Auckland"}
"""

# ---------------------------------------------------------------- websearch

WEBSEARCH_DESCRIPTION = "searches the web for current, factual or local information (news, events, prices, stocks, opening hours)"

WEBSEARCH_PROMPT = """
WEBSEARCH:
Use for current, factual, real-time, or location-specific information, or when you need fresh ideas.

Parameters:
- query (string, required): the search query

Example:
{"tool": "websearch", "query": "current NZD to USD exchange rate"}
"""

# ---------------------------------------------------------------- wikipedia

WIKIPEDIA_DESCRIPTION = "encyclopedic summary of a well known person, place, thing, concept or historic event"

WIKIPEDIA_PROMPT = """
WIKIPEDIA:
Use for a quick encyclopedic summary of a well-known person, place, thing, or event. Not for news or current values.

Parameters:
- query (string, required): the topic
- lang (string, optional): Wikipedia language code, default "en"

Example:
{"tool": "wikipedia", "query": "Eiffel Tower", "lang": "en"}
"""

# ---------------------------------------------------------------- write_file

WRITE_FILE_DESCRIPTION = "writes a text file the user can keep, such as a page of a website or a source file or document"

WRITE_FILE_ATTACHED_PART = ("{file_names} are already attached to your answer as download buttons, the user saves them from there. "
                       "Do NOT write their code or content into your answer, no code blocks and no copy and paste instructions. "
                       "Only say in one or two sentences what each file is for and that it can be downloaded below.")

WRITE_FILE_PROMPT = """
WRITE_FILE:
Use when the user wants a file they can keep: a page, a stylesheet, a script, or several of those.
One JSON line per file. A website is several lines, one path each. Put the file text in content.
Paths are relative (index.html, css/style.css). No .. and no absolute path.
Escape quotes and newlines inside content so the line stays valid JSON.

Parameters:
- path (string, required): relative file name
- content (string, required): the whole file

Example:
{"tool": "write_file", "path": "index.html", "content": "<!DOCTYPE html><html><head><link rel=\\"stylesheet\\" href=\\"css/style.css\\"></head><body><h1>Hello</h1></body></html>"}
{"tool": "write_file", "path": "css/style.css", "content": "body { color: #222; }"}
"""
