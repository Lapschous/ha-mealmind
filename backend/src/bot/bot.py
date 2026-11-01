import os
from dotenv import load_dotenv
import telebot
from recipe_picker import get_recipe_html, random_dinners, bot_options_message, get_recipe_html

load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
if not bot_token:
	raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

bot = telebot.TeleBot(token=bot_token, parse_mode="HTML")  

offered_options = {}  

def build_dinner_options(chat_id):
    """Pick new dinners, remember them for this chat, return (text, keyboard)."""
    dinner_suggestion = random_dinners()
    db_recipe_index, suggestion_message = bot_options_message(dinner_suggestion)
    offered_options[chat_id] = db_recipe_index

    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("Reroll?", callback_data="reroll"))
    return suggestion_message, kb


@bot.message_handler(commands=["dinner"])
def dinner(message):
    text, kb = build_dinner_options(message.chat.id)
    bot.send_message(message.chat.id, text, reply_markup=kb)        

@bot.callback_query_handler(func=lambda call: call.data == "reroll")
def on_reroll(call):
    bot.answer_callback_query(call.id)                              
    text, kb = build_dinner_options(call.message.chat.id)
    bot.edit_message_text(                                          
        text,
        chat_id=call.message.chat.id,
        message_id=call.message.message_id,
        reply_markup=kb,
    )


@bot.message_handler(commands=["pick"])
def pick(message):
    options = offered_options.get(message.chat.id, [])
    if len(options) < 3:
        bot.send_message(message.chat.id, "Use /dinner first to get some options.")
        return

    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(*[
        telebot.types.InlineKeyboardButton(f"Option {i + 1}", callback_data=str(rid))
        for i, rid in enumerate(options[:3])
    ])
    bot.send_message(message.chat.id, "Pick one:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data.isdigit())
def on_recipe(call):
    bot.answer_callback_query(call.id)
    formatted_recipe = get_recipe_html(int(call.data))
    bot.send_message(call.message.chat.id, formatted_recipe)