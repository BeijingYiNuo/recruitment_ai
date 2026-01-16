import asyncio
from openai import AsyncOpenAI
from time import perf_counter, sleep
from typing import AsyncGenerator,List,Dict
import logging
logger = logging.getLogger(__name__)
class Conf:
    openai_url: str = "https://ark.cn-beijing.volces.com/api/v3/"
    openai_apikey: str = "76a878dc-4905-44c3-858c-8ef33006250f"
    openai_model: str = "doubao-seed-1-6-251015"

async def stream_text_to_llm(
        text_q:asyncio.Queue,
        system_prompt: str = "你是一个拥有20年经验的销售领域面试专家",
        context: List[Dict[str, str]] = None
) -> AsyncGenerator[str, None]:
    """
    监听text_q队列，并实现流式输出LLM处理
    """
    client = AsyncOpenAI(
        api_key=Conf.openai_apikey,
        base_url=Conf.openai_url,
    )
    if context is None:
        context = [{"role":"system","content":system_prompt}]
    
    while True:
        user_input = await text_q.get()
        
        try:
            if not user_input or not user_input.strip():
                continue    
            context.append({"role":"user","content":user_input})

            start_time = perf_counter()
            first_token_received = False
            full_reply_content = ""

            response = await client.chat.completions.create(
                model=Conf.openai_model,
                messages=context,
                stream=True,
                extra_body={"thinking": {"type": "disabled"}},
            )

            async for chunk in response:
                if not first_token_received:
                    delay = perf_counter() - start_time

                    first_token_received = True
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    content = delta.content
                    full_reply_content = content
                    
                    yield full_reply_content
            context.append({"role": "assistant", "content": full_reply_content})
        except Exception as e:
            yield f"Error:{str(e)}"
        finally:
            text_q.task_done()