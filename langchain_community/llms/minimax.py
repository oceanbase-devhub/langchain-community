"""Wrapper around Minimax APIs."""

from __future__ import annotations

import logging
from typing import (
    Any,
    Dict,
    List,
    Optional,
)

import requests
from langchain_core.callbacks import (
    CallbackManagerForLLMRun,
)
from langchain_core.language_models.llms import LLM
from langchain_core.utils import convert_to_secret_str, get_from_dict_or_env, pre_init
from pydantic import BaseModel, Field, SecretStr, model_validator

from langchain_community.llms.utils import enforce_stop_tokens

logger = logging.getLogger(__name__)


class _MinimaxEndpointClient(BaseModel):
    """API client for the Minimax LLM endpoint."""

    host: str
    group_id: str
    api_key: SecretStr
    api_url: str

    @model_validator(mode="before")
    @classmethod
    def set_api_url(cls, values: Dict[str, Any]) -> Any:
        if "api_url" not in values:
            host = values["host"]
            group_id = values["group_id"]
            api_url = f"{host}/v1/text/chatcompletion?GroupId={group_id}"
            values["api_url"] = api_url
        return values

    def post(self, request: Any) -> Any:
        headers = {"Authorization": f"Bearer {self.api_key.get_secret_value()}"}
        response = requests.post(self.api_url, headers=headers, json=request)
        # TODO: error handling and automatic retries
        if not response.ok:
            raise ValueError(f"HTTP {response.status_code} error: {response.text}")
        if response.json()["base_resp"]["status_code"] > 0:
            raise ValueError(
                f"API {response.json()['base_resp']['status_code']}"
                f" error: {response.json()['base_resp']['status_msg']}"
            )
        return response.json()["reply"]


class MinimaxCommon(BaseModel):
    """Common parameters for Minimax large language models."""

    _client: _MinimaxEndpointClient
    model: str = "abab5.5-chat"
    """Model name to use."""
    max_tokens: int = 256
    """Denotes the number of tokens to predict per generation."""
    temperature: float = 0.7
    """A non-negative float that tunes the degree of randomness in generation."""
    top_p: float = 0.95
    """Total probability mass of tokens to consider at each step."""
    model_kwargs: Dict[str, Any] = Field(default_factory=dict)
    """Holds any model parameters valid for `create` call not explicitly specified."""
    minimax_api_host: Optional[str] = None
    minimax_group_id: Optional[str] = None
    minimax_api_key: Optional[SecretStr] = None

    @pre_init
    def validate_environment(cls, values: Dict) -> Dict:
        """Validate that api key and python package exists in environment."""
        values["minimax_api_key"] = convert_to_secret_str(
            get_from_dict_or_env(values, "minimax_api_key", "MINIMAX_API_KEY")
        )
        values["minimax_group_id"] = get_from_dict_or_env(
            values, "minimax_group_id", "MINIMAX_GROUP_ID"
        )
        # Get custom api url from environment.
        values["minimax_api_host"] = get_from_dict_or_env(
            values,
            "minimax_api_host",
            "MINIMAX_API_HOST",
            default="https://api.minimax.chat",
        )
        values["_client"] = _MinimaxEndpointClient(  # type: ignore[call-arg]
            host=values["minimax_api_host"],
            api_key=values["minimax_api_key"],
            group_id=values["minimax_group_id"],
        )
        return values

    @property
    def _default_params(self) -> Dict[str, Any]:
        """Get the default parameters for calling OpenAI API."""
        return {
            "model": self.model,
            "tokens_to_generate": self.max_tokens,
            "temperature": self.temperature,
            "top_p": self.top_p,
            **self.model_kwargs,
        }

    @property
    def _identifying_params(self) -> Dict[str, Any]:
        """Get the identifying parameters."""
        return {**{"model": self.model}, **self._default_params}

    @property
    def _llm_type(self) -> str:
        """Return type of llm."""
        return "minimax"


class Minimax(MinimaxCommon, LLM):
    """Minimax large language models.

    To use, you should have the environment variable
    ``MINIMAX_API_KEY`` and ``MINIMAX_GROUP_ID`` set with your API key,
    or pass them as a named parameter to the constructor.
    Example:
     . code-block:: python
         from langchain_community.llms.minimax import Minimax
         minimax = Minimax(model="<model_name>", minimax_api_key="my-api-key",
          minimax_group_id="my-group-id")
    """

    def _call(
        self,
        prompt: str,
        stop: Optional[List[str]] = None,
        run_manager: Optional[CallbackManagerForLLMRun] = None,
        **kwargs: Any,
    ) -> str:
        r"""Call out to Minimax's completion endpoint to chat
        Args:
            prompt: The prompt to pass into the model.
        Returns:
            The string generated by the model.
        Example:
            .. code-block:: python
                response = minimax("Tell me a joke.")
        """
        request = self._default_params
        request["messages"] = [{"sender_type": "USER", "text": prompt}]
        request.update(kwargs)
        text = self._client.post(request)
        if stop is not None:
            # This is required since the stop tokens
            # are not enforced by the model parameters
            text = enforce_stop_tokens(text, stop)

        return text
