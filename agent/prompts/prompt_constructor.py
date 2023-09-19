import json
import re
from pathlib import Path
from typing import Any, TypedDict

import tiktoken
from beartype import beartype

from browser_env import Action, ActionParsingError, Trajectory
from browser_env.env_config import URL_MAPPINGS
from browser_env.utils import StateInfo
from llms import lm_config

APIInput = str | list[Any] | dict[str, Any]


class Instruction(TypedDict):
    """Instruction for constructing prompt"""

    intro: str
    examples: list[tuple[str, str]]
    template: str
    meta_data: dict[str, Any]


class PromptConstructor(object):
    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: tiktoken.core.Encoding,
    ):
        self.instrction_path = Path(instruction_path)
        self.obs_modality = "text"
        self.lm_config = lm_config
        instruction = json.load(open(self.instrction_path))
        instruction["examples"] = [tuple(e) for e in instruction["examples"]]
        self.instruction: Instruction = instruction
        self.tokenizer = tokenizer

    @beartype
    def get_lm_api_input(
        self, intro: str, examples: list[tuple[str, str]], current: str
    ) -> APIInput:

        """Return the require format for an API"""
        message: list[dict[str, str]] | str
        if "openai" in self.lm_config.provider:
            if self.lm_config.mode == "chat":
                message = [{"role": "system", "content": intro}]
                for (x, y) in examples:
                    message.append(
                        {
                            "role": "system",
                            "name": "example_user",
                            "content": x,
                        }
                    )
                    message.append(
                        {
                            "role": "system",
                            "name": "example_assistant",
                            "content": y,
                        }
                    )
                message.append({"role": "user", "content": current})
                return message
            elif self.lm_config.mode == "completion":
                message = f"{intro}\n\n"
                message += "Here are a few examples:\n"
                for example in examples:
                    message += f"Observation\n:{example[0]}\n\n"
                    message += f"Action: {example[1]}\n\n"
                message += "Now make prediction given the observation\n\n"
                message += f"Observation\n:{current}\n\n"
                message += "Action:"
                return message
            else:
                raise ValueError(
                    f"OpenAI models do not support mode {self.lm_config.mode}"
                )
        else:
            raise NotImplementedError(
                f"Provider {self.lm_config.provider} not implemented"
            )

    @beartype
    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        raise NotImplementedError

    @beartype
    def map_url_to_real(self, url: str) -> str:
        """Map the urls to their real world counterparts"""
        for i, j in URL_MAPPINGS.items():
            if i in url:
                url = url.replace(i, j)
        return url

    @beartype
    def map_url_to_local(self, url: str) -> str:
        """Map the urls to their local counterparts"""
        for i, j in URL_MAPPINGS.items():
            if j in url:
                url = url.replace(j, i)
        return url

    @beartype
    def _extract_action(self, response: str) -> str:
        raise NotImplementedError

    @beartype
    def extract_action(self, response: str) -> str:
        response = self._extract_action(response)
        response = self.map_url_to_local(response)
        return response


class DirectPromptConstructor(PromptConstructor):
    """The agent will direct predict the action"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: tiktoken.core.Encoding,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)

    @beartype
    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        """Construct prompt given the trajectory"""
        intro = self.instruction["intro"]
        examples = self.instruction["examples"]
        template = self.instruction["template"]
        keywords = self.instruction["meta_data"]["keywords"]
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]

        page = state_info["info"]["page"]
        url = page.url
        previous_action_str = meta_data["action_history"][-1]

        # input x
        current = template.format(
            objective=intent,
            url=self.map_url_to_real(url),
            observation=obs,
            previous_action=previous_action_str,
        )

        # make sure all keywords are replaced
        assert all([f"{{k}}" not in current for k in keywords])
        prompt = self.get_lm_api_input(intro, examples, current)
        return prompt

    @beartype
    def _extract_action(self, response: str) -> str:
        action_splitter = self.instruction["meta_data"]["action_splitter"]
        pattern = rf"{action_splitter}(.*?){action_splitter}"
        match = re.search(pattern, response)
        if match:
            return match.group(1)
        else:
            raise ActionParsingError(
                f"Cannot parse action from response {response}"
            )


class CoTPromptConstructor(PromptConstructor):
    """The agent will perform step-by-step reasoning before the answer"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: tiktoken.core.Encoding,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)
        self.answer_phrase = self.instruction["meta_data"]["answer_phrase"]

    @beartype
    def construct(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        intro = self.instruction["intro"]
        examples = self.instruction["examples"]
        template = self.instruction["template"]
        keywords = self.instruction["meta_data"]["keywords"]
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]

        page = state_info["info"]["page"]
        url = page.url
        previous_action_str = meta_data["action_history"][-1]
        current = template.format(
            objective=intent,
            url=self.map_url_to_real(url),
            observation=obs,
            previous_action=previous_action_str,
        )

        assert all([f"{{k}}" not in current for k in keywords])

        prompt = self.get_lm_api_input(intro, examples, current)
        return prompt

    @beartype
    def _extract_action(self, response: str) -> str:
        # find the first occurence of action
        action_splitter = self.instruction["meta_data"]["action_splitter"]
        pattern = rf"{action_splitter}(.*?){action_splitter}"
        match = re.search(pattern, response)
        if match:
            return match.group(1)
        else:
            raise ActionParsingError(
                f'Cannot find the answer phrase "{self.answer_phrase}" in "{response}"'
            )

class ReactPromptConstructor(PromptConstructor):
    """The agent will perform step-by-step reasoning before the answer"""

    def __init__(
        self,
        instruction_path: str | Path,
        lm_config: lm_config.LMConfig,
        tokenizer: tiktoken.core.Encoding,
    ):
        super().__init__(instruction_path, lm_config, tokenizer)
        self.answer_phrase = self.instruction["meta_data"]["answer_phrase"]
        self.sys_prompt = self.get_lm_api_initialize()
        self.sys_tokens = sum([len(msg['content']) for msg in self.sys_prompt])/4
        self.messages = []
        self.messages_tokens_list = []
        self.messages_token_sum = 0
        self.intent = ""
        self.intent_tokens = 0
        self.msg_start_idx = 0

    def get_lm_api_initialize(self):
        """Return the required format for an API"""
        message: list[dict[str, str]] | str
        if "openai" in self.lm_config.provider:
            if self.lm_config.mode == "chat":
                message = [{"role": "system", "content": self.instruction["intro"]}]
                for (user_msg, assistant_msg) in self.instruction["examples"]:
                    message.append(
                        {
                            "role": "system",
                            "name": "example_user",
                            "content": user_msg,
                        }
                    )
                    message.append(
                        {
                            "role": "system",
                            "name": "example_assistant",
                            "content": assistant_msg,
                        }
                    )

                return message
            elif self.lm_config.mode == "completion":
                message = f"{self.instruction['intro']}\n\n"
                message += "Here are a few examples:\n"
                for example in self.instruction["examples"]:
                    message += f"Observation\n:{example[0]}\n\n"
                    message += f"Action: {example[1]}\n\n"
                return message
            else:
                raise ValueError(
                    f"OpenAI models do not support mode {self.lm_config.mode}"
                )
        else:
            raise NotImplementedError(
                f"Provider {self.lm_config.provider} not implemented"
            )

    def get_lm_api_input(
        self, intro: str, examples: list[tuple[str, str]], current: str
    ) -> APIInput:

        """Return the require format for an API"""
        message: list[dict[str, str]] | str
        if "openai" in self.lm_config.provider:
            if self.lm_config.mode == "chat":
                message = [{"role": "user", "content": current}]
                return message
            elif self.lm_config.mode == "completion":
                message += "Now make thoughts given the observation\n\n"
                message += f"Observation\n:{current}\n\n"
                message += "Thought:"
                return message
            else:
                raise ValueError(
                    f"OpenAI models do not support mode {self.lm_config.mode}"
                )
        else:
            raise NotImplementedError(
                f"Provider {self.lm_config.provider} not implemented"
            )

    def get_limited_message_history(self):
        """
        fn to limit history so it can fit context length
        """
        tot_tokens = self.sys_tokens+self.intent_tokens+self.messages_token_sum+self.lm_config.gen_config["max_tokens"]
        print(f'total tokens: {tot_tokens} \n')
        while tot_tokens > self.lm_config.gen_config["context_length"]:
            print('\n Context limit reached, truncating')
            self.messages_token_sum -= self.messages_tokens_list[self.msg_start_idx]
            self.msg_start_idx += 1
            tot_tokens = self.sys_tokens + self.intent_tokens + self.messages_token_sum + self.lm_config.gen_config[
                "max_tokens"]
            print(f'total tokens: {tot_tokens} \n')

        return self.messages[self.msg_start_idx:]

    def construct_thought(
        self,
        trajectory: Trajectory,
        intent: str,
        meta_data: dict[str, Any] = {},
    ) -> APIInput:
        # intro = self.instruction["intro"]
        # examples = self.instruction["examples"]
        template = self.instruction["template"]
        keywords = self.instruction["meta_data"]["keywords"]
        state_info: StateInfo = trajectory[-1]  # type: ignore[assignment]

        obs = state_info["observation"][self.obs_modality]
        max_obs_length = self.lm_config.gen_config["max_obs_length"]
        if max_obs_length:
            obs = self.tokenizer.decode(self.tokenizer.encode(obs)[:max_obs_length])  # type: ignore[arg-type]

        page = state_info["info"]["page"]
        url = page.url
        previous_action_str = meta_data["action_history"][-1]
        if previous_action_str.startswith('Attempt to perfom') or previous_action_str.startswith('The previous prediction you issued was'):
            error_msg = previous_action_str
        else:
            error_msg = "None"
        current = template.format(
            url=self.map_url_to_real(url),
            previous_action=self.map_url_to_real(error_msg),
        )

        assert all([f"{{k}}" not in obs for k in keywords])
        assert all([f"{{k}}" not in current for k in keywords])

        # self.messages += self.get_lm_api_input("", [], current)
        # curr_tokens = len(current)/4
        # self.messages_tokens_list.append(curr_tokens)
        # self.messages_token_sum += curr_tokens

        self.add_message(current, "user")
        self.add_message("OBSERVATION: \n" + obs, "user")

        prompt = self.sys_prompt + self.intent + self.get_limited_message_history()

        print('prompt \n')
        for item in prompt:
            print(item)
            print('\n')
        return prompt

    def add_message(self, msg, role="assistant"):
        self.messages.append({"role": role, "content": msg})
        msg_tokens = len(msg) / 4
        self.messages_tokens_list.append(msg_tokens)
        self.messages_token_sum += msg_tokens
    def remove_obs(self):
        """
        removes previous observation
        """
        prev_msg = self.messages[-1]
        if prev_msg["role"]=="user" and prev_msg["content"].startswith("OBSERVATION:"):
            print('removing previous observation')
            self.messages.pop()
            self.messages_tokens_list.pop()
            self.messages_token_sum -= len(prev_msg["content"])/4
    # @beartype
    # def construct(
    #     self,
    #     trajectory: Trajectory,
    #     intent: str,
    #     meta_data: dict[str, Any] = {},
    # ) -> APIInput:
    #     prompt = self.sys_prompt + self.intent + self.get_limited_message_history()
    #
    #     print('prompt \n')
    #     for item in prompt:
    #         print(item)
    #         print('\n')
    #     return prompt

    @beartype
    def _extract_action(self, response: str) -> str:
        # find the first occurence of action
        print('response\n')
        print(response)
        action_splitter = self.instruction["meta_data"]["action_splitter"]
        pattern = rf"{action_splitter}(.*?){action_splitter}"
        match = re.search(pattern, response)
        print('\n matched action \n')
        if match:
            print(match.group(1))
            return match.group(1)
        else:
            print('cannot find answer phrase in response')
            raise ActionParsingError(
                f'Cannot find the answer phrase "{self.answer_phrase}" in "{response}"'
            )
