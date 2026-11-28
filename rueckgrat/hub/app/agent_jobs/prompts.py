"""
the agents' prompts (#152): the Controller plans a job; workers (Worker, #230) reach one goal each in a loop of tool calls: a job's, or the lookup of
a task or companion pass.

placeholders, filled with str.format (literal json braces are doubled):
  WORKER_PROMPT              role (the worker's role in the plan), task (its goal with its folder line and the earlier
                             results), check (WORKER_CHECK_PART or ""), tools (the tools' instructions
                             with WORKER_FINISH_TOOL_PART), per_turn (calls per turn), reply_chars (about how many
                             characters one reply holds, Worker._reply_chars)
  WORKER_CHECK_PART          check: its step's check, a command, folder: where it runs (Worker.folder)
  FOLDER_PART                path: a job worker's folder, absolute (Worker.folder)
  WORKER_EARLIER_PART        lines: the older turns, one short line per call (the same turns in a row as one), the newest that fit
  WORKER_LEFT_OUT_PART       count: the oldest turns that did not fit, at the start of the lines
  WORKER_RESULTS_PART        results: the results of a turn's calls, "[n] tool: text" each
  WORKER_BUDGET_LEFT_PART    calls (left), total, minutes (left)
  WORKER_NOT_RUN_PART        count: calls per turn
  WORKER_UNREADABLE_PART     text: the start of what could not be read
  WORKER_UNKNOWN_TOOL_PART   tool: the name it wrote, tools: its tools, comma separated
  WORKER_CHANGED_PART        files: the full paths a worker changed, comma separated
  WORKER_COMMANDS_PART       commands: its last commands with their exit codes, "; " separated
  SAVED_FILES_PART           paths: the full paths of the files a worker's tools wrote, comma separated (Worker.result_text)
  ATTACHED_FILES_PART        names: the files a worker holds for the user, comma separated (Worker.result_text)
  TOOLS_USED_PART            tools: the tools a worker called, comma separated, or "none" (Worker.result_text)
  PASS_GOAL_PART             goal: what a task or companion pass looks up (worker.lookup)
  PASS_FAILED_PART           reason: why a pass's lookup failed
  PLAN_PROMPT                prompt (the job), max_steps, projects (the contact's projects, one line each)
  CHECK_FAILED_PART          check: a step's check, output: its output (Controller.step)
  WORKER_ERROR_PART          error: why a step's worker without a check crashed
  WORKER_NO_ANSWER_PART      turns: failed turns in a row, reason: why the last chat got no reply (Worker.step, ends it as an error)
  WORKER_NO_CALLS_PART       turns: replies in a row without a call (Worker.step, ends it as an error)
  USER_MESSAGES_PART         messages: the user's messages while the job runs, one "- " line each (Controller._start)
  RETRY_PART                 failed: CHECK_FAILED_PART or WORKER_ERROR_PART, after the goal of the retry (Controller._start)
  CHECKED_PART               check: the check a finished step passed (Controller._results_text)
  JOB_FAILED_PART            step, total, role, attempts, failed: why the job failed (Controller.step)
RESULTS_MARKER_PART is also how a task is split again into its own part and the earlier results, change it only as a whole.
"""

# ---------------------------------------------------------------- the workers (Worker)

FOLDER_PART = "\n\nYOUR FOLDER: {path}/ (your commands start there)"
RESULTS_MARKER_PART = "\n\nRESULTS OF THE STEPS BEFORE:\n"    # the Controller appends the earlier results to a task after this
SAVED_FILES_PART = "files saved: {paths}"
ATTACHED_FILES_PART = "files offered to the user: {names}"
TOOLS_USED_PART = "tools used: {tools}"

WORKER_PROMPT = """You are the {role}, an agent that works in the background in turns: each turn you write 1 to {per_turn} tool calls and see their results.

YOUR GOAL:
{task}
{check}
- Facts come only from tool results and from your goal.
- One reply holds at most about {reply_chars} characters: write or change a bigger file in parts.
- Call finish when your goal is reached.

THE TOOLS:
{tools}

Reply with json only, a short note (what you learned, what you do next) and your calls:
{{"note": "...", "calls": [{{"tool": "...", ...}}]}}
"""
WORKER_CHECK_PART = "\nTHE CHECK: after you finish, the job runs `{check}` in {folder}/. Only it decides whether your goal is reached.\n"
WORKER_FINISH_TOOL_PART = """
FINISH:
Use as your last call, when your goal is reached or you can get no further.

Parameters:
- summary (string, required): what you made or found, with the facts and numbers the job needs

Example:
{"tool": "finish", "summary": "wordstat builds with cmake, ctest passes 12 tests"}
"""
WORKER_EARLIER_PART = "\n\nYOUR EARLIER TURNS (shortened):\n{lines}"
WORKER_LEFT_OUT_PART = "({count} turns before these are left out)"
WORKER_RESULTS_PART = "RESULTS:\n{results}"
WORKER_BUDGET_LEFT_PART = "{calls} of {total} calls and about {minutes} minutes left."
WORKER_NOT_RUN_PART = "not run, at most {count} calls per turn: write it again next turn"
WORKER_UNREADABLE_PART = "unreadable, write the call as json: {text}"
WORKER_CUT_OFF_PART = "your reply was cut off, its last call did not run: write shorter calls, a long file piece by piece"
WORKER_UNKNOWN_TOOL_PART = "{tool} is not your tool, not run (yours: {tools}, finish)"
WORKER_NO_CALL_PART = 'no call in your reply, write json: {"note": "...", "calls": [...]}'
WORKER_NO_RESULT_PART = "no result (nothing found)"
WORKER_CHANGED_PART = "files changed: {files}"
WORKER_COMMANDS_PART = "commands: {commands}"
PASS_GOAL_PART = """{goal}

What you find is for a message that is written after you finish: look up or do with your tools what that message needs
(facts, numbers, links, a poll, a map, files to offer). Then finish, what you found in the summary: the facts, numbers
and links as the tools gave them. When nothing needs a tool, finish at once, the summary "nothing to look up"."""
PASS_FAILED_PART = "the lookup failed: {reason}"

# ---------------------------------------------------------------- the Controller: plan, retry, result

CHECK_FAILED_PART = "the check `{check}` failed:\n{output}"
WORKER_ERROR_PART = "the worker ended with an error: {error}"
WORKER_NO_ANSWER_PART = "the llm did not answer {turns} times in a row: {reason}"
WORKER_NO_CALLS_PART = "{turns} replies in a row without a call"
USER_MESSAGES_PART = "\n\nTHE USER WROTE WHILE THE JOB RAN:\n{messages}"
RETRY_PART = "\n\nTHE LAST ATTEMPT did not reach the goal, {failed}"
CHECKED_PART = "checked: `{check}` passed"
NOT_CHECKED_PART = "not checked"
JOB_FAILED_PART = "step {step} of {total} ({role}) did not reach its goal after {attempts} attempt(s), {failed}"

PLAN_PROMPT = """Split a background job into steps for worker agents.

THE JOB:
{prompt}

The steps run one after the other, each by one worker that works on its own until its goal is reached; it gets the results of the steps before.
Prefer one step: a simple job, and also a whole software project, is one step. Use more only when the parts need different kinds of work
(e.g. research first, then writing), at most {max_steps}.
Each step has:
- role: one or two words, e.g. researcher, writer, developer
- goal: what the worker has to reach, self-contained with every detail of the job it needs and the paths of the files it makes. No commands.
- check: one shell command, run in the job's folder after the worker ends, that exits with 0 when the goal is reached. It builds and tests
  what the step makes and tests that the files the job asks for are there, e.g. "cmake -B build && cmake --build build && ctest --test-dir build && test -s chart.bmp"
  (exit code 124 of a timeout counts as passed). It installs nothing. "" for a step that makes no files.
The workers can search the web, read pages, write text files, speak text into audio files, join files, generate images and use a shell to make, build, run and test programs.
A work of several parts (e.g. an audiobook) keeps each part in its own file and joins them in its last step.
A new project gets a PROJECT.md whose first line says in one sentence what it is.
The projects so far (folder: first line of its PROJECT.md):
{projects}
Say in "project" which one the job works on: "continue" with a listed folder when the job changes it, "new" with a short lowercase
folder name when the job starts a project, "none" when it makes no software project. Also give the job a short name of two to five words.

Respond with json like this:
{{
    "name": "...",
    "project": {{"mode": "new|continue|none", "name": "..."}},
    "steps": [
        {{"role": "developer", "goal": "...", "check": "..."}}
    ]
}}
"""
