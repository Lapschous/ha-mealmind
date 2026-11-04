import json
import re
import sqlite3
import html
import logging
from datetime import date
from pathlib import Path

import ollama

DB_PATH = "backend/src/db/recipes.db"
USERS_DIR = Path("users")
MODEL = "hf.co/mistralai/Ministral-3-8B-Instruct-2512-GGUF:Q4_K_M"
MAX_LLM_CHECKS = 15   # cap on LLM calls per request, to bound latency


# Always banned for vegetarians.
MEAT_WORDS = ["chicken", "beef", "pork", "bacon", "ham", "lamb", "turkey", "sausage",
              "salami", "prosciutto", "chorizo", "mince", "fish", "salmon", "tuna",
              "cod", "shrimp", "prawn", "anchovy", "anchovie", "worcestershire", "gelatin"]
# Banned for vegetarians unless the ingredient says "vegetable".
STOCK_WORDS = ["stock", "broth", "bouillon"]

def random_dinners():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row # each row acts as a dict, not needing index
    cursor = conn.cursor()

    query = """SELECT recipe_id, title, description, preptime_minutes, cooktime_minutes, continent 
                FROM recipe_meta ORDER BY RANDOM() LIMIT 3 
                """

    cursor.execute(query)
    recipes = cursor.fetchall()

    dict_recipes = []
    for row in recipes:
        dict_recipes.append(dict(row))

    conn.close()

    return dict_recipes

def load_user_profile(telegram_id):
    for path in USERS_DIR.glob("*.json"):
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if profile.get("user_id") == telegram_id:
            return profile
    return None

def bot_options_message(random_dinners_dict):

    if not random_dinners_dict:
        return [], "I couldn't find any recipes that fit you right now. Try /dinner again later."

    option_message = "Good morning! Here are your dinner options:\n\n"
    db_recipe_index = [recipe['recipe_id'] for recipe in random_dinners_dict]

    for index, recipe in enumerate(random_dinners_dict, start=1):
        recipe_message = f"<b>Option {index}</b>,\n<i>{recipe['title'].title()}</i>\n{recipe['description']}\nPrep time: {recipe['preptime_minutes']} minutes\nCook time: {recipe['cooktime_minutes']} minutes\nContinent: {recipe['continent']}\n\n"
        option_message += recipe_message

    return db_recipe_index, option_message

def has_banned_ingredients(profile, ingredient_names):
    banned = [w.lower() for w in profile.get("allergies", []) + profile.get("dislikes", [])]
    stock_banned = []
    if profile.get("diet") == "vegetarian":
        banned += MEAT_WORDS
        stock_banned = STOCK_WORDS

    for name in ingredient_names:
        name = name.lower()
        words = banned + ([] if "vegetable" in name else stock_banned)
        for word in words:
            if re.search(rf"\b{re.escape(word)}s?\b", name):
                return True
    return False

def llm_fits(profile, recipe, ingredient_names, tag_names):
    profile_for_llm = {
        k: profile.get(k) for k in 
        ("diet", "allergies", "dislikes", "likes", "cuisines", "spice_tolerance", "goals", "notes")
        }

    prompt = (
        " You decide whether a recipe suits a person. Respond with JSON only:"
        '{"fits": true or false, "reason": "<one short sentence>"}. \n'
        "Respect the person's notes strictly. If unsure, answer false. \n\n"
        f"PERSON:\n{json.dumps(profile_for_llm)}\n\n"
        f"RECIPE:\nTitle: {recipe['title']}\nDescription: {recipe['description']}\n"
        f"Continent: {recipe['continent']}\nTags: {', '.join(tag_names)}\n"
        f"Ingredients: {', '.join(ingredient_names)}\n"
    )

    try:
        response = ollama.chat(
            model= MODEL,
            format = "json",
            messages = [{"role": "user", "content": prompt}],
            options={"temperature": 0.1, "num_ctx": 4096},
            keep_alive="10m",  # stay loaded between checks, unlike the scraper's keep_alive=0
        )
        verdict = json.loads(response.message.content)
        return verdict.get("fits") is True
    except Exception:
        logging.exception("LLM check failed for recipe %s", recipe["recipe_id"])
        return False 

def get_recipe_html(recipe_id):
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()

    # metadata
    cursor.execute(
        "SELECT title, description FROM recipe_meta WHERE recipe_id = ?",
        (recipe_id,),
    )
    meta = cursor.fetchone()
    if meta is None:
        return None
    title, description = meta

    # ingredients
    cursor.execute(
        """
        SELECT ingredients.name,
                recipe_ingredients.amount,
                recipe_ingredients.unit,
                recipe_ingredients.prep_method
        FROM recipe_ingredients
        JOIN ingredients
        ON ingredients.ingredient_id = recipe_ingredients.ingredient_id
        WHERE recipe_ingredients.recipe_id = ?
        ORDER BY recipe_ingredients.recipe_ingredient_id
        """,
        (recipe_id,),
    )
    ingredients = cursor.fetchall()

    # instructions
    cursor.execute(
        """
        SELECT step_number, instruction
        FROM recipe_steps
        WHERE recipe_id = ?
        ORDER BY step_number
        """,
        (recipe_id,),
    )
    steps = cursor.fetchall()

    # putting the message together
    message = f"<b>{html.escape(title).title()}</b>\n"
    message += f"<i>{html.escape(description)}</i>\n\n"

    message += "<b>Ingredients</b>\n"
    for name, amount, unit, prep_method in ingredients:
        message += f"• {amount} {unit} {name}\n"

    message += "\n<b>Instructions</b>\n"
    for step_number, instruction in steps:
        message += f"{step_number}. {html.escape(instruction)}\n"

    return message

def personal_dinners(profile, exclude_ids = (), want = 3):
    cooking = profile.get("cooking", {})
    key = "max_total_minutes_weeknight" if date.today().weekday() < 5 else "max_total_minutes_weekend"
    max_minutes = cooking.get(key, 120)  # default to 2 hours if not specified

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    accepted = []

    try:
        rows = conn.execute(
            """SELECT recipe_id, title, description, preptime_minutes, cooktime_minutes, continent
               FROM recipe_meta
               WHERE preptime_minutes IS NOT NULL AND cooktime_minutes IS NOT NULL
               AND preptime_minutes + cooktime_minutes <= ?
               ORDER BY RANDOM()""",
            (max_minutes,),
        ).fetchall()

        llm_checks = 0
        for row in rows:
            recipe = dict(row)
            if recipe["recipe_id"] in exclude_ids:
                continue

            ingredient_names = [r[0] for r in conn.execute(
                """ SELECT ingredients.name FROM recipe_ingredients
                    JOIN ingredients
                    ON ingredients.ingredient_id = recipe_ingredients.ingredient_id
                    WHERE recipe_ingredients.recipe_id = ?""", (recipe["recipe_id"],))]
            if has_banned_ingredients(profile, ingredient_names):
                continue

            if llm_checks >= MAX_LLM_CHECKS:
                break
            llm_checks += 1

            tag_names = [r[0] for r in conn.execute(
                """SELECT tags.name FROM recipe_tags
                   JOIN tags ON tags.tag_id = recipe_tags.tag_id
                   WHERE recipe_tags.recipe_id = ?""", (recipe["recipe_id"],))]
            if llm_fits(profile, recipe, ingredient_names, tag_names):
                accepted.append(recipe)
                if len(accepted) == want:
                    break
    finally:
        conn.close()
    return accepted
