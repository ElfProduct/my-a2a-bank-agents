# Feedback Task Playbooks

These playbooks are for human/Codex understanding. Do not hardcode task IDs, task-specific private values, or expected actions into prompts or agent logic.

## General Pattern

1. Preserve role boundaries: personal handles the user and user-side tools; CS handles bank facts, bank tools, KB policy, verification, and escalation.
2. Search before deciding: policy, product terms, referral rules, and tool-discovery instructions live in the KB.
3. Verify before sensitive access: CS must verify identity using required factors before reading or modifying protected customer data.
4. Act only with real values: no placeholders, no invented account details, no invented policy facts.
5. Let the right side act: CS uses bank-side tools; personal uses user-side tools after the user clearly asks or authorizes.

## task_006: Credit Card Recommendation And Application

Principle: a product recommendation should compare the full relevant product set against the user's constraints, then the personal agent should execute the user's requested action with exact known values.

Expected pattern:

- Personal gathers only needed missing facts, then asks CS for a comparison.
- CS searches credit-card docs for relevant card terms: annual fees, cashback, subscription requirements, and eligibility.
- CS compares Bronze, Silver, Gold, Platinum, and any other relevant personal cards instead of answering from one document.
- CS recommends `Gold Rewards Card` when supported by docs and user constraints.
- Personal confirms or infers from the user's clear request that the user wants to apply.
- Personal calls `apply_for_credit_card` with exact user details, including subscription status when the user has provided it.

Risk to avoid:

- Recommending Platinum because it is premium while missing the annual fee constraint.
- Forgetting that the user may reveal Rho-Bank+ only when asked.
- Telling the user to apply themselves instead of using the available user-side tool when requested.

## task_009: Email Change With Verification Failure

Principle: when protected account changes cannot be verified under policy, the CS agent should escalate with the specific reason code instead of weakening verification or inventing a workaround.

Expected pattern:

- Personal asks CS about the requested email change.
- CS recognizes email change as a protected account setting change.
- CS asks for verification factors and checks them using bank-side read tools.
- CS requires two valid factors among date of birth, email, phone, and address; name or user ID is not enough.
- If the customer cannot provide enough verification, CS explains that it cannot complete the change.
- When the customer requests transfer after unresolved verification, CS uses `transfer_to_human_agents` with reason `account_ownership_dispute`.

Risk to avoid:

- Treating email plus phone as enough without checking the exact policy and customer record.
- Asking the personal agent to perform bank-side account updates.
- Using a vague transfer reason when a specific identity-verification failure reason applies.

## task_053: Checking Referral Optimization

Principle: referral tasks combine product comparison with eligibility checks; the agent must optimize the combined referrer/referred bonus only after confirming the user can successfully submit a referral now.

Expected pattern:

- Personal asks CS for referral-program comparison and eligibility.
- CS verifies identity before reading account/referral history.
- CS searches general checking referral rules and individual account referral docs.
- CS checks the rolling 9-day limit and existing referral history.
- CS compares combined bonuses for all candidate checking accounts that qualify for the friend's expected deposit.
- CS recommends `Blue Account` when eligible because its combined bonus is highest for the stated deposit.
- Personal asks for or uses the real user id only if available and then calls user-side `submit_referral` with `account_type` exactly `Blue Account`.

Risk to avoid:

- Only comparing account types the customer already owns.
- Missing that referrals across different checking account types share one rolling-window limit.
- Submitting a referral before CS confirms current eligibility.
- Omitting the word `Account` from the `account_type`.

