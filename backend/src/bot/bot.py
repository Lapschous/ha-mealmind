import os
import logging
from dotenv import load_dotenv
import telebot
from recipe_picker import (get_recipe_html, random_dinners, bot_options_message,load_user_profile, personal_dinners)

offered_options = {}  
seen_options = {}     
load_dotenv()

bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
if not bot_token:
    raise RuntimeError("TELEGRAM_BOT_TOKEN is not set")

bot = telebot.TeleBot(token=bot_token, parse_mode="HTML")
telebot.logger.setLevel(logging.DEBUG)  # shows handler errors in the terminal



def build_dinner_options(chat_id, user_id, reroll=False):
    """Pick new dinners, remember them for this chat, return (text, keyboard)."""
    key = (chat_id, user_id)
    profile = load_user_profile(user_id)
    if profile is None:
        dinners = random_dinners()
    else:
        seen = seen_options.get(key, set()) if reroll else set()
        dinners = personal_dinners(profile, exclude_ids=seen)
        seen_options[key] = seen | {r["recipe_id"] for r in dinners}

    db_recipe_index, message = bot_options_message(dinners)
    offered_options[key] = db_recipe_index

    kb = telebot.types.InlineKeyboardMarkup()
    if dinners:
        kb.add(telebot.types.InlineKeyboardButton("Reroll", callback_data="reroll"))
    return message, kb



@bot.message_handler(commands=["greet"])
def start(message):
    welcome_message = f"Hello, <i>{message.from_user.first_name}</i>! I am <i>MealMind</i>.\nUse /help to see what I can do."
    bot.send_message(chat_id=message.chat.id, text=welcome_message)

@bot.message_handler(commands=["user_id"])
def user_id(message):
    user_id_message = f"Your user ID is: <i>{message.from_user.id}</i>"
    bot.send_message(chat_id=message.chat.id, text=user_id_message)


@bot.message_handler(commands=["help"])
def help(message):
    help_message = (
        "Here are the commands you can use:\n"
        "/greet - Receive a greeting message.\n"
        "/help - Show this help message.\n"
        "/dinner - Get a dinner suggestion.\n"
        "/pick - Pick one of the dinner options.\n"
    )
    bot.send_message(chat_id=message.chat.id, text=help_message)


@bot.message_handler(commands=["dinner"])
def dinner(message):
    bot.send_message(message.chat.id,"Checking recipes ... ") # visually indicating that bot is "thinking"
    text, kb = build_dinner_options(message.chat.id, message.from_user.id)
    bot.send_message(message.chat.id, text, reply_markup=kb)


@bot.message_handler(commands=["pick"])
def pick(message):
    options = offered_options.get((message.chat.id, message.from_user.id), [])
    if not options:
        bot.send_message(message.chat.id, "Use /dinner first to get some options.")
        return
    kb = telebot.types.InlineKeyboardMarkup()

    kb.add(*[
        telebot.types.InlineKeyboardButton(f"Option {i}", callback_data=str(recipe_id))
        for i, recipe_id in enumerate(options, start=1)
    ])

    bot.send_message(message.chat.id, "Pick one:", reply_markup=kb)


@bot.callback_query_handler(func=lambda call: call.data == "reroll")
def on_reroll(call):
    bot.answer_callback_query(call.id)
    text, kb = build_dinner_options(call.message.chat.id, call.from_user.id, reroll=True)
    try:
        bot.edit_message_text(
            text,
            chat_id=call.message.chat.id,
            message_id=call.message.message_id,
            reply_markup=kb,
        )
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" not in str(e):
            raise


@bot.callback_query_handler(func=lambda call: call.data.isdigit())
def on_recipe(call):
    bot.answer_callback_query(call.id)
    recipe_id = int(call.data)
    formatted_recipe = get_recipe_html(recipe_id)  # html formatted recipe from the db
    # TODO: Return engineering recipe for the selected recipe_id
    bot.send_message(call.message.chat.id, formatted_recipe)


bot.polling()