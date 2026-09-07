import json
import unittest

import httpx

from ai_providers import AIConfig, generate, stream


class AIProviderTest(unittest.TestCase):
    def client_for(self, handler):
        return httpx.Client(transport=httpx.MockTransport(handler))

    def test_openai_uses_responses_api_and_extracts_text_and_tokens(self):
        def handler(request):
            self.assertEqual(request.url.path, "/v1/responses")
            self.assertEqual(request.headers["authorization"], "Bearer secret")
            body = json.loads(request.content)
            self.assertEqual(body["model"], "gpt-test")
            self.assertFalse(body["store"])
            return httpx.Response(200, json={
                "output": [{"type": "message", "content": [{"type": "output_text", "text": "OpenAI 解答"}]}],
                "usage": {"total_tokens": 12},
            })
        result = generate(AIConfig("openai", "gpt-test", "secret"), "prompt", self.client_for(handler))
        self.assertEqual(result.text, "OpenAI 解答")
        self.assertEqual(result.total_tokens, 12)

    def test_anthropic_uses_messages_api(self):
        def handler(request):
            self.assertEqual(request.url.path, "/v1/messages")
            self.assertEqual(request.headers["x-api-key"], "secret")
            self.assertEqual(request.headers["anthropic-version"], "2023-06-01")
            return httpx.Response(200, json={
                "content": [{"type": "text", "text": "Claude 解答"}],
                "usage": {"input_tokens": 4, "output_tokens": 6},
            })
        result = generate(AIConfig("anthropic", "claude-test", "secret"), "prompt", self.client_for(handler))
        self.assertEqual(result.text, "Claude 解答")
        self.assertEqual(result.total_tokens, 10)

    def test_ollama_uses_openai_compatible_endpoint_without_required_key(self):
        def handler(request):
            self.assertEqual(request.url.path, "/v1/chat/completions")
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "本機解答"}}],
                "usage": {"total_tokens": 7},
            })
        config = AIConfig("ollama", "llama-test", "", "http://127.0.0.1:11434/v1")
        result = generate(config, "prompt", self.client_for(handler), allow_private_endpoint=True)
        self.assertEqual(result.text, "本機解答")

    def test_ollama_stream_parses_openai_sse(self):
        def handler(_request):
            body = (
                'data: {"choices":[{"delta":{"content":"甲"}}]}\n\n'
                'data: {"choices":[{"delta":{"content":"乙"}}],"usage":{"total_tokens":9}}\n\n'
                'data: [DONE]\n\n'
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        chunks = list(stream(
            AIConfig("ollama", "llama-test", "", "http://127.0.0.1:11434/v1"),
            "prompt", self.client_for(handler), allow_private_endpoint=True,
        ))
        self.assertEqual("".join(chunk.text for chunk in chunks), "甲乙")
        self.assertEqual(chunks[-1].total_tokens, 9)

    def test_anthropic_stream_accumulates_input_and_output_tokens(self):
        def handler(_request):
            body = (
                'data: {"type":"message_start","message":{"usage":{"input_tokens":4}}}\n\n'
                'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"解"}}\n\n'
                'data: {"type":"message_delta","usage":{"output_tokens":6}}\n\n'
            )
            return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})
        chunks = list(stream(
            AIConfig("anthropic", "claude-test", "secret"), "prompt", self.client_for(handler)
        ))
        self.assertEqual("".join(chunk.text for chunk in chunks), "解")
        self.assertEqual(chunks[-1].total_tokens, 10)

    def test_custom_private_endpoint_is_rejected_in_hosted_mode(self):
        with self.assertRaisesRegex(ValueError, "私人網路"):
            generate(
                AIConfig("openai", "gpt-test", "secret", "http://127.0.0.1:9999/v1"),
                "prompt", self.client_for(lambda _request: None),
            )


if __name__ == "__main__":
    unittest.main()
