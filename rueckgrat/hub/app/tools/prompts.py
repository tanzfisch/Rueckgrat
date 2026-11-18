"""
the tools' texts for the llm: every prompt of a tool (its instructions with parameters and examples), its one line for the
tool index (*_DESCRIPTION), the notes its results and planned results give the reply, the texts of its own llm calls, and
the sections ToolRegistry wraps around the tools' instructions. each Tool class picks its own constants from here.
the laya decision questions (Tool.question) stay with their tools, they are tuned with their scores.

plain constants are used as they are: the tool prompts hold literal json examples with single braces, never call .format on them.
templates, filled with str.format (literal braces doubled):
  TOOL_PLANNED_PART                           name: the tool's name
  TOOL_CUT_OFF_PART                           name: the tool whose last call was cut off
  TOOL_LENGTH_PART                            name: the tool of the last call of a setup reply that hit its token limit
  FIX_ROUND_PART                              fix, total: the fix round and how many there are, problems: "- " lines
  TOOL_NOT_CALLED_PART                        name: a mandatory tool of a worker that got no call
  CHECKS_FIXED_PART, CHECKS_FAILED_PART       rounds: fix rounds run, problems (failed only): "; " separated
  TOOLS_RECOMMENDED_PART, TOOLS_REPLY_PART,
  TOOLS_OPTIONAL_PART, TOOLS_MANDATORY_PART   tools: the instructions of the offered tools (ToolRegistry.get_tools_prompt)
  RUN_CODE_WRITER_PROMPT                      run_timeout: seconds the program may run, files: the sandbox files folder,
                                              projects: its projects folder, workdir: the conversation's own folder
  MAP_LOOKING_UP_PART                         query: the address of the call
  MAP_SHOWN_PART                              name: the found place's display name
  POLL_SHOWN_PART                             question, options (joined by " | "), choices: POLL_ONE_CHOICE_PART or POLL_SEVERAL_CHOICES_PART
  PRICE_FOUND_PART                            query, findings: one PRICE_FINDING_LINE per find, best first
  PRICE_FINDING_LINE                          place, title, price, currency, shop, note: " (the note)" or ""
  PRICE_NONE_PART                             query: the product searched for
  WEBSEARCH_FOUND_PART                        query: the search, answers: one WEBSEARCH_ANSWER_LINE per answer, most accurate first
  WEBSEARCH_ANSWER_LINE                       source: the site's name, answer: what the page says, url: the page
  WRITE_FILE_ATTACHED_PART                    file_names: the files, comma separated
  WRITE_FILE_NOT_ATTACHED_PART                problems: what could not be attached, "; " separated
  WRITE_FILE_SAVED_PART                       paths: where write_file kept its files, comma separated
  WRITE_FILE_PROMPT                           documents: the folder write_file keeps a plain name in, files: the sandbox files folder
  WRITE_FILE_REFUSED_PART                     name: the file write_file does not write (audio, image, archive)
  FILE_EXISTS_PART                            path: the full path that is taken
  FILE_TOO_LARGE_PART                         path: where it is kept, size, limit: MB
  SHARE_FILE_PROMPT                           files: the sandbox files folder
  TEXT_TO_SPEECH_PROMPT                       files: the sandbox files folder, tts: the folder the audio files are kept in
  TEXT_TO_SPEECH_MADE_PART                    name: the audio file, minutes: its length
  TEXT_TO_SPEECH_NOT_TEXT_PART                name: the file that is not text
  TEXT_TO_SPEECH_FAILED_PART                  name: the call's name, reason: what went wrong
  TEXT_TO_SPEECH_PLANNED_PART                 name: the call's name
  JOIN_FILES_PROMPT                           files: the sandbox files folder, tts: the folder audio is kept in,
                                              documents: the folder text is kept in
  JOIN_FILES_MADE_PART                        name: the joined file, count: how many files, length: JOIN_FILES_AUDIO_PART or ""
  JOIN_FILES_AUDIO_PART                       minutes: the audio's length
  JOIN_FILES_FAILED_PART                      name: the call's name, reason: what went wrong
  BASH_PROMPT                                 files: the sandbox files folder, timeout: seconds per command, workdir: the
                                              conversation's own folder, project_dir, documents, images: the folders of
                                              the layout, projects: BASH_PROJECT_LINE lines, BASH_NO_PROJECTS_PART or
                                              BASH_PROJECTS_UNKNOWN_PART
  BASH_PROJECT_LINE                           name: a project's folder, summary: the first line of its PROJECT.md
  SEARCH_MEMORY_CONVERSATION_QUESTION_PART    summary: the start of an earlier conversation's summary
  SPAWN_JOB_REPORT_PROMPT                     prompt, summary, details, attachments: SPAWN_JOB_ATTACHMENTS_PART or ""
  SPAWN_JOB_ATTACHMENTS_PART                  names: one "- name" line per held file
  SPAWN_JOB_CANCELLED_PROMPT                  prompt, name: the job's name
  SPAWN_JOB_FAILED_PROMPT                     prompt, name, reason
  FIND_TOOLS_PART                             task: what the find_tools call asked a tool for
  FIND_TOOLS_FOUND_PART, FIND_TOOLS_NONE_PART,
  FIND_TOOLS_OFFERED_PART                     task, tools (not for none): the tools found, comma separated
  FIND_TOOLS_ROUND_PART                       task: added to the original prompt of the rounds of the found tools
  TOOL_NOTES_PART                             notes: the TOOL_NOTE_* lines of the offered tools, one "- " line each
A tool's own texts never name another tool: how tools are used together is in the TOOL_NOTE_* texts (ToolRegistry.TOOL_NOTES).
"""

# ---------------------------------------------------------------- tool index, how the tools are offered (ToolRegistry, Tool)

# how tools are used together, the tools themselves know nothing of each other. ToolRegistry.TOOL_NOTES: a note goes into a
# tool setup when one of its tools is offered there and all of them can be used in it
TOOL_NOTES_PART = """
HOW THE TOOLS WORK TOGETHER
{notes}
"""
TOOL_NOTE_RUN_CODE_BASH = "run_code runs one program once. To create a project or files to keep, use bash: it works in the same files."
TOOL_NOTE_RUN_CODE_CALCULATE = "Simple arithmetic goes to calculate, not to run_code."
TOOL_NOTE_BASH_WRITE_FILE = ("A software project or several files at once are made with bash in your sandbox files, not with write_file: "
                             "write_file writes one text file.")
TOOL_NOTE_BASH_SHARE_FILE = ("The user does not see the files bash makes: give them files or a project folder with share_file afterwards. "
                             "share_file calls in the same answer as the bash calls that make the files run after them.")
TOOL_NOTE_RUN_CODE_SHARE_FILE = "The user does not see the files run_code makes in your files: give them with share_file afterwards."
TOOL_NOTE_CONVERT_WEBSEARCH = "Prefer convert over websearch for exchange rates and metal prices."
TOOL_NOTE_WEATHER_WEBSEARCH = "Prefer weather over websearch for the weather."
TOOL_NOTE_SPAWN_JOB_TASK = ("spawn_job is for work now, not for anything at a later time or repeating (reminders, alarms, every day, "
                            "every hour, watching a price): that is task.")
TOOL_NOTE_WRITE_FILE_TEXT_TO_SPEECH = ("write_file writes text only, never audio. An audio file comes from text_to_speech: write a "
                                       "long text into files first, then text_to_speech speaks the files.")
TOOL_NOTE_TEXT_TO_SPEECH_JOIN_FILES = ("Audio made of several parts (chapters, episodes, scenes) is one text_to_speech call over all its "
                                       "text files in order, or one text_to_speech call per part followed by join_files, which joins the "
                                       "audio files in order.")

TOOL_PLANNED_PART = "{name} runs in the background, its result is shown to the user under your answer when it is done"

TOOL_CUT_OFF_PART = ("the last {name} call was cut off, the tool setup got too long, it did NOT run. "
                     "Its work is missing: tell the user which part is not done")
TOOL_LENGTH_PART = ("the tool setup hit its length limit after the last {name} call: the calls it did not write are missing, "
                    "tell the user which part is not done")

# a worker's fix rounds (ToolExecutionTask): appended to its task when bash, run_code, share_file or write_file calls did not work
FIX_ROUND_PART = """

FIX ROUND {fix} OF {total}: these calls of the earlier rounds did not work:
{problems}
The earlier results show what happened (the commands, exit codes and errors). Fix only what failed, in order: repair the
code or write the missing files, then run the failed command again (e.g. the build or the test), so its result shows
whether it works now. Do not redo what already worked. Attach a file again only when it is new or changed. A file of
this task that is there already (made by an earlier call) is replaced with "overwrite": true."""
TOOL_NOT_CALLED_PART = ("{name}: the task needs it, but it was not called. Call it now for what the task asks "
                        "(build, install, run, test), all calls at once")
CHECKS_FIXED_PART = "the calls that did not work were fixed in {rounds} fix round(s), the last calls all worked."
CHECKS_FAILED_PART = ("still not working after {rounds} fix round(s): {problems}. Tell the user what does not work, "
                      "do not claim it works.")

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
- It must finish within {run_timeout} seconds. Keep the output short.
- The folder {files} holds the user's files, they stay between runs: the projects in {projects}/<project-name>/, this conversation's own folder {workdir}, the files written for the user in {files}/data/documents/. Read and write there when the task is about these files. Files to keep go into the project's own folder, scratch files into {workdir}.
- A task about a project: the program first changes into the project's folder {projects}/<project-name> (python: os.chdir to it and sys.path.insert(0, it)), then imports or runs the project's code from there, so its own imports and relative paths work."""

RUN_CODE_NO_CODE_PART = ("the task was to run the code from the user's message, but the conversation has no code. Nothing ran. "
                         "Describe what the program must do instead.")

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
Do not use it when the user only wants to see or discuss code, or for simple arithmetic.
It runs one program once, the files it writes in your files stay.

Parameters:
- task (string, required): what the program must do and print, with all the values it needs. Only when the user's message has code to run, write "run the code from the user's message", do not copy the code here.
- language (string, optional): "python" (default), "javascript", "cpp", "java" or "go"

Examples:
{"tool": "run_code", "task": "compute the 50th Fibonacci number and print it"}
{"tool": "run_code", "task": "run the code from the user's message", "language": "javascript"}
"""

# ---------------------------------------------------------------- bash

BASH_DESCRIPTION = ("runs a bash command in your own persistent sandbox files, shared by all your conversations with the user (git, python, curl, network): "
                    "where you create and work on projects and files")

BASH_PROMPT = """
BASH:
Use to work with your files, shared by all your conversations with the user: create, read, edit, list, move and delete files and folders, run command line tools and scripts, clone and work on git repositories, download files. Each call runs one bash command (pipes, &&, heredocs are fine) in a Linux container as a normal user (no sudo, no apt-get), with network.
- $HOME is {files}, the files in it are kept (for a week after the last message to you). Like an open terminal, the next call of this conversation goes on in the folder its last one ended in, with its exported variables and an activated venv. A new conversation starts in {workdir}. Running processes do not carry over.
- The folders, each for one purpose:
  - {project_dir}/<project-name>/: one folder per project (short, lowercase, e.g. fractal_explorer), all its files and subfolders inside. Each has a PROJECT.md: its first line says in one sentence what the project is, then its status and how to run it. Write it when you create the project, update it when the project changes.
  - {workdir}: this conversation's own folder: scratch work, quick scripts and downloads that belong to no project.
  - {documents}/: the files written for the user, each in its own folder (<hash>/<name>). Read or copy them, do not change them.
  - {images}/: generated images.
- The projects so far (folder: first line of its PROJECT.md):
{projects}
- Available: bash, coreutils, git, python3 with pip and venv, curl, wget, unzip. git commit works, an author is set. There is no display: GUI programs run without a window.
- Python packages go in a venv in the project folder: python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
- The command must finish within {timeout} seconds. A program that keeps running (a game, a GUI, a server) runs with a time limit: timeout 10 python3 main.py, exit code 124 then means it ran 10 seconds without crashing. Keep the output short: use head, tail, grep or wc instead of printing big files whole.
- {files} is your own filesystem: create every project and its files here. Nothing loose at the top of {files}.
- Continue earlier work: an existing project is changed in its folder (cd into it first), not started again.
- You write all calls of this step at once and get no second turn: write every command the task needs now, in order, nothing left for later. They run one after another, a later call sees what an earlier one made.
- To create or change a project: one call per file with its whole content in a heredoc (mkdir -p in the first call). Every file the task asks for gets its call.
- The user does not see these files.

Parameters:
- command (string, required): the bash command, newlines written as \\n

Examples:
{{"tool": "bash", "command": "ls -la"}}
{{"tool": "bash", "command": "git clone --depth 1 https://github.com/psf/requests.git && ls requests"}}
{{"tool": "bash", "command": "mkdir -p shopping_list && printf 'milk\\neggs\\n' > shopping_list/items.txt && cat shopping_list/items.txt"}}
{{"tool": "bash", "command": "mkdir -p ~/projects/fractal_explorer && cd ~/projects/fractal_explorer && printf '%s\\n' 'Fractal explorer: a Mandelbrot viewer in python.' '' 'Status: started.' 'Run: python3 main.py' > PROJECT.md"}}
{{"tool": "bash", "command": "cat > ~/projects/fractal_explorer/main.py << 'EOF'\\nprint('hello')\\nEOF"}}
"""

BASH_PROJECT_LINE = "  - {name}: {summary}"
BASH_NO_PROJECTS_PART = "  none yet"
BASH_PROJECTS_UNKNOWN_PART = "  (not listed here, ls ~/projects shows them)"

# ---------------------------------------------------------------- conversion

CONVERSION_DESCRIPTION = "converts amounts between currencies, crypto and physical units, prices gold/silver/platinum in any currency"

CONVERSION_PROMPT = """
CONVERT:
Use for converting an amount between units: currencies and crypto (live rates), precious metals (gold, silver, platinum, palladium) in any currency, and physical units (length, mass, volume, area, temperature, speed, time, data, energy, power, pressure). One call per conversion.

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
Use when you need the current date, time, or weekday, the user's own or in a location.

Parameters:
- timezone (string, optional): IANA name ("America/New_York") or city ("Tokyo", "Munich") of the place asked about.
  Leave it out for the user's own time, never put a person's name in it.

Example (the user's own time):
{"tool": "current_time"}

Example (a place):
{"tool": "current_time", "timezone": "Tokyo"}
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
- timezone (string, optional): IANA name or city whose "today" counts. Leave it out for the user's own today.

Example (difference):
{"tool": "date_calc", "start": "today", "end": "2026-12-25"}

Example (offset):
{"tool": "date_calc", "start": "today", "days": 90}
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
Not for feedback on a program, an app or a game (an axis is flipped, a color is wrong in it): that is a fix of the program, not a picture.

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
Use when the user asks for a poll, a vote, a quiz, a questionnaire, a survey, questions in several rounds or options to choose from, or when a multiple choice question fits your answer better than an open question. The user picks from the options, the choice comes back as their next message.

Parameters:
- question (string, required): the question, short
- options (list of strings, required): 2 to 8 short options
- mode (string, optional): "single" (one choice, default) or "multi" (several choices)

Put the question and the options only in the tool call. Do not write them or a list of further questions in your answer text, at most one short line that points to the poll.
One poll per message: for a questionnaire or quiz, put the first question in the poll and ask the next one in a new poll after the user answered.

Example:
{"tool": "poll", "question": "Where should we go tonight?", "options": ["Cinema", "Restaurant", "Stay home"], "mode": "single"}
"""

# ---------------------------------------------------------------- price_finder

PRICE_FINDER_DESCRIPTION = ("searches shops on the web for a product, ranks the best prices or the best matches and shows "
                            "the top three on a podium with links to buy")

PRICE_FOUND_PART = ("a price ranking for {query} is shown to the user under your answer: the best three on a podium, more finds in "
                    "a list under it, each with a link to its shop. The finds, best first:\n{findings}\n"
                    "Name the winner with its price and shop in one or two sentences, a runner-up when it helps. Do not write "
                    "links or the whole list, the user sees them. The prices are from the shops' pages now, they can change.")

PRICE_FINDING_LINE = "{place}. {title}: {price} {currency} at {shop}{note}"

PRICE_NONE_PART = ("no shop page with a price for {query} was found. Tell the user you could not find prices for it right now, "
                   "suggest a more precise product name. Do not make up prices, shops or links.")

PRICE_FINDER_PROMPT = """
PRICE_FINDER:
Use when the user wants to buy something: the best price or the cheapest shop for a product, what a product costs now, or a product with the features they name (e.g. a lawn mower with a 21 inch cut and a petrol engine). It searches the shops on the web, reads their pages and shows the best three finds on a podium under your answer, more finds in a list, each with a link to its shop.
Do not use it for stocks, crypto or exchange rates, for things the user already has, or for services like flights or hotels.

Parameters:
- query (string, required): the product with the details that matter (brand, model, size, features), and the user's country when you know it
- rank (string, optional): "price" (default) puts the cheapest offers for a named product first, "match" the products that fit the named features best

One price_finder call per message. Do not write prices, shops or links in your answer that are not in its result.

Examples:
{"tool": "price_finder", "query": "Sony WH-1000XM5 headphones NZ", "rank": "price"}
{"tool": "price_finder", "query": "petrol lawn mower 21 inch cutting width", "rank": "match"}
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

# ---------------------------------------------------------------- find_tools

FIND_TOOLS_DESCRIPTION = "asks for the tools of a task that the offered tools can not do, they are offered in an extra round"

FIND_TOOLS_PROMPT = """
FIND TOOLS:
Rarely needed: most answers need no tool at all. Do not call it unless one of these is true:
- something that runs with a tool goes on in this answer, as the conversation before shows: e.g. a quiz asked as polls
  continues with its next poll, or a game that shows maps shows the next one
- the user clearly asks for something that needs a tool, and no offered tool can do it
Never call it to chat, to answer from what you know, to tell a story, to give an opinion, or because a tool might help.
Never call it for what an offered tool can do. When in doubt, do not call it.
The tools that fit the task are offered to you in an extra round.

Parameters:
- task (string, required): one short sentence, written as the user would ask for it: what has to happen now, without
  the content details (no questions, answers or lists of values)

Examples:
{"tool": "find_tools", "task": "Ask me the next quiz question as a poll."}
{"tool": "find_tools", "task": "Show me the city I guessed on a map."}
"""

FIND_TOOLS_PART = "looked for the tools of: {task}"
FIND_TOOLS_FOUND_PART = "looked for the tools of: {task}. found and offered: {tools}"
FIND_TOOLS_NONE_PART = "looked for the tools of: {task}. no tool fits it"
FIND_TOOLS_OFFERED_PART = "looked for the tools of: {task}. found {tools}, they were offered already"
FIND_TOOLS_ROUND_PART = """

THE TASK THE TOOLS WERE FOUND FOR
{task}"""

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

SPAWN_JOB_DESCRIPTION = "hands a task to a background job now: long or multi-step work, building a program, research with its own analysis, reporting back when it is done"

SPAWN_JOB_REPORT_PROMPT = """A background job you started for the user has finished.

JOB_PROMPT:
{prompt}

JOB_RESULT:
{summary}
{details}
{attachments}
Tell the user in one or two short sentences that the job is done and what it found. If JOB_RESULT says something failed, does not work or was not tested, tell the user that too and do not call it ready. Reply with the message only.
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
Use it for tasks that take long or have several steps, it starts right away and reports back when it is done.
Not for anything at a later time or repeating (reminders, alarms, every day, every hour, watching a price).
A conversation has one job at a time: while it runs, the user's messages go to it and it adjusts its plan.

Parameters:
- prompt (string, required): the full instructions for the job, in the user's own words. Keep every detail the user gave: what to do and what to report back. Never add names, numbers, tickers or places the user did not say. If the user says "these" or "my" without naming them, keep it like that and add: ask the user which ones.
To fix or change a program or project made earlier, say that it is in your files already and is changed there, not made again, name it if you know it, and keep what the user says is wrong or wants changed.

Examples:
{"tool": "spawn_job", "prompt": "find three reviews of the new Pixel phone and summarize them"}
{"tool": "spawn_job", "prompt": "the snake game in your files crashes when space is pressed: fix it there, not made again, and test it"}
{"tool": "spawn_job", "prompt": "compare the prices of my two favourite games in three shops and tell me where they are cheapest (ask the user which games)"}
"""

# ---------------------------------------------------------------- task (#170)

TASK_DESCRIPTION = ("does something for the user at a set time, once or repeating: reminders, alarms, wake up calls, daily news "
                    "or weather, checking a price every hour. also lists, changes and cancels these tasks")

TASK_CREATED_PART = "task #{id} is set: {task}. Tell the user in a few words when it runs."
TASK_COMPANION_PART = " Companion mode was switched on for this contact, tasks only run in companion mode: tell the user that too."
TASK_CHANGED_PART = "task #{id} is changed: {task}"
TASK_CANCELLED_PART = "task #{id} is cancelled: {task}"
TASK_LIST_PART = "the user's open tasks with you:\n{tasks}"
TASK_NONE_PART = "the user has no open tasks with you"
TASK_OTHERS_PART = "\n{count} more with other contacts, they are on the tasks page of the app"
TASK_LINE = "- {task}"
TASK_UNKNOWN_ACTION_PART = "unknown action {action!r}: create, list, edit or cancel"
TASK_NO_ID_PART = "the task's id is missing, it is the number in YOUR OPEN TASKS"

TASK_OPEN_PART = """
YOUR OPEN TASKS for the user (max {max_tasks} over all contacts, repeating at most every {min_interval} minutes):
{tasks}
"""

TASK_PROMPT = """
TASK:
Use when the user wants something done at a later time or again and again: a reminder, an alarm or wake up call, a daily summary, checking something every hour. Also to list, change or cancel their tasks.
At its time you do the task yourself: you look things up and write the user the result in this conversation.

Parameters:
- action (string, required): "create", "list", "edit" or "cancel"
- task (string, create, edit): what to do then, in the user's own words with every detail ("remind me to call mum", "check the bitcoin price and tell me only if it is below 50k")
- when (string, create, edit): the user's local time "07:30", "tomorrow 07:30", "friday 18:00", "2026-11-18 07:30" or a delay "in 20 minutes". Leave it out for "every N minutes or hours" from now on
- repeat (string, optional): "once" (default), "hourly", "daily", "weekdays", "weekly", "every 30 minutes", "every 2 hours"
- alarm (boolean, optional): true rings the user's app: alarms, wake up calls, "ring me", "wake me"
- id (number, edit, cancel): the task's number
{open_tasks}
Examples:
{{"tool": "task", "action": "create", "when": "in 20 minutes", "task": "remind me to take the pizza out of the oven", "alarm": true}}
{{"tool": "task", "action": "create", "when": "07:00", "repeat": "weekdays", "task": "wake me up and tell me the weather in Berlin", "alarm": true}}
{{"tool": "task", "action": "create", "repeat": "hourly", "task": "check the bitcoin price and tell me only if it is below 50k"}}
{{"tool": "task", "action": "cancel", "id": 3}}
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
Use for current weather and 3-day forecast.

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

WEBSEARCH_FOUND_PART = ("web search for {query}, the answers the pages give, the most accurate first:\n{answers}\n"
                        "Base what you say about it on these answers, do not add facts they do not give.")

WEBSEARCH_ANSWER_LINE = "{source}: {answer} ({url})"

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

WRITE_FILE_DESCRIPTION = ("writes one tiny text file (text only, no audio, images or archives) into your documents and attaches "
                          "it to your answer for the user to download")

SHARE_FILE_DESCRIPTION = ("attaches files or folders that are in your sandbox files already to your answer for the user to download")

WRITE_FILE_ATTACHED_PART = ("{file_names} are already attached to your answer as download buttons, the user saves them from there. "
                       "Do NOT write their code or content into your answer, no code blocks and no copy and paste instructions. "
                       "Only say in one or two sentences what each file is for and that it can be downloaded below.")

WRITE_FILE_NOT_ATTACHED_PART = ("Not attached: {problems}. Tell the user, do not claim these files were made or attached: "
                                "only files a tool result names exist.")

WRITE_FILE_SAVED_PART = "Kept in your files as {paths}."

WRITE_FILE_REFUSED_PART = "{name}: write_file writes text files only, it can not write audio, images or archives"

FILE_EXISTS_PART = "{path}: the file exists, pass \"overwrite\": true to replace it"

FILE_TOO_LARGE_PART = ("It is {size} MB, too large to attach (more than {limit} MB): it is kept in your files as {path}, "
                       "tell the user to download it from the conversation's files.")

WRITE_FILE_PROMPT = """
WRITE_FILE:
Writes one text file and puts it under your answer as a download button, the user saves it from there. For a short note, a small list, a small single script, or one text of a bigger job, like a chapter.
Text only: it can not write audio (.mp3, .wav, .ogg ...), images or archives, such a name is refused. One file per call, not a software project.
- path: a plain file name (shopping.txt, notes/todo.md) is kept in {documents}/<hash>/<path>, a new folder for every content, so it never overwrites another file.
  When the task names where the file goes, or later steps read it from a known place, give the full path in your files instead (~/projects/sea_book/chapter_01.md or {files}/projects/sea_book/chapter_01.md): the file is written exactly there. The tool result tells where the file was kept.
- overwrite: a file that is at the full path already is an error, unless "overwrite": true replaces it. Only for a file the task itself made or is told to replace.
Escape quotes and newlines inside content so the line stays valid JSON.

Parameters:
- path (string, required): a file name, or the full path under ~/ ({files}/), no ..
- content (string, required): the whole file
- overwrite (boolean, optional): replace a file at the full path, default false

Examples:
{{"tool": "write_file", "path": "shopping.txt", "content": "milk\\neggs\\n"}}
{{"tool": "write_file", "path": "~/projects/sea_book/chapter_01.md", "content": "# Chapter 1\\n..."}}
"""

TEXT_TO_SPEECH_DESCRIPTION = ("speaks a short text or text files of your sandbox files with your voice into one audio file "
                              "(a story, an audiobook, a podcast, a voice-over, a voice memo) and attaches it to your answer for the user to download")

TEXT_TO_SPEECH_MADE_PART = "{name} was spoken ({minutes} minutes)."

TEXT_TO_SPEECH_NOT_TEXT_PART = "{name} is not a text file, only text can be spoken"

TEXT_TO_SPEECH_FAILED_PART = ("The audio {name} was not made: {reason}. Tell the user, do not claim an audio file was made or attached.")

TEXT_TO_SPEECH_PLANNED_PART = ("The audio {name} is being spoken now, it takes a while and is attached to your answer as a download "
                               "button when it is ready. Say so in one sentence, do not write the text again.")

TEXT_TO_SPEECH_PROMPT = """
TEXT_TO_SPEECH:
Speaks text with your voice into one audio file and puts it under your answer as a download button, the user saves it from there. For an audio file the user wants to keep: a story, a poem, an audiobook, a podcast, a voice-over, a voice memo. Not for reading your answer out loud, the chat does that itself.
It speaks text only: the files have to be text files, not audio.
- text: a short text, up to a few paragraphs, written into the call.
- files: for anything longer, like the chapters or parts of a longer work: write the text into files first, then give their paths here, they are spoken one after another in the given order, with a short pause between them. A folder speaks all its files in name order. Relative to your current folder (where your last command ended), or absolute under {files}. Every word is spoken, also (asides), only code, links and markdown markers are left out. A heading is spoken as a sentence of its own.
- name: the audio file's name. Without an extension it becomes .wav, or .ogg (Ogg Opus) when it is long. End it with .mp3, .ogg or .wav when the task asks for that format (e.g. "an mp3": story.mp3), other formats can not be made. It is kept in {tts}/<hash>/. When the task names where the audio goes, give its full path instead (~/projects/sea_book/sea_book or {files}/projects/sea_book/sea_book): it is written there with its extension.
- overwrite: an audio file that is at the full path already is an error, unless "overwrite": true replaces it. Only for a file the task itself made or is told to replace.
- language: optional, the two letter code of the text's language (en, de, ...), else it is detected.

Parameters:
- text (string): the text to speak, or
- files (string or list of strings): the text files to speak, in order
- name (string, required): the audio file's name, or its full path under ~/ ({files}/)
- overwrite (boolean, optional): replace a file at the full path, default false
- language (string, optional): the language code

Examples:
{{"tool": "text_to_speech", "text": "Once upon a time there was a little fox.", "name": "fox_story"}}
{{"tool": "text_to_speech", "files": ["{files}/projects/sea_book/chapter_01.md", "{files}/projects/sea_book/chapter_02.md"], "name": "~/projects/sea_book/sea_book", "language": "en"}}
"""

JOIN_FILES_DESCRIPTION = ("joins several files of your sandbox files in their order into one file: audio files (.wav, .ogg, "
                          ".mp3) into one audio file, or text files into one text file, and attaches it to your answer")

JOIN_FILES_MADE_PART = "{name} was joined from {count} files{length}."

JOIN_FILES_AUDIO_PART = " ({minutes} minutes)"

JOIN_FILES_FAILED_PART = "The file {name} was not joined: {reason}. Tell the user, do not claim the file was made or attached."

JOIN_FILES_PROMPT = """
JOIN_FILES:
Joins files that are in your sandbox files already into one new file, in the given order, and puts it under your answer as a download button. The files stay as they are.
- files: at least two files, in the order they are joined. A folder joins all its files in name order. Relative to your current folder (where your last command ended), or absolute under {files}.
  Audio files (.wav, .ogg, .mp3) become one audio file with a short pause between them, they may differ in format and sound. Text files become one text file, a blank line between them. Audio and text can not be mixed.
- name: the new file's name, its extension says what it becomes: .mp3, .ogg or .wav for audio, any text extension (.txt, .md ...) for text. A plain name is kept in {tts}/<hash>/ (audio) or {documents}/<hash>/ (text). When the task names where the file goes, give its full path instead (~/projects/sea_book/sea_book.mp3 or {files}/projects/sea_book/sea_book.mp3). It can not be one of the joined files.
- overwrite: a file that is at the full path already is an error, unless "overwrite": true replaces it. Only for a file the task itself made or is told to replace.

Parameters:
- files (list of strings, required): the files to join, in order
- name (string, required): the new file's name with its extension, or its full path under ~/ ({files}/)
- overwrite (boolean, optional): replace a file at the full path, default false

Examples:
{{"tool": "join_files", "files": ["{files}/projects/sea_book/chapter_01.mp3", "{files}/projects/sea_book/chapter_02.mp3"], "name": "~/projects/sea_book/sea_book.mp3"}}
{{"tool": "join_files", "files": ["notes/part_1.md", "notes/part_2.md"], "name": "notes.md"}}
"""

SHARE_FILE_PROMPT = """
SHARE_FILE:
Puts files that are in your sandbox files already (made now or earlier, also in another conversation) under your answer as download buttons, the user saves them from there. It writes nothing. Use it after the work, for the files the user asked for or will want to keep, also when the user asks you to send or give them a file. Do not write their content again.
- path: a file, or a folder to share all of its files (.git, caches and installed packages are left out). Relative to your current folder (where your last command ended), or absolute under {files} (e.g. {files}/projects/fractal_explorer).
- Calls in the same answer as the calls that make the files run after them.

Parameters:
- path (string or list of strings, required): the files or folders

Examples:
{{"tool": "share_file", "path": "{files}/projects/fractal_explorer"}}
{{"tool": "share_file", "path": ["{files}/projects/fractal_explorer/main.py", "{files}/projects/fractal_explorer/README.md"]}}
{{"tool": "share_file", "path": "result.csv"}}
"""
