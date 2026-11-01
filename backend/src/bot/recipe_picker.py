import sqlite3
import html

def random_dinners():
    db_path = "backend/src/db/recipes.db"

    conn = sqlite3.connect(db_path)
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

def bot_options_message(random_dinners_dict):
    option_message = "Good morning! Here are your dinner options:\n\n"
    db_recipe_index = [recipe['recipe_id'] for recipe in random_dinners_dict]

    for index, recipe in enumerate(random_dinners_dict, start=1):
        recipe_message = f"<b>Option {index}</b>,\n<i>{recipe['title'].title()}</i>\n{recipe['description']}\nPrep time: {recipe['preptime_minutes']} minutes\nCook time: {recipe['cooktime_minutes']} minutes\nContinent: {recipe['continent']}\n\n"
        option_message += recipe_message

    return db_recipe_index, option_message

def get_recipe_html(recipe_id):
    db_path = "backend/src/db/recipes.db"

    conn = sqlite3.connect(db_path)
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