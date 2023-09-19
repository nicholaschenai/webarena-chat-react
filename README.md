# Attribution
The original authors of WebArena can be found here:
[[Code](https://github.com/web-arena-x/webarena)]
[[Site](https://webarena.dev/)]
[[Paper](https://arxiv.org/2307.13854)]

The original authors of ReAct can be found here:
[[Paper](https://arxiv.org/abs/2210.03629)]
[[Site](https://react-lm.github.io/)]
[[Code](https://github.com/ysymyth/ReAct)]

# Intro
This repo is a modification of WebArena, forked from version 1c0f414dd7827f0eff5cbfe13cf17331f43e9793 Sep 18, 2023

## Modification: ReAct Prompting
Thought-Action-Observation cycle which works on WebShop. Difference from default CoT: Refactored the code to accommodate ‘chat style’ messages and roles. Previously, it was quite monolithic with all the history being put in the user message, which can cause confusion to the agents as it mistakes the history for instruction. Originally wanted to have thought-action-observation as separate messages but this confuses the agent and it starts deviating from the action format, so the current format is to still group Thought and Action in the same message. Also, agent will do an observation summary to remind itself of the past, without exceeding context limit

Usage:

```python
python run.py --instruction_path agent/prompts/jsons/react.json --agent_type reactprompt --test_start_idx 0 --test_end_idx 812 --model gpt-3.5-turbo --result_dir outputs/react_test
```

### Upgrades
- Just like the original paper, take the most recent x characters to manage context len
    - even so, raw observation takes up a huge chunk of the context that at best, the context can only 2 observations 
    - To circumvent this, agent prompted to also do an Observation Summary. Only the most recent observation is displayed in full, past observations appear in summarized form
- prompt includes stating location of element id so agent doesnt confuse whether it should be on the left or right
- Token counting (approximate, assume 4char=1token)
- prompt to hover over new tab if page has not loaded, but that causes agent to do this more often
- Safeguards in `goto` action to allow whitelist-only sites