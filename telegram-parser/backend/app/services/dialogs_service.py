"""
NeuroDialogs Service
ИИ автоответчик на личные сообщения

Based on:
- n3d1117/chatgpt-telegram-bot (GPT-4o, streaming, context management)
  https://github.com/n3d1117/chatgpt-telegram-bot
- biisal/chatgpt-bot (plugin architecture, MongoDB history)
  https://github.com/biisal/chatgpt-bot
- nashirabbash/autorepychatbot (Gemini AI, Groq API)
  https://github.com/nashirabbash/autorepychatbot

Key patterns:
- ConversationContext with max_messages limit (from n3d1117)
- Streaming responses via OpenAI API
- MongoDB-style chat history (adapted to our DB)
- System prompts for different use cases
"""

import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Optional
from sqlalchemy.ext.asyncio import AsyncSession
from app.models.account import Account
from app.services.ai_provider_service import get_ai_client

logger = logging.getLogger(__name__)

# OpenAI Integration
try:
    import openai  # noqa: F401
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    logger.warning("OpenAI not installed. Install with: pip install openai")


# Default system prompts from the repos
DEFAULT_SYSTEM_PROMPTS = {
    "sales": """Ты — ассистент по продажам в Telegram.
Отвечай кратко (до 2-3 предложений), дружелюбно, профессионально.
Не отправляй длинные сообщения.
Если не знаешь ответ — признайся и предложи связаться с менеджером.
Используй естественный язык, не слишком формальный.""",

    "support": """Ты — служба поддержки клиентов.
Отвечай вежливо, предоставляй полезную информацию.
Если нужна помощь специалиста — переключай на менеджера.
Всегда благодари за обращение.""",

    "chatbot": """Ты — дружелюбный собеседник в Telegram.
Поддерживай естественную беседу, будь интересным.
Не отправляй слишком длинные сообщения.
Задавай уточняющие вопросы.""",

    "friend": """Ты — близкий друг пользователя в Telegram. 
Твой стиль общения — неформальный, теплый и искренний. 
Используй сленг, если это уместно, но оставайся вежливым. 
Твоя задача — поддерживать общение, давать советы как другу и просто быть рядом. 
Отвечай кратко, как в обычном мессенджере.""",

    "onboarding": """Ты — бот для онбординга новых пользователей.
Помоги пользователю познакомиться с продуктом.
Отвечай кратко и по делу.
Расскажи о ключевых возможностях.""",
}


class ConversationContext:
    """
    Track conversation context per user.

    From n3d1117/chatgpt-telegram-bot pattern:
    - Maintains message history with max limit
    - Automatically trims old messages
    - Stores role, content, timestamp
    - Age-based expiry (unlike our old count-only approach)
    """

    def __init__(self, max_messages: int = 10, max_age_minutes: int = 60):
        self.messages: List[Dict] = []
        self.max_messages = max_messages
        self.max_age_minutes = max_age_minutes
        self.created_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()

    def add_message(self, role: str, content: str):
        """Add a message to the conversation history."""
        self.messages.append({
            "role": role,
            "content": content,
            "timestamp": datetime.utcnow().isoformat()
        })
        self.last_updated = datetime.utcnow()
        # Keep only last N messages
        if len(self.messages) > self.max_messages:
            self.messages = self.messages[-self.max_messages:]

    def is_expired(self) -> bool:
        """Check if conversation expired by age (from n3d1117 pattern)."""
        age_minutes = (datetime.utcnow() - self.last_updated).total_seconds() / 60
        return age_minutes > self.max_age_minutes

    def get_messages(self) -> List[Dict]:
        """Get all messages for API call."""
        return self.messages

    def clear(self):
        """Clear conversation history."""
        self.messages = []
        self.created_at = datetime.utcnow()
        self.last_updated = datetime.utcnow()

    def count(self) -> int:
        """Get number of messages."""
        return len(self.messages)

    def get_last_n(self, n: int) -> List[Dict]:
        """Get last N messages."""
        return self.messages[-n:] if self.messages else []


# Store active conversations per user (in-memory for now)
# In production, this would be Redis or database
active_conversations: Dict[str, ConversationContext] = {}


async def get_or_create_context(
    account_id: int,
    user_id: str,
    max_messages: int = 10
) -> ConversationContext:
    """Get or create conversation context for a user."""
    # Prune expired contexts to avoid memory leaks
    expired_keys = [k for k, ctx in active_conversations.items() if ctx.is_expired()]
    for k in expired_keys:
        active_conversations.pop(k, None)

    key = f"{account_id}_{user_id}"
    if key not in active_conversations:
        active_conversations[key] = ConversationContext(max_messages=max_messages)
    return active_conversations[key]


async def generate_ai_response(
    prompt: str,
    system_prompt: str = None,
    conversation_history: List[Dict] = None,
    model: str = "gpt-4o-mini",
    max_tokens: int = 200,
    temperature: float = 0.7,
    provider: str = "openai",
) -> Optional[str]:
    """
    Generate AI response using OpenAI API.

    From n3d1117/chatgpt-telegram-bot pattern:
    - System prompt for behavior
    - Conversation history for context
    - Configurable model and parameters

    Args:
        prompt: User message
        system_prompt: System instructions
        conversation_history: Previous messages
        model: OpenAI model to use
        max_tokens: Max response length
        temperature: Response creativity (0-1)

    Returns:
        Generated response or None on error
    """
    if not OPENAI_AVAILABLE:
        logger.warning("OpenAI not available")
        return None

    if system_prompt is None:
        system_prompt = DEFAULT_SYSTEM_PROMPTS["chatbot"]

    try:
        messages = []

        # Add system prompt
        messages.append({"role": "system", "content": system_prompt})

        # Add conversation history (from biisal pattern)
        if conversation_history:
            messages.extend(conversation_history)
            # Avoid duplicating prompt if it's already the last message in history
            if not (conversation_history[-1]["role"] == "user" and conversation_history[-1]["content"] == prompt):
                messages.append({"role": "user", "content": prompt})
        else:
            messages.append({"role": "user", "content": prompt})

        # Generate response
        client = get_ai_client(provider)
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=False,
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"OpenAI error: {e}")
        return None


async def generate_streaming_response(
    prompt: str,
    system_prompt: str = None,
    conversation_history: List[Dict] = None,
    model: str = "gpt-4o-mini",
    max_tokens: int = 200,
    temperature: float = 0.7,
    provider: str = "openai",
):
    """
    Generate streaming AI response (for real-time display).

    From n3d1117/chatgpt-telegram-bot streaming pattern:
    - Yields chunks as they arrive
    - Used for typing indicator simulation

    Usage:
        async for chunk in generate_streaming_response(...):
            display(chunk)
    """
    if not OPENAI_AVAILABLE:
        yield "OpenAI not configured"
        return

    try:
        messages = []

        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})

        if conversation_history:
            messages.extend(conversation_history)
            # Avoid duplicating prompt if it's already the last message in history
            if not (conversation_history[-1]["role"] == "user" and conversation_history[-1]["content"] == prompt):
                messages.append({"role": "user", "content": prompt})
        else:
            messages.append({"role": "user", "content": prompt})

        # Stream response
        client = get_ai_client(provider)
        stream = await client.chat.completions.create(
            model=model,
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )

        full_response = ""
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                full_response += chunk.choices[0].delta.content
                yield chunk.choices[0].delta.content

    except Exception as e:
        yield f"Error: {e}"


async def process_incoming_message(
    account: Account,
    user_id: str,
    message_text: str,
    settings: Dict = None,
) -> Dict:
    """
    Process incoming message and generate auto-response.

    From biisal/chatgpt-bot ai_res pattern:
    1. Get/create conversation context
    2. Add message to history
    3. Generate AI response
    4. Add response to history
    5. Return response with metadata

    Args:
        account: Account model
        user_id: User ID/username
        message_text: Incoming message
        settings: AI settings (prompt, model, etc.)

    Returns:
        Dict with response_text, should_respond, delay_seconds
    """
    if settings is None:
        settings = {}

    result = {
        "account_id": account.id,
        "user_id": user_id,
        "message_received": message_text,
        "response_text": None,
        "should_respond": False,
        "delay_seconds": 0,
        "processed_at": datetime.utcnow().isoformat(),
    }

    # Check if AI is enabled
    if not settings.get("ai_enabled", True):
        return result

    # Get conversation context
    context = await get_or_create_context(
        account.id,
        user_id,
        max_messages=settings.get("context_depth", 10)
    )

    # Add incoming message to context
    context.add_message("user", message_text)

    # Get system prompt
    system_prompt = settings.get(
        "system_prompt",
        DEFAULT_SYSTEM_PROMPTS["chatbot"]
    )

    # Generate response
    response = await generate_ai_response(
        prompt=message_text,
        system_prompt=system_prompt,
        conversation_history=context.get_messages(),
        model=settings.get("model", "gpt-4o-mini"),
        provider=settings.get("provider", "openai"),
    )

    if response:
        result["response_text"] = response
        result["should_respond"] = True

        # Calculate typing delay based on response length
        # From nashirabbash/autorepychatbot pattern
        delay = len(response) // 10  # ~1 second per 10 characters
        delay = max(
            settings.get("min_delay", 5),
            min(delay, settings.get("max_delay", 60))
        )
        result["delay_seconds"] = delay

        # Add response to context
        context.add_message("assistant", response)

    return result


async def send_ai_response(
    client,
    username: str,
    response: str,
    delay: int = 0
):
    """
    Send AI response with typing simulation.

    From autorepychatbot main.py pattern:
    - Show typing indicator
    - Wait for simulated typing
    - Send response
    """
    if delay > 0:
        # Show typing indicator
        await client.send_chat_action(username, "typing")
        await asyncio.sleep(delay)

    # Send the response
    await client.send_message(username, response)


async def setup_ai_for_account(
    db: AsyncSession,
    account: Account,
    system_prompt: str = None,
    context_depth: int = 10,
    min_delay: int = 5,
    max_delay: int = 60,
    model: str = "gpt-4o-mini",
    provider: str = "openai",
) -> bool:
    """
    Setup AI auto-responder for an account.

    From biisal pattern for AI configuration storage.
    """
    try:
        # Validate account has session
        if not account.session_string:
            return False

        # Store AI settings in account health_factors
        account.health_factors = {
            "ai_enabled": True,
            "system_prompt": system_prompt or DEFAULT_SYSTEM_PROMPTS["chatbot"],
            "context_depth": context_depth,
            "min_delay": min_delay,
            "max_delay": max_delay,
            "model": model,
            "provider": provider,
        }
        await db.commit()

        return True

    except Exception as e:
        logger.error(f"Failed to setup AI for account {account.id}: {e}")
        return False


async def get_conversation_summary(conversation_key: str) -> Dict:
    """Get summary of a conversation."""
    if conversation_key not in active_conversations:
        return {"message_count": 0, "messages": [], "is_active": False}

    context = active_conversations[conversation_key]
    return {
        "message_count": context.count(),
        "messages": context.get_last_n(5),
        "is_active": True,
    }


async def clear_conversation(conversation_key: str):
    """Clear conversation history for a user."""
    if conversation_key in active_conversations:
        active_conversations[conversation_key].clear()


def get_default_prompts() -> Dict[str, str]:
    """Get default prompt templates."""
    return DEFAULT_SYSTEM_PROMPTS


async def generate_groq_response(
    prompt: str,
    api_key: str,
    model: str = "llama-3.1-70b-versatile",
) -> Optional[str]:
    """
    Generate response using Groq API (alternative to OpenAI).

    From nashirabbash/autorepychatbot gemini_client.py pattern.
    """
    try:
        from openai import AsyncOpenAI

        groq_client = AsyncOpenAI(
            api_key=api_key,
            base_url="https://api.groq.com/openai/v1",
            max_retries=2
        )

        response = await groq_client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=250,
            temperature=0.7
        )

        return response.choices[0].message.content

    except Exception as e:
        logger.error(f"Groq API error: {e}")
        return None
