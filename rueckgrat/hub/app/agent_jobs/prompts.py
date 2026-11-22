"""
the background jobs' prompts (#152): the Controller plans a job, reviews it after each step, revises a failed task and
merges the results; its workers (AgentJob) do one task each with the tools' results.

placeholders, filled with str.format (literal json braces are doubled):
  WORKER_PROMPT              role (the worker's role in the plan), prompt (its task), tools (the TOOL_RESULTS block or "")
  FAILED_TOOLS_PART          failed: the failed tools with their errors, "; " separated
  SAVED_FILES_PART           paths: the full paths of the files a worker's tools wrote, comma separated (AgentJob.result_text)
  FILE_TOOLS_STUCK_PART      problems: what its file making tools still failed with after the fix rounds, "; " separated
  STUCK_VERDICT_PART         problems: the same, after a stuck worker's prompt: only UNSUPPORTED keeps it from failing
  UNSUPPORTED_PART           reason: how far a worker got, what the sandbox lacks for the rest and how to run it (AgentJob.result_text)
  UNSUPPORTED_NO_REASON_PART none: the reason of an UNSUPPORTED: line without one
  IDLE_WORKER_PART           offered, called: the tools a worker was offered and the ones it called, comma separated ("none")
  ATTACHED_FILES_PART        names: the files a worker holds for the user, comma separated (AgentJob.result_text)
  TOOLS_USED_PART            tools: the tools a worker called, comma separated, or "none" (AgentJob.result_text)
  NOT_DELIVERED_PART         none: the job makes files but no worker saved or holds one (Controller._delivered)
  PLAN_PROMPT                prompt (the job), max_steps, max_workers, projects (the contact's projects, one line each)
  PROJECT_NEW_PART,
  PROJECT_CONTINUE_PART      path: the job's project folder (Controller._project), after each task (AgentJob.set_project)
  REVIEW_PROMPT              done, total (finished step of how many), prompt, messages (the user's messages since the start,
                             one "- " line each, or "none"), results, remaining, max_steps, max_workers
  MERGE_PROMPT               prompt, results
  RETRY_PROMPT               prompt, role, task (the failed task), reason
  RETRY_EXCLUDED_TOOLS_PART  tools: the tools the new worker is not offered, comma separated
NO_WEBSEARCH_PART, EMPTY_WEBSEARCH_PART and FAILED_TOOLS_PART go in front of a worker's TOOL_RESULTS block.
RESULTS_MARKER_PART is also how a task is split again into its own part and the earlier results, change it only as a whole.
"""

# ---------------------------------------------------------------- the workers (AgentJob)

NO_WEBSEARCH_PART = "\n\nNo web search was done for this message. If you don't know current facts like opening hours, prices or news, say so.\n"
EMPTY_WEBSEARCH_PART = ("\n\nThe web search found nothing useful. Do the task with the results of the steps before and your own knowledge, "
                   "and say which facts you could not check.\n")
FAILED_TOOLS_PART = ("\n\nThese tools failed: {failed}. Do the task with what you have and your own knowledge, and say what could not be checked. "
                "Reply FAILED: only when the task can not be done at all without them.\n")
PROJECT_NEW_PART = ("\n\nTHE PROJECT FOLDER: {path}/ is this job's new project, it was empty when the job started. Work only in it: "
                    "every file of the project goes there, a project folder the task names means this one.")
PROJECT_CONTINUE_PART = ("\n\nTHE PROJECT FOLDER: {path}/ is the existing project this job changes. Work only in it: "
                         "every file of the project goes there, a project folder the task names means this one.")
RESULTS_MARKER_PART = "\n\nRESULTS OF THE STEPS BEFORE:\n"    # the Controller appends the earlier results to a task after this
SAVED_FILES_PART = "files saved: {paths}"
FILE_TOOLS_STUCK_PART = "the files of the task were not made, still failing after the fix rounds: {problems}"
STUCK_VERDICT_PART = """

THESE CALLS STILL FAIL AFTER THE FIX ROUNDS: {problems}
The task failed, unless the only reason is that this sandbox does not have what the failing step needs (see UNSUPPORTED above)."""
UNSUPPORTED_PART = "not checked (the sandbox can't do it, how far it got - what is missing - how to run the rest): {reason}"
UNSUPPORTED_NO_REASON_PART = "the sandbox lacks what the check needs"
IDLE_WORKER_PART = ("the task makes or uses files or runs commands, but nothing was made, run or saved: no tool for it was called "
                    "(offered: {offered}; called: {called})")
ATTACHED_FILES_PART = "files offered to the user: {names}"
TOOLS_USED_PART = "tools used: {tools}"
NOT_DELIVERED_PART = ("NOTHING WAS DELIVERED: the job asks for files, but no step saved a file or offered one to the user. "
                      "Whatever the results claim, no file was made.")

WORKER_PROMPT = """You are the {role} in a background job. Do your task and report what you found or made.
Facts, numbers and dates come only from the tool results below and from the task itself. Name the source of each fact as the tool results give it. Never make up facts, numbers or sources.
Stay factual and neutral: report what the sources say, also where they disagree, without taking sides.
Do only your own task: the job's other steps are done by other workers, do not do their part (e.g. a writer writes the text, it does not make the audio of it).
Files the steps before saved are listed with their full paths ("files saved:"): use them, do not write them again.
A file in another format than the task asks for, with the same content, does the task (e.g. audio as .ogg instead of .mp3, text as .md instead of .txt): say which format it is, that is not a failure.
Only what the tool results below show counts as done: a file is made, a command is run or a check passed only when a tool result says so. Never report files, commands, outputs or exit codes the tool results do not show.
If you can not do the task with what you have, or a check of your task failed, start your reply with FAILED: and the reason.
Only when a step can not run because this sandbox does not have what it needs (a system package or library that is not installed and can
not be, no root or apt-get, no display, no sound, no hardware or service), add one line: UNSUPPORTED: how far it got - what is missing - how the
user runs the rest on their own machine, e.g. "UNSUPPORTED: compiled, not linked - SDL2 is not installed - apt install libsdl2-dev, then
cmake --build build && ./build/game". How far it got, best first: everything worked (then no UNSUPPORTED line); built, the tests or the program
not run; compiled, not linked; files made, not compiled. The files of the task must be made, the rest goes as far as this sandbox can: do what it
can (compile what compiles, run the tests that don't need what is missing). A compile error in the project's own code, a failing test, a crash or
a missing file of the task is FAILED, not UNSUPPORTED. When both apply, FAILED.

YOUR TASK:
{prompt}
{tools}
Reply with the result only.
"""

# ---------------------------------------------------------------- the Controller: plan, review, retry, merge

PLAN_PROMPT = """Split a background job into steps for worker agents.

THE JOB:
{prompt}

The steps run one after the other, each step gets the results of the steps before it.
The tasks inside one step run at the same time, so they must not need each other's results.
Use as few steps and tasks as the job needs, at most {max_steps} steps and at most {max_workers} tasks per step. A simple job is one step with one task.
Each task has a role (one or two words, e.g. researcher, analyst, writer) and a prompt: full instructions the worker can follow on its own. Keep every detail of the job the task needs.
The results of the steps before are added to each task automatically, so write every task self-contained and never use placeholders like {{design_context}} for them.
Each worker can use the hub's tools on its own, e.g. a web search, reading a web page, wikipedia, the weather, calculations and conversions,
writing text files, speaking text files into audio files (.mp3, .ogg or .wav, no other audio format), joining files into one file
(audio files into one audio file, text files into one text file) and generating images the user gets with the job's report.
Writing files makes text only: audio comes only from speaking text or from joining audio files.
A work made of several parts (e.g. an audiobook, a podcast, a narrated documentary) keeps each part as its own file (one text file per chapter, episode or scene)
and combines them at the end: one task speaks all the text parts into one audio file in one go, or one task per part makes its audio
followed by a task that joins those audio files in order.
A task that makes files names each file and its path (e.g. index.html, css/style.css). Each task does only its own part and names only that: a writer task writes the text and does not mention audio, narration or
the final medium, turning the text into audio (or another medium) is a task of its own.
A software project lives in its own folder ~/projects/<project-name>/ (short, lowercase, e.g. my_project): every task of the project names that folder,
the task that creates the project also writes its PROJECT.md there (first line: what the project is in one sentence, then its status and how to run it).
To change an existing project, its tasks work in its folder.
The projects so far (folder: first line of its PROJECT.md):
{projects}
Say in "project" which project the job works on: "continue" with the folder of one of these exactly as listed when the job changes,
fixes or extends that project; "new" with the folder name it wants when the job starts a project (also a new version of a listed one,
e.g. in another language), the job then gets a free folder of that name or a similar one; "none" when the job makes no software project.
When the job makes code or something that runs (a program, a script, a website, a software project), add a last step with a tester task, unless the job is tiny.
Write the tester's prompt as the commands it runs, in order and all at once, with no "if" steps: list the files, set up what the project needs
(e.g. python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt), check every file the job asks for by name
(e.g. python3 -m py_compile a.py b.py, node --check, cmake -B build && cmake --build build), so a missing one fails, run the tests (e.g. pytest)
and run the program with a time limit (e.g. timeout 10 python3 main.py, exit code 124 means it was still running, that passed).
What fails it fixes and runs again in its fix rounds. A step the sandbox can't do (it does not link for a missing system library, the tests need a
package that can't be installed, no display) it reports as not checked, with how far it got and what is missing, instead of failing: write its
commands anyway, the files made and what compiles are a result. Then it updates the project's PROJECT.md (status, how to run it), shares the finished project folder with share_file and reports each command it ran with its exit code. A job that only makes text, data or images does not need it.
Say in a task's prompt what it has to look up. A research task names the time period (e.g. "2021 to 2031"), the scope
(e.g. country, measure, which kind of predictions) and the sources it must check (e.g. the central bank, the statistics office, the big banks).

Also give the job a short name of two to five words (e.g. "NZ cash rate forecast").

Respond with a json structure like this:
{{
    "name": "...",
    "project": {{"mode": "new|continue|none", "name": "..."}},
    "steps": [
        [{{"role": "researcher", "prompt": "..."}}],
        [{{"role": "analyst", "prompt": "..."}}, {{"role": "analyst", "prompt": "..."}}],
        [{{"role": "writer", "prompt": "..."}}]
    ]
}}
"""

REVIEW_PROMPT = """A background job runs in steps of worker agents. Step {done} of {total} is finished. Decide how the job goes on.

THE JOB:
{prompt}

THE USER'S MESSAGES SINCE THE JOB STARTED (newest last, ignore those that are not about the job):
{messages}

THE RESULTS SO FAR:
{results}

THE REMAINING STEPS:
{remaining}

A step did only what its "tools used:", "files saved:" and "files offered to the user:" lines show: when it says it made files, ran commands
or tested something but no tool that does that was used, it did not do it, treat its files and checks as missing.

Choose one action:
- "continue": the remaining steps still fit.
- "replan": the results so far stay, but the remaining steps must change, e.g. a step found nothing useful, the results
  show a better way, or the user added or changed something. Give the new remaining steps.
- "restart": the user changed the job so much that the results so far do not fit any more. Give a new plan from the start.
New steps follow the same rules as the plan: at most {max_steps} steps and at most {max_workers} tasks per step, the tasks
of one step run at the same time, each task has a role and a prompt with full instructions, including the user's changes.

Respond with a json structure like this:
{{
    "action": "continue",
    "name": "only if the job changed: a new short name of two to five words",
    "steps": [
        [{{"role": "researcher", "prompt": "..."}}]
    ]
}}
"steps" only for replan and restart.
"""

RETRY_PROMPT = """A worker agent of a background job failed its task. Write the task again for a new worker.

THE JOB:
{prompt}

THE TASK OF THE {role}:
{task}

WHY IT FAILED:
{reason}

Keep the task's goal and every detail of the job it needs, change what made it fail. E.g. when a search found nothing
useful, tell the worker to do the task from its own knowledge and to invent what the job leaves open. When the failure
was bad luck (e.g. a timeout or a tool error), the task may stay as it is. When a file was made in another format than
asked (e.g. audio as .ogg instead of .mp3), that is no failure: let the task accept it, never ask for a conversion.
The failed worker may have made some of the task's files already: tell the new worker to replace the task's own output
files when they are there (with "overwrite": true), never other files.

Respond with a json structure like this:
{{
    "prompt": "the task for the new worker, full instructions"
}}
"""

RETRY_EXCLUDED_TOOLS_PART = " (the new worker can not use these tools: {tools})"

MERGE_PROMPT = """Worker agents did a background job step by step. Merge their results into one report.

THE JOB:
{prompt}

THE RESULTS:
{results}

Respond with a json structure like this:
{{
    "summary": "the answer to the job in one or two sentences",
    "details": "what the user needs to know, keep the facts and numbers the workers gave"
}}

Use only what the results say, add nothing.
A step did only what its "tools used:", "files saved:" and "files offered to the user:" lines show: when it says it made files, ran commands
or tested something but no tool that does that was used, it did not do it.
When the job asks for files and no result has a "files saved:" or "files offered to the user:" line, the summary says that no file was delivered: never call the job done, built or working then.
What a "not checked" line says was not checked stays in the details as not tested, with how far it got and what is missing: never call it tested or working.
"""