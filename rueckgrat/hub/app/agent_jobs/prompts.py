"""
the background jobs' prompts (#152): the Controller plans a job, reviews it after each step, revises a failed task and
merges the results; its workers (AgentJob) do one task each with the tools' results.

placeholders, filled with str.format (literal json braces are doubled):
  WORKER_PROMPT              role (the worker's role in the plan), prompt (its task), tools (the TOOL_RESULTS block or "")
  FAILED_TOOLS_PART          failed: the failed tools with their errors, "; " separated
  PLAN_PROMPT                prompt (the job), max_steps, max_workers
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
RESULTS_MARKER_PART = "\n\nRESULTS OF THE STEPS BEFORE:\n"    # the Controller appends the earlier results to a task after this

WORKER_PROMPT = """You are the {role} in a background job. Do your task and report what you found or made.
Facts, numbers and dates come only from the tool results below and from the task itself. Name the source of each fact as the tool results give it. Never make up facts, numbers or sources.
Stay factual and neutral: report what the sources say, also where they disagree, without taking sides.
If you can not do the task with what you have, or a check of your task failed or could not be run, start your reply with FAILED: and the reason.

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
writing files and generating images the user gets with the job's report. A task that makes files names each file and its path (e.g. index.html, css/style.css).
A software project lives in its own folder ~/projects/<project-name>/ (short, lowercase, e.g. fractal_explorer): every task of the project names that folder,
the task that creates the project also writes its PROJECT.md there (first line: what the project is in one sentence, then its status and how to run it).
To change an existing project, its tasks work in its folder.
When the job makes code or something that runs (a program, a script, a website, a software project), add a last step with a tester task, unless the job is tiny.
Write the tester's prompt as the commands it runs, in order and all at once, with no "if" steps: list the files, set up what the project needs
(e.g. python3 -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt), check every file the job asks for by name
(e.g. python3 -m py_compile a.py b.py, node --check, cmake -B build && cmake --build build), so a missing one fails, run the tests (e.g. pytest)
and run the program with a time limit (e.g. timeout 10 python3 main.py, exit code 124 means it was still running, that passed).
What fails it fixes and runs again in its fix rounds. Then it updates the project's PROJECT.md (status, how to run it), shares the finished project folder with share_file and reports each command it ran with its exit code. A job that only makes text, data or images does not need it.
Say in a task's prompt what it has to look up. A research task names the time period (e.g. "2021 to 2031"), the scope
(e.g. country, measure, which kind of predictions) and the sources it must check (e.g. the central bank, the statistics office, the big banks).

Also give the job a short name of two to five words (e.g. "NZ cash rate forecast").

Respond with a json structure like this:
{{
    "name": "...",
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
was bad luck (e.g. a timeout or a tool error), the task may stay as it is.

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
"""