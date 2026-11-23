# Tools

This document describes the hub's tools: what a tool is, every tool there is, which tools a chat turn or an agent can use, how the tools of a message are chosen (detection, bands, rounds and the priority tools), how the calls run, how Laya's questions and thresholds are tuned, and what each tool does.

It follows what the code actually does (`rueckgrat/hub/app/tools/`, `tasks/tool_detection_task.py`, `tasks/tool_execution_task.py` and `hub/laya_tune/`). How agents use the tools is in `agents.md`.

# What a tool is

A tool is a subclass of `Tool` (`tools/tool.py`), itself a `Task` on the hub's task queue. One call of a tool is one JSON object such as `{"tool": "weather", "location": "Auckland"}`, written by the LLM in a tool setup round. The tool runs it and returns `{tool name: result}`, where the result has a `text` for the reply or an `error`, and maybe `sources`, `attachments` or held data.

A tool class describes itself with a few attributes:

| Attribute | Meaning |
| --- | --- |
| `description` | one line for the tool index and the LLM pick |
| `question` | the yes/no questions Laya is asked about the message |
| `thresholds` | (recommended, mandatory) for the scores, default (0.5, 0.7) |
| `whole_message` | its questions are also judged on the whole message |
| `text_only` | no Laya questions, only `text_score` detects it |
| `text_score()` | a score from code (a pattern or the message's shape), on the same scale as Laya's |
| `offered_with` | it is a companion: offered as optional together with these tools, no question of its own |
| `requires`, `requires_any` | capabilities it needs (all of `requires`, one of `requires_any`). Without them it is not detected, offered, listed or run |
| `overrides` | tools it makes needless when both are detected |
| `sequential` | its calls in one round run one after another, in their order |

`ToolRegistry` (`tools/tool_registry.py`) registers the tools at hub start and holds the rules for using them. `ToolRegistry.tools` only returns the tools whose capabilities are available right now (`Infrastructure.available`), so a tool disappears while its node or the internet is down.

# All tools

There are 25 tools, registered in this order in `ToolRegistry.__init__`.

| Tool | With Laya | Without Laya | Priority | Kind | Needs |
| --- | --- | --- | --- | --- | --- |
| `websearch` | Laya; always offered to a job's worker and a companion `news` pass's lookup | LLM pick; the same always-runs | | detected | internet or library |
| `generate_image` | Laya | LLM pick | | detected, detached | image |
| `take_photo` | not detected: a prompt tool; in a chat turn a reply tool | the same | | optional, detached | image |
| `convert` | Laya | LLM pick | | detected | |
| `calculate` | Laya | LLM pick | | detected | |
| `current_time` | Laya | LLM pick | | detected | |
| `date_calc` | Laya | LLM pick | | detected | |
| `wikipedia` | Laya | LLM pick | | detected | internet or library |
| `weather` | Laya | LLM pick | | detected | internet |
| `fetch_url` | only its text score: a link in the message (mandatory) | the same (never in the LLM pick) | | detected | |
| `remember` | not detected: a prompt tool; in a chat turn a reply tool | the same | | optional, detached | embedding |
| `search_memory` | not detected: a prompt tool | the same | | optional | embedding |
| `spawn_job` | Laya, also on the whole message; text score for a complex message; the project questions | LLM pick, sure when picked; the text score; no project questions | yes, second; ends the setup | detected | |
| `poll` | Laya | LLM pick | | detected, detached | |
| `show_map` | Laya; text score for a short "where is ..." | LLM pick; the text score | | detected, detached | internet or offline map |
| `price_finder` | Laya | LLM pick | | detected, overrides `websearch` | internet |
| `bash` | Laya; the project questions | LLM pick; no project questions | | detected, sequential | |
| `read_file` | not detected: a worker's loop tool | the same | | loop, sequential | |
| `edit_file` | not detected: a worker's loop tool | the same | | loop, sequential | |
| `write_file` | Laya; the project questions | LLM pick; no project questions | | detected, detached | |
| `share_file` | not detected: a companion of `bash` | the same | | companion, sequential | |
| `find_tools` | not detected: a prompt tool | the same | | optional | |
| `task` | Laya | LLM pick, sure when picked | yes, first; ends the setup | detected | |
| `text_to_speech` | Laya | LLM pick | | detected, detached | tts |
| `join_files` | Laya | LLM pick | | detected | |

Without Laya, an LLM pick makes a picked tool recommended, a picked `task` or `spawn_job` sure; if the pick fails, only the text scores count. A message of fewer than 4 words always uses only the text scores (see Detection). The kinds:

- detected: the detection decides whether it is mandatory, recommended or not offered.
- optional: one of the `PROMPT_TOOLS` (`remember`, `search_memory`, `take_photo`, `find_tools`). Every tool setup offers them, and the model decides on its own whether to call them.
- companion: offered as optional whenever one of its `offered_with` tools is offered.
- loop: in `LOOP_TOOLS`. Only a job's worker has them, in its loop (see `agents.md`); no tool setup detects or offers them.
- detached: in `DETACHED_TOOLS`. In a chat turn its calls can go on in the background (see Running the calls).

## Who can use which tool

`MetaTask` is a chat turn, `Worker` a job's worker (the `Controller` itself runs no tools), `TaskJob` a task pass and `CompanionJob` a companion pass: each pass's lookup is a `Worker` too (`lookup`). An agent's tools are fixed when its worker starts, see `agents.md`.

| Tool | `MetaTask` | `Worker` | `TaskJob` | `CompanionJob` |
| --- | :---: | :---: | :---: | :---: |
| `websearch` | ✓ | ✓ | ✓ | ✓ |
| `generate_image` | ✓ | ✓ | ✓ |  |
| `take_photo` | ✓¹ |  |  | ✓² |
| `convert` | ✓ | ✓ | ✓ | ✓ |
| `calculate` | ✓ | ✓ | ✓ | ✓ |
| `current_time` | ✓ | ✓ | ✓ | ✓ |
| `date_calc` | ✓ | ✓ | ✓ | ✓ |
| `wikipedia` | ✓ | ✓ | ✓ | ✓ |
| `weather` | ✓ | ✓ | ✓ | ✓ |
| `fetch_url` | ✓ | ✓ | ✓ | ✓ |
| `remember` | ✓¹ |  |  |  |
| `search_memory` | ✓ |  | ✓ | ✓ |
| `spawn_job` | ✓ |  | ✓ |  |
| `poll` | ✓ |  | ✓ | ✓ |
| `show_map` | ✓ |  | ✓ | ✓ |
| `price_finder` | ✓ | ✓ | ✓ | ✓ |
| `bash` | ✓ | ✓⁴ | ✓ | ✓ |
| `read_file` |  | ✓⁴ | ✓³ | ✓³ |
| `edit_file` |  | ✓⁴ | ✓³ |  |
| `write_file` | ✓ | ✓ | ✓ |  |
| `share_file` | ✓ |  | ✓³ | ✓³ |
| `find_tools` | ✓ |  |  |  |
| `task` | ✓ |  |  |  |
| `text_to_speech` | ✓ | ✓ | ✓ |  |
| `join_files` |  | ✓ | ✓ |  |

¹ Not in the tool setup: the chat reply calls it itself at its end (`REPLY_TOOLS`).
² Only when the contact's settings allow photos.
³ A pass's lookup gets them with a detected `bash` (`FILE_KIT`).
⁴ A job's worker always has them (`JOB_TOOLS`, with `reset_sandbox` and `websearch`). It never offers files: the job delivers them (`JOB_EXCLUDED`).

The exclusions come from `CHAT_EXCLUDED_TOOLS` and `REPLY_TOOLS` (`MetaTask`), `WORKER_EXCLUDED_TOOLS` with each worker's `allowed` and `excluded` (a pass's `ALLOWED_TOOLS` and `EXCLUDED_TOOLS`), and the companion settings. Both excluded lists hold the `LOOP_TOOLS`. What an agent's worker always has: `websearch` for a job's worker, `search_memory` for a pass's lookup, `take_photo` for a companion's, `websearch` for a `news` pass. Every tool still needs its capabilities (Needs above).

# Choosing tools

Chat turns choose their tools this way. Agents (a job's workers, the lookups of task and companion passes) run one detection when they start and then call their tools in a loop, see Workers in `agents.md`:

1. A `ToolDetectionTask` scores the candidate tools and puts them into a mandatory and a recommended band.
2. A `ToolExecutionTask` runs tool setup rounds: in each round the LLM writes the calls for that round's tools, and the calls run.

The rules for the two priority tools, `task` and `spawn_job`, are part of this one path and do not depend on how the tools were detected.

## Detection

`ToolDetectionTask` (`tasks/tool_detection_task.py`) scores every candidate tool. The candidates are the tools that can be used now, minus the excluded ones and minus the optional ones (prompt tools and companions are offered without a detection). The source of the decision is recorded (`source()`):

| Source | When | How the scores come about |
| --- | --- | --- |
| `short` | the message has fewer than 4 words (`MIN_DETECTION_WORDS`) | only the tools' text scores |
| `laya` | Laya answers | one Laya question per tool question (`Tool.question`, or one made from the description; `text_only` tools get none). A `whole_message` tool (`spawn_job`) is also judged on the whole message. A tool's score is its best answer. The text scores are max'd in |
| `llm` | Laya is down (`decide_whole` returns `None`) and the LLM picks | one LLM call (`TOOL_PICK_PROMPT`, temperature 0, a JSON schema that only allows the candidates' names) picks from the names and descriptions. A picked tool gets its recommended threshold, a picked `PRIORITY_TOOLS` tool its mandatory threshold, so it is sure exactly as when Laya is sure of it. The text scores are max'd in |
| `text` | Laya is down and the LLM pick failed | only the text scores |

A tool is mandatory when its score reaches its mandatory threshold and recommended when it reaches its recommended threshold. The defaults are 0.5 and 0.7 (`RECOMMENDED_THRESHOLD`, `MANDATORY_THRESHOLD`). Most tools set their own in their code (`Tool.thresholds`).

The text scores:

- `fetch_url` scores 1.0 when the message holds a link (`URL_PATTERN`), so it is mandatory.
- `spawn_job` scores its recommended threshold (0.7) when `MessageShape(prompt).complexity()` is at least 0.4 (`JOB_COMPLEXITY`), a message of several steps. A text score never makes it mandatory.
- `show_map` scores 0.6 (above its mandatory threshold) for a short question like "where is ..." (`SHORT_WHERE`), unless the place is a word like "the" without a name after it.

In a chat turn the detection also gets the contact's `SandboxVolume`, and Laya is asked the `PROJECT_QUESTIONS` too: does the user report a bug in a program, or ask for a fix or change to something made earlier? If that score reaches 0.5 and the contact's files hold a project (`SandboxVolume.has_project`), the `PROJECT_TOOLS` (`spawn_job`, `bash`, `write_file`) get that score.

## Bands

`ToolRegistry.bands(mandatory, recommended)` turns the scores into the final bands. This is the one place where the priority rules for a detection live, whatever its source:

- `PRIORITY_TOOLS = ("task", "spawn_job")`, highest first.
- Before that a priority tool that would outrank a mandatory priority tool but does not take over for this message (`Tool.takes_over`) is dropped from both bands (`ToolRegistry.yielding`, called by `ToolDetectionTask._bands`): `task` takes over from `spawn_job` only when the message says when to act (`user_tasks.SCHEDULE`: in 2 hours, every morning, daily, tomorrow, at 7pm, on Friday, a date). A build request that ends with "tell me when it works" or "share it with me" is a job, not a task.
- A mandatory priority tool becomes the only mandatory tool. Of the recommended tools only the ones that outrank it stay (`task` over `spawn_job`).
- Otherwise a tool that another one overrides (`Tool.overrides`, only `price_finder` over `websearch`) is dropped: by a mandatory tool from both bands, by a recommended one only from the recommended band.

`ToolExecutionTask` then adds the `PROMPT_TOOLS` to the mandatory band, drops the excluded tools and the ones that cannot be used now, and adds the companions of the offered tools to the mandatory band (`share_file` with `bash`). The setup prompt lists three kinds of tools (`split_tools`): mandatory (detected, must be called), recommended (the model decides), and optional (prompt tools and companions).

## Rounds

`ToolRegistry.rounds(mandatory, recommended)` groups the tools into setup rounds in `TOOL_ORDER`:

```
1  spawn_job, current_time, task
2  date_calc
3  search_memory, find_tools, wikipedia, websearch, fetch_url, weather, price_finder
4  convert
5  calculate, bash, read_file, edit_file, share_file
6  show_map, poll, write_file, generate_image, take_photo, remember
7  text_to_speech
8  join_files
```

Only groups with a tool in them become rounds. A setup with nothing but prompt tools is one round.

A recommended priority tool gets a round of its own:

- It comes first when it outranks every sure tool. A sure tool is a mandatory tool that is not optional, so the prompt tools and the companions never count.
- Otherwise it comes last, so an uncertain priority tool does not take over from a sure tool (for example a mandatory `bash` or `fetch_url`).
- A mandatory priority tool is alone in its band anyway (see Bands).

After each round `ToolRegistry.ends_setup` looks at the calls of that round. If a priority tool was called, nothing runs after that round. So when `spawn_job` is called, the turn does not also write files or run commands.

## A setup round

Each round is one LLM call (`ToolExecutionTask._round`, temperature 0, seed 1337, `max_new_tokens` from `Infrastructure.long_reply_tokens()`). The prompt (`ToolPromptCompiler`) holds the task, the results so far, the offered tools with their prompts, the notes on tools used together (`TOOL_NOTES`, for example that `spawn_job` is for work now and `task` for anything later), the user's timezone and, in a chat turn, the last two messages before this one.

Then:

- Calls of tools that were not offered in this round are dropped.
- A recommended tool's call whose values do not come from the message or the results so far is dropped as made up (`ToolRegistry.grounded`). A plain `ls` of the conversation's work folder counts as grounded (`BashTool.looks_around`).
- A reply that was cut off (an unclosed last call, or the LLM hit its token limit) gets a note for the tool whose calls are missing (`cut_off_result`), so later rounds and the reply know it did not run.

`find_tools` calls start a new detection on the task they name. Newly found tools that were not offered yet get extra rounds, with `find_tools` offered again, at most twice in a row (`FIND_TOOLS_STEPS`).

## Running the calls

`ToolRegistry.execute` runs the calls of a round together, each on its own thread (not on the task queue's workers, so they cannot block each other). The calls of `sequential` tools (`bash`, `read_file`, `edit_file`, `share_file`, `reset_sandbox`) share one lane and run one after another in their order, because they work on the same files. Calls of excluded tools are dropped, also when the LLM wrote them without being offered the tool.

Detached calls: in a chat turn, a call of a `DETACHED_TOOLS` tool (`show_map`, `poll`, `write_file`, `generate_image`, `take_photo`, `remember`, `text_to_speech`) for a stored message starts in the background and is not waited for. The reply gets the tool's planned result instead (made from the call alone), and the tool attaches its file or data to the message when it is done. If the turn is already gone, those calls are dropped.

Background calls: the calls of an agent's `Worker` (a job's worker, a pass's lookup) are marked `background` (`Tool.background`), with `JOB_LLM_TIMEOUT` for tools that call the LLM (`Worker._run`). A chat turn's setup drops both keys from the calls the LLM writes (`ToolExecutionTask._call`). Nobody waits for them. These calls have no stored message, so tools that would attach a file or show data hold it in their result instead (`attachments`, `held_data`). Whoever posts the agent's message attaches or shows it there (`ToolRegistry.attach_held`, `show_held`).

## Results

The results of all rounds are merged per tool (`Tool.merge`: texts on separate lines, lists added up). For the reply they become a `TOOL_RESULTS` block, one line per tool. A failed tool keeps its text, or shows `failed: <error>`, so the reply does not claim it worked. The pages that `websearch`, `wikipedia` and `fetch_url` used are stored as the message's sources and shown as links under the answer.

## Reply tools

A chat reply can call `remember` and `take_photo` itself (`REPLY_TOOLS`): they are JSON lines at the end of the reply. `split_reply` keeps them out of the text the user sees, and `MetaTask` runs them after the reply, for the reply's message.

# Laya tuning

Laya itself is not trained in this repository. What is tuned are the tools' Laya questions (`Tool.question`) and their thresholds (`Tool.thresholds`). Both are edited by hand in the tools' code; the thresholds' comments say they come from `laya_tune/tune.sh`. The tuning lives in `rueckgrat/hub/laya_tune/` (`DEVELOPMENT.md`, "Laya tuning"):

- `dataset.jsonl`: one example per line, `{"lang": "en", "text": "Quiz me on capitals", "labels": {"poll": "M"}}`. `"M"` means the tool should be mandatory, `"r"` that recommended or mandatory are both fine. A tool not in `labels` should stay below its recommended threshold. It has 534 examples, all in English, 82 of them without any label.
- `tune.sh`: runs `tune.py` in the `rueckgrat-hub` image (host network) with the current `hub/app` and the chat's `app/common` mounted, so edited questions count without a rebuild. `LAYA_DECIDE=host:port` picks the `text_to_decision` node.
- `tune.py`: scores every example the way the hub does. It runs the real `ToolDetectionTask` on the text and takes `tool_scores()`: the best of each tool's questions, also on the whole message for a `whole_message` tool, max'd with its text score. Only `decide` is used: the `Infrastructure` has no config and no node connections, and no contact files, so the project questions are not asked.

For each language and each tool with questions, `tune.py` prints:

- how many examples the current thresholds get right (`M`: the score reaches mandatory; `r`: it reaches recommended; no label: it stays below recommended);
- a recommended (recommended, mandatory) pair: the pair with the most correct examples on a grid of 0.20 to 0.95 in steps of 0.05, mandatory at least 0.5 and recommended below it, the one nearest the current pair on a tie. A tool with fewer than 3 labelled examples gets no recommendation;
- the total over all tools, in percent.

The same dataset was used to measure `MessageShape` (`utils/message_shape.py`), whose complexity gives `spawn_job` its text score.

# The tools

## websearch

Searches the web (DDGS search engines) and the offline library (Project NOMAD) for a `query`, the library in parallel with the web. The pages are read, and the answers found in them compete by quality for the best three (`GOOD_ANSWERS`). If the web finds nothing useful, it tries once more with only the key words. Without internet only the library is searched. The pages used become the answer's sources. A worker gets `websearch` in any case, unless its detection found a build tool; an empty search does not fail the worker.

## generate_image

Generates a picture from a `positive_prompt` on the image node. With a stored message the planned file is attached at once and filled when the image is done (it is detached in a chat turn). Without one (agents) the file is held in the result's `attachments` and attached to the message the agent posts later.

## take_photo

Takes a photo of the contact (`subject: "self"`), the user (`"user"`) or both (`"both"`) in the current situation, through the image node (`AssistantImageTask`). A single person is portrait (768×1024), both together landscape. In a chat turn it is a reply tool. A companion pass may take one if the contact's settings allow photos; it is sent with the companion's message.

## convert

Converts an `amount` `from` one unit `to` another. Physical units (length, weight, temperature and more) are fixed in the code and work offline. Currencies, crypto and the prices of gold, silver and platinum need exchange rates from the web (a free currency API), or the saved rates when the internet is down.

## calculate

Evaluates an arithmetic `expression` exactly, with a safe evaluator of the Python syntax tree: the usual operators, functions like `sqrt`, `log`, `sin`, `factorial` and the constants `pi`, `e`, `tau`. The expression is at most 200 characters, exponents at most 1000.

## current_time

Returns the current date, time and weekday in a `timezone` (a city or a zone name). Without one, or with a word like "here" or "my", it uses the user's timezone.

## date_calc

Counts the days between a `start` and an `end` date, or adds `days` to a start date, and gives the weekdays. Dates are `YYYY-MM-DD` or `today`, in the user's timezone unless the call names one.

## wikipedia

Looks up a `query` on Wikipedia (in `lang`, English by default), or in the offline library's copy without internet. Returns the article's summary with the source link.

## weather

The current weather and a 3-day forecast for a `location`, from open-meteo (geocoding and forecast, no API key).

## fetch_url

Reads the web page of a `url` the user gave and returns a condensed summary, optionally about a `focus`. It tries plain HTTP first and a headless browser when that comes back thin or blocked (20 s per page). It needs no capability: a link in the local network works without the internet. It has no Laya questions; a link in the message makes it mandatory.

## remember

Saves one short fact (`text`, at least 2 words, at most 200 characters) as a memory of the contact, as an embedding. A fact that means nearly the same as one the contact already has is not saved again. A chat reply calls it itself at its end. Agents cannot use it.

## search_memory

Searches what the user told the contact before, for a `query`: the 5 nearest memories of the contact, and up to 3 summaries of its other conversations that Laya judges to be about the question (without Laya, all of them). It is a prompt tool, so every setup offers it.

## spawn_job

Hands a `prompt` to a background job: a Controller plans it and runs worker agents, then the contact reports in a new message. It is also how code is run: a program to write and run, or code from the user's message to run (word for word), becomes a job whose worker writes and runs it in the sandbox with `bash`. There is at most one job per conversation. It is the second priority tool: when it is called, nothing runs after its round. See `agents.md`.

## poll

Shows a poll bubble with a `question`, `options` and a `mode` (one choice or several). The client shows it under the message (the message's `poll` data). The user's answer comes back as a chat message with `poll_answer`, which locks the poll. A quiz goes on poll by poll: the setup of the next turn sees the last answer and the message before it.

## show_map

Shows a map bubble of an `address` with a `label`. The address is geocoded online (Nominatim, Photon, open-meteo) or, without internet, with the offline library's coordinates. The client gets the map as the message's `map` data, and its tiles come through the hub.

## price_finder

Searches shops on the web for a product (`query`, with "price" added) and ranks the finds by price or by how well they match (`rank`). It reads up to 10 pages, 5 at a time. One LLM call per page reads its offers (`FindOfferTask`), and only offers whose price is really on the page are kept. The best three are shown on a podium under the answer, with more finds in a list (the message's `prices` data). When it is detected, `websearch` is dropped (`overrides`).

## bash

Runs one `command` in the contact's sandbox container (`SandboxContainer`, image `rueckgrat-sandbox`: Debian with Python and numpy, pandas, matplotlib, scipy, scikit-learn, scikit-image, seaborn, pillow and plotly, git, curl, gcc, g++, make, cmake, ninja and SDL2) with network, in the contact's persistent files, as the sandbox user with sudo (`sudo apt-get install` works, the installs stay while the container lives). Each call has its own timeout (120 s) and result; a failing command does not stop the next, what it left running is killed. Like an open terminal per conversation, the folder, exported variables and functions carry over between calls, running processes do not. The prompt names the container's CPUs and memory. This is where projects are made and changed. A job's worker gets its loop rules instead of the one-turn rules of a tool setup (`BASH_LOOP_PART`, `BASH_ONE_TURN_PART`).

## reset_sandbox

Starts the contact's sandbox over (`what`, `system` by default): a fresh container from the clean image, when the agent broke the system or the user asks for a clean one (installs, their record and processes go, nothing is installed again, the files stay). Only when the user explicitly asks: `files` brings the files back to the backup made before the last worker that changed them (the replaced files are kept in the backup's safety copy, the agent cannot bring them back), `all` both. It has no question of its own: it is offered whenever `bash` is, and a job's worker always has it (`JOB_TOOLS`), a lookup with `bash` (`FILE_KIT`). Companion passes never get it.

## read_file

A worker's loop tool. Reads a text file of the contact's files (`path`, up to 1 MB) from line `start`, `lines` lines (200, at most 400), numbered, long lines cut at 500 characters.

## edit_file

A worker's loop tool. Changes a text file of the contact's files: `old` (must be in the file exactly once) becomes `new`. An empty `old` writes the whole file with `new`. The result names the saved file.

## write_file

Writes one text file (`path`, `content`) into the contact's files and offers it to the user. A plain name is kept under `data/documents/<hash>/`, so it never overwrites another file. A full path (`~/projects/x/a.md`) is written there, and a file that is there is only replaced when the call says `overwrite`. Audio, image and archive names are refused: text only. In a chat turn it is detached (the file is checked first, written in the background).

## share_file

Offers files that are already in the contact's files to the user as download cards, without writing anything. A `path` (or a list) is a file or a folder: all its files up to 50, without `.git`, caches and packages. Relative paths start at the conversation's bash folder. It has no question of its own: it is offered whenever `bash` is, and runs after their calls in the same round. For a job, a task pass or a companion pass the files are held and attached to the message the agent posts later.

## find_tools

Asks for the tools of a `task` that the offered tools cannot do (for example the next quiz question as a poll). The call only notes the task. `ToolExecutionTask` runs a detection on it and offers what it finds in extra rounds.

## task

Manages the user's tasks with this contact: `create` (`task`, `when`, `repeat`, `alarm`), `list`, `edit` and `cancel` (by `id`). Its prompt lists the contact's open tasks with their ids. It is the first priority tool: it outranks `spawn_job` when the message says when to act (`TaskTool.takes_over`, see Bands), and nothing runs after its round. When a task is due, `CompanionScheduler` runs it as a `TaskJob`. See `agents.md`.

## text_to_speech

Speaks a short `text`, or text files of the contact's files in their order, into one audio file `name`, with the user's chosen voice or else the contact's, in a `language`. It works chunk by chunk, so a long text never goes through the LLM. The file is `.wav`, `.ogg` when it is large, or the format the name asks for (`.wav`, `.ogg`, `.mp3`). A plain name is kept under `data/tts/<hash>/`, a full path is written there (replaced only with `overwrite`). The file is offered to the user unless it is too large; then it stays in the files. It needs the TTS node. In a chat turn it is detached, since speaking a chapter takes minutes.

## join_files

Joins `files` of the contact's files in their order into one new file `name`. An audio name (`.wav`, `.ogg`, `.mp3`) joins audio files, with a pause between them and converted to the first file's format; any other name joins text files, with a blank line between them (at most 10 MB). The file is kept and offered like `write_file`'s. Chat turns cannot use it (`CHAT_EXCLUDED_TOOLS`): it is for workers and task passes.