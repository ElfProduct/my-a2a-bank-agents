# A2A Hackathon Agent Instructions

This is a competition repo based on `a2anet/a2a-hackathon-template`.

- Never change the required Docker Compose shape: `personal-agent`, `cs-agent`, and `redis`.
- Never change marked runs away from `gemini-3.5-flash`.
- Never hardcode hidden tasks, hidden env data, or task IDs into prompts or agent logic.
- Never commit API keys or secrets.
- Always preserve the incoming A2A `contextId`.
- Always fetch environment tools from the env API.
- The personal agent owns user-side tools and user-facing conversation.
- The CS agent owns bank-side tools, policy, KB search, verification, and escalation.
- Improvements should be evaluated with smoke, feedback, and train runs.
- Prefer small commits with measured score impact.

