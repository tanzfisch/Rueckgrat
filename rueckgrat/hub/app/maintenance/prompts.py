"""
the prompts of the nightly maintenance (app.maintenance).

the conversation summary (ConversationSummaryTask) is what search_memory finds old conversations by, so it names what
was talked about rather than retelling it. placeholders, filled with str.format:
  SUMMARY_EARLIER_PART  previous: the conversation's last summary
  SUMMARY_PROMPT        earlier (SUMMARY_EARLIER_PART or ""), messages (one "- role: text" line each), max_words
"""

# ---------------------------------------------------------------- conversation summary (ConversationSummaryTask)

SUMMARY_SYSTEM_PROMPT = "You write short, factual summaries of chat conversations. Use only the given text."

SUMMARY_EARLIER_PART = "EARLIER SUMMARY (of this conversation, may be out of date):\n{previous}\n\n"

SUMMARY_PROMPT = """{earlier}MESSAGES:
{messages}

Summarize the whole conversation in at most {max_words} words, so it can be found again later by its content.
Name the topics, people, places, plans, decisions and facts the user shared. Keep what still matters from the earlier summary.
Plain text, no lists, no preface. Reply with the summary only."""
