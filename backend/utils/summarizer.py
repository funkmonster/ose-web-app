"""
Campaign summarizer.

Every SUMMARIZE_EVERY player actions, this module:
  1. Pulls the last SUMMARIZE_CONTEXT_WINDOW messages from the session log
  2. Asks the LLM to distill them into a dense factual summary
  3. Merges that with any existing summary stored in world_state['campaign_summary']
  4. Writes the updated summary back to world_state

The summary is then prepended to every GM prompt, giving the LLM permanent
long-term memory regardless of how long the campaign runs.
"""

import logging
from utils.llm import get_gm_response

log = logging.getLogger("ose-bot.summarizer")

SUMMARY_KEY = "campaign_summary"
ACTION_COUNT_KEY = "player_action_count"

SUMMARIZER_PROMPT = """You are a campaign chronicler for a B/X D&D adventure.
Your job is to maintain a concise, factual running summary of a campaign.
You will be given the existing summary (if any) and a batch of recent session transcript.
Produce an updated summary that:
- Is written as dense, factual bullet points (not prose)
- Covers: locations visited, enemies fought and outcomes, items found, NPCs met and their disposition, quests active or resolved, party decisions and their consequences
- Preserves all important facts from the existing summary
- Incorporates new events from the recent transcript
- Drops minor flavor detail that has no future gameplay relevance
- Stays under 600 words total
Respond with ONLY the bullet-point summary. No preamble, no headers."""


async def maybe_update_summary(db, campaign_id: int, config) -> bool:
    """
    Increment the player action counter. If it hits the threshold,
    trigger a summary update and reset the counter.
    Returns True if a summary was generated.
    """
    world = await db.get_world_state(campaign_id)
    count = int(world.get(ACTION_COUNT_KEY, "0")) + 1
    await db.set_world_state(campaign_id, ACTION_COUNT_KEY, str(count))

    if count % config.SUMMARIZE_EVERY != 0:
        return False

    log.info(f"Campaign {campaign_id}: triggering summary update at action {count}.")
    await _generate_summary(db, campaign_id, config)
    return True


async def _generate_summary(db, campaign_id: int, config):
    """Pull recent history, call the LLM, store the result."""
    world = await db.get_world_state(campaign_id)
    existing_summary = world.get(SUMMARY_KEY, "")

    history = await db.get_history(campaign_id, limit=config.SUMMARIZE_CONTEXT_WINDOW)
    transcript_lines = []
    for row in history:
        author = row.get("author_name") or row["role"]
        transcript_lines.append(f"[{author}]: {row['content']}")
    transcript = "\n".join(transcript_lines)

    user_content = ""
    if existing_summary:
        user_content += f"EXISTING SUMMARY:\n{existing_summary}\n\n"
    user_content += f"RECENT TRANSCRIPT:\n{transcript}\n\nProduce the updated summary now."

    messages = [{"role": "user", "content": user_content}]

    try:
        # Use a lightweight system prompt — this is a summarization task, not GM narration
        provider = config.LLM_PROVIDER.lower()
        if provider == "anthropic":
            import anthropic as _anthropic
            client = _anthropic.AsyncAnthropic(api_key=config.ANTHROPIC_API_KEY)
            response = await client.messages.create(
                model=config.ANTHROPIC_MODEL,
                max_tokens=800,
                system=SUMMARIZER_PROMPT,
                messages=messages,
            )
            new_summary = response.content[0].text.strip()

        elif provider == "openai":
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=config.OPENAI_API_KEY)
            response = await client.chat.completions.create(
                model=config.OPENAI_MODEL,
                max_tokens=800,
                messages=[{"role": "system", "content": SUMMARIZER_PROMPT}] + messages,
            )
            new_summary = response.choices[0].message.content.strip()

        else:
            # Ollama / fallback: reuse the generic get_gm_response with inline system
            full_content = SUMMARIZER_PROMPT + "\n\n" + user_content
            new_summary = await get_gm_response(
                [{"role": "user", "content": full_content}], config
            )
            new_summary = new_summary.strip()

        await db.set_world_state(campaign_id, SUMMARY_KEY, new_summary)
        log.info(f"Campaign {campaign_id}: summary updated ({len(new_summary)} chars).")

    except Exception as e:
        log.error(f"Summary generation failed for campaign {campaign_id}: {e}")
        # Non-fatal — the bot continues without an updated summary
